import json
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import AuditEvent, DealPacket, PolicyEvaluation
from .services import (
    build_idempotency_key,
    compute_status_from_policy,
    compute_request_fingerprint,
    create_system_audit_event,
    create_tenant_audit_event,
    emit_result_payload,
    evaluate_policy,
    get_active_policy_config,
    resolve_quote_for_packet,
    resolve_tenant_context,
    route_approvals_for_packet,
    serialize_audit_event,
    serialize_deal_packet,
    validate_deal_packet_schema,
)


def _json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body)
    except json.JSONDecodeError:
        return None


def _error(message: str, status: int = 400, code: str | None = None):
    payload = {"error": message}
    if code:
        payload["code"] = code
    return JsonResponse(payload, status=status)


def _resolve_actor(data, request):
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        return user

    username = (data.get("username") or "").strip()
    if not username:
        return None

    User = get_user_model()
    return User.objects.filter(username=username).first()


def _resolve_tenant_or_error(request, data, *, channel: str):
    explicit_tenant_id = data.get("tenant_id") if channel == "orchestrator" else None
    resolution = resolve_tenant_context(request, channel=channel, explicit_tenant_id=explicit_tenant_id)
    if resolution.ok:
        return resolution, None

    create_system_audit_event(
        source=channel,
        event_type=resolution.error_code or "tenant_error",
        request_meta=resolution.presented,
        idempotency_key=(request.headers.get("Idempotency-Key") or ""),
    )

    return None, _error(
        resolution.error_message or "Tenant resolution failed.",
        status=resolution.status_code,
        code=resolution.error_code,
    )


def _build_external_ref(payload, data):
    external_ref_type = (
        data.get("external_ref_type")
        or payload.get("external_ref_type")
        or ("opportunity" if (payload.get("opportunity") or {}).get("id") is not None else "deal_packet")
    )
    external_ref_id = data.get("external_ref_id")
    if not external_ref_id:
        if external_ref_type == "opportunity":
            external_ref_id = str((payload.get("opportunity") or {}).get("id") or "unknown")
        elif external_ref_type == "quote":
            external_ref_id = str(payload.get("quote_ref") or "unknown")
        else:
            external_ref_id = "unknown"
    return external_ref_type, str(external_ref_id)


def _build_response(packet: DealPacket, *, policy_eval: PolicyEvaluation | None = None, replayed: bool = False):
    payload = {
        "deal_packet": serialize_deal_packet(packet),
        "replayed": replayed,
    }
    if policy_eval is not None:
        payload["policy_evaluation"] = {
            "id": policy_eval.id,
            "policy_version": policy_eval.policy_version,
            "results_json": policy_eval.results_json,
            "created_at": policy_eval.created_at.isoformat(),
        }
        payload["crm_sync_payload"] = emit_result_payload(deal_packet=packet, policy_eval=policy_eval)
    return payload


@csrf_exempt
def review_deal_packet(request):
    if request.method != "POST":
        return _error("Only POST allowed", status=405)

    data = _json_body(request)
    if data is None:
        return _error("Invalid JSON", status=400)

    channel = (data.get("channel") or request.headers.get("X-Channel") or "api").strip().lower()
    resolution, response = _resolve_tenant_or_error(request, data, channel=channel)
    if response is not None:
        return response

    tenant_id = resolution.tenant_id
    actor = _resolve_actor(data, request)

    deal_payload = data.get("deal_packet") or data.get("deal_inputs") or {}
    if not isinstance(deal_payload, dict):
        return _error("'deal_packet' must be an object", status=400)

    deal_payload.setdefault("schema_version", "1.0")

    policy_version, policy_config, ttl_hours = get_active_policy_config(tenant_id)
    external_ref_type, external_ref_id = _build_external_ref(deal_payload, data)

    idempotency_key = build_idempotency_key(
        tenant_id=tenant_id,
        channel=channel,
        external_ref_type=external_ref_type,
        external_ref_id=external_ref_id,
        payload=deal_payload,
        policy_version=policy_version,
        client_key=request.headers.get("Idempotency-Key"),
    )
    fingerprint = compute_request_fingerprint(deal_payload)

    run_id = str(data.get("run_id") or f"ddrun-{uuid.uuid4().hex[:12]}")

    existing = (
        DealPacket.objects.filter(tenant_id=tenant_id, idempotency_key=idempotency_key)
        .order_by("-created_at")
        .first()
    )
    if existing:
        age = timezone.now() - existing.created_at
        if age > timedelta(hours=ttl_hours):
            return JsonResponse(
                {
                    "error": "Idempotency key expired. Submit with a new Idempotency-Key.",
                    "code": "idempotency_key_expired",
                    "deal_packet_id": existing.id,
                },
                status=409,
            )

        create_tenant_audit_event(
            tenant_id=tenant_id,
            run_id=run_id,
            source=channel,
            entity_type="deal_packet",
            entity_id=str(existing.id),
            event_type="idempotency_replay",
            details={"replayed": True},
            idempotency_key=idempotency_key,
            tenant_resolution_source=resolution.source or "",
            duplicate_request_detected=True,
        )
        latest_eval = existing.policy_evaluations.order_by("-created_at").first()
        return JsonResponse(_build_response(existing, policy_eval=latest_eval, replayed=True), status=200)

    try:
        with transaction.atomic():
            packet = DealPacket.objects.create(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                external_ref_type=external_ref_type,
                external_ref_id=external_ref_id,
                crm_source=(data.get("crm_source") or "").strip(),
                payload_json=deal_payload,
                status=DealPacket.STATUS_DRAFT,
                created_by=actor,
            )
    except IntegrityError:
        packet = DealPacket.objects.filter(tenant_id=tenant_id, idempotency_key=idempotency_key).first()
        if not packet:
            return _error("Could not create idempotent deal packet", status=500)

        create_tenant_audit_event(
            tenant_id=tenant_id,
            run_id=run_id,
            source=channel,
            entity_type="deal_packet",
            entity_id=str(packet.id),
            event_type="idempotency_replay",
            details={"replayed": True, "integrity_error": True},
            idempotency_key=idempotency_key,
            tenant_resolution_source=resolution.source or "",
            duplicate_request_detected=True,
        )
        latest_eval = packet.policy_evaluations.order_by("-created_at").first()
        return JsonResponse(_build_response(packet, policy_eval=latest_eval, replayed=True), status=200)

    create_tenant_audit_event(
        tenant_id=tenant_id,
        run_id=run_id,
        source=channel,
        entity_type="deal_packet",
        entity_id=str(packet.id),
        event_type="review_created",
        details={"external_ref_type": external_ref_type, "external_ref_id": external_ref_id},
        idempotency_key=idempotency_key,
        tenant_resolution_source=resolution.source or "",
    )

    schema_validation = validate_deal_packet_schema(deal_payload)
    results_json = evaluate_policy(deal_payload, policy_config)

    for required_field in schema_validation.get("required_fields", []):
        if required_field not in results_json["required_fields"]:
            results_json["required_fields"].append(required_field)

    for schema_error in schema_validation.get("errors", []):
        message = schema_error.get("message")
        if message:
            results_json["violations"].append(f"schema: {message}")

    results_json["required_fields"] = sorted(set(results_json.get("required_fields", [])))

    policy_eval = PolicyEvaluation.objects.create(
        tenant_id=tenant_id,
        deal_packet=packet,
        policy_version=policy_version,
        results_json=results_json,
    )

    route_info = {}
    packet.status = compute_status_from_policy(results_json)

    if packet.status == DealPacket.STATUS_IN_APPROVAL:
        quote, resolve_error = resolve_quote_for_packet(deal_packet=packet, payload=deal_payload, actor=actor)
        if resolve_error or quote is None:
            packet.status = DealPacket.STATUS_NEEDS_INFO
            results_json["violations"].append("quote_resolution_failed")
            policy_eval.results_json = results_json
            policy_eval.save(update_fields=["results_json"])
        else:
            route_info = route_approvals_for_packet(
                deal_packet=packet,
                quote=quote,
                results_json=results_json,
                policy_version=policy_version,
            )
            if not route_info.get("routed"):
                packet.status = DealPacket.STATUS_NEEDS_INFO
                route_error = route_info.get("error") or route_info.get("reason") or "approval_routing_failed"
                results_json["violations"].append(route_error)
                policy_eval.results_json = results_json
                policy_eval.save(update_fields=["results_json"])

    if packet.status == DealPacket.STATUS_NEEDS_INFO:
        packet.decision_summary = "Deal packet requires additional information before routing."
    elif packet.status == DealPacket.STATUS_IN_APPROVAL:
        packet.decision_summary = "Deal packet submitted for approval routing."
    else:
        packet.decision_summary = "Deal packet approved automatically (no approval routing required)."

    packet.save(update_fields=["status", "decision_summary", "updated_at"])

    create_tenant_audit_event(
        tenant_id=tenant_id,
        run_id=run_id,
        source=channel,
        entity_type="policy_eval",
        entity_id=str(policy_eval.id),
        event_type="policy_evaluated",
        details={"status": packet.status},
        idempotency_key=idempotency_key,
        tenant_resolution_source=resolution.source or "",
    )

    if route_info.get("routed"):
        create_tenant_audit_event(
            tenant_id=tenant_id,
            run_id=run_id,
            source=channel,
            entity_type="approval",
            entity_id=str(route_info.get("approval_instance_id") or ""),
            event_type="approval_routed",
            details={"routing_mode": route_info.get("routing_mode")},
            idempotency_key=idempotency_key,
            tenant_resolution_source=resolution.source or "",
        )

    return JsonResponse(_build_response(packet, policy_eval=policy_eval, replayed=False), status=200)


@csrf_exempt
def get_deal_packet(request, packet_id: int):
    if request.method != "GET":
        return _error("Only GET allowed", status=405)

    channel = (request.headers.get("X-Channel") or "api").strip().lower()
    resolution, response = _resolve_tenant_or_error(request, {}, channel=channel)
    if response is not None:
        return response

    packet = DealPacket.objects.filter(id=packet_id, tenant_id=resolution.tenant_id).first()
    if not packet:
        return _error("Deal packet not found", status=404)

    latest_eval = packet.policy_evaluations.order_by("-created_at").first()
    return JsonResponse(_build_response(packet, policy_eval=latest_eval), status=200)


@csrf_exempt
def get_deal_packet_status(request, packet_id: int):
    if request.method != "GET":
        return _error("Only GET allowed", status=405)

    channel = (request.headers.get("X-Channel") or "api").strip().lower()
    resolution, response = _resolve_tenant_or_error(request, {}, channel=channel)
    if response is not None:
        return response

    packet = DealPacket.objects.filter(id=packet_id, tenant_id=resolution.tenant_id).first()
    if not packet:
        return _error("Deal packet not found", status=404)

    instance = packet.approval_instances.select_related("quoteapproval", "quoteapproval__step").order_by("-created_at").first()
    current_step = None
    if instance and instance.quoteapproval and instance.quoteapproval.step:
        current_step = instance.quoteapproval.step.approver_role

    payload = {
        "id": packet.id,
        "status": packet.status,
        "decision_summary": packet.decision_summary,
        "current_step": current_step,
        "updated_at": packet.updated_at.isoformat() if packet.updated_at else None,
    }
    return JsonResponse(payload, status=200)


@csrf_exempt
def get_deal_packet_audit(request, packet_id: int):
    if request.method != "GET":
        return _error("Only GET allowed", status=405)

    channel = (request.headers.get("X-Channel") or "api").strip().lower()
    resolution, response = _resolve_tenant_or_error(request, {}, channel=channel)
    if response is not None:
        return response

    packet = DealPacket.objects.filter(id=packet_id, tenant_id=resolution.tenant_id).first()
    if not packet:
        return _error("Deal packet not found", status=404)

    events = AuditEvent.objects.filter(
        tenant_id=resolution.tenant_id,
        entity_type="deal_packet",
        entity_id=str(packet.id),
    ).order_by("created_at")

    payload = {
        "deal_packet_id": packet.id,
        "events": [serialize_audit_event(event) for event in events],
    }
    return JsonResponse(payload, status=200)


@csrf_exempt
def evaluate_packet(request, packet_id: int):
    if request.method != "POST":
        return _error("Only POST allowed", status=405)

    data = _json_body(request)
    if data is None:
        return _error("Invalid JSON", status=400)

    channel = (data.get("channel") or request.headers.get("X-Channel") or "api").strip().lower()
    resolution, response = _resolve_tenant_or_error(request, data, channel=channel)
    if response is not None:
        return response

    packet = DealPacket.objects.filter(id=packet_id, tenant_id=resolution.tenant_id).first()
    if not packet:
        return _error("Deal packet not found", status=404)

    policy_version, policy_config, _ = get_active_policy_config(resolution.tenant_id)
    results_json = evaluate_policy(packet.payload_json, policy_config)
    schema_validation = validate_deal_packet_schema(packet.payload_json)

    for required_field in schema_validation.get("required_fields", []):
        if required_field not in results_json["required_fields"]:
            results_json["required_fields"].append(required_field)

    policy_eval = PolicyEvaluation.objects.create(
        tenant_id=resolution.tenant_id,
        deal_packet=packet,
        policy_version=policy_version,
        results_json=results_json,
    )

    packet.status = compute_status_from_policy(results_json)
    packet.save(update_fields=["status", "updated_at"])

    return JsonResponse(_build_response(packet, policy_eval=policy_eval), status=200)


@csrf_exempt
def route_packet(request, packet_id: int):
    if request.method != "POST":
        return _error("Only POST allowed", status=405)

    data = _json_body(request)
    if data is None:
        return _error("Invalid JSON", status=400)

    channel = (data.get("channel") or request.headers.get("X-Channel") or "api").strip().lower()
    resolution, response = _resolve_tenant_or_error(request, data, channel=channel)
    if response is not None:
        return response

    packet = DealPacket.objects.filter(id=packet_id, tenant_id=resolution.tenant_id).first()
    if not packet:
        return _error("Deal packet not found", status=404)

    latest_eval = packet.policy_evaluations.order_by("-created_at").first()
    if not latest_eval:
        return _error("No policy evaluation found", status=400)

    if latest_eval.results_json.get("required_fields") or latest_eval.results_json.get("violations"):
        return _error("Deal packet has unresolved required fields or violations", status=400)

    quote, resolve_error = resolve_quote_for_packet(deal_packet=packet, payload=packet.payload_json, actor=_resolve_actor(data, request))
    if resolve_error or quote is None:
        return _error("Unable to resolve quote for approval routing", status=400)

    route_info = route_approvals_for_packet(
        deal_packet=packet,
        quote=quote,
        results_json=latest_eval.results_json,
        policy_version=latest_eval.policy_version,
    )

    if not route_info.get("routed"):
        return _error(route_info.get("error") or "Approval routing failed", status=400)

    packet.status = DealPacket.STATUS_IN_APPROVAL
    packet.decision_summary = "Deal packet submitted for approval routing."
    packet.save(update_fields=["status", "decision_summary", "updated_at"])

    return JsonResponse({"deal_packet_id": packet.id, "route_info": route_info}, status=200)


@csrf_exempt
def record_packet_event(request, packet_id: int):
    if request.method != "POST":
        return _error("Only POST allowed", status=405)

    data = _json_body(request)
    if data is None:
        return _error("Invalid JSON", status=400)

    channel = (data.get("channel") or request.headers.get("X-Channel") or "api").strip().lower()
    resolution, response = _resolve_tenant_or_error(request, data, channel=channel)
    if response is not None:
        return response

    packet = DealPacket.objects.filter(id=packet_id, tenant_id=resolution.tenant_id).first()
    if not packet:
        return _error("Deal packet not found", status=404)

    event_type = (data.get("event_type") or "updated").strip().lower()
    details = data.get("details") if isinstance(data.get("details"), dict) else {}
    run_id = str(data.get("run_id") or f"ddrun-{uuid.uuid4().hex[:12]}")

    if event_type in {"approved", "approve"}:
        packet.status = DealPacket.STATUS_APPROVED
        packet.decision_summary = "Deal approved."
    elif event_type in {"rejected", "reject"}:
        packet.status = DealPacket.STATUS_REJECTED
        packet.decision_summary = "Deal rejected."
    elif event_type in {"request_info", "needs_info", "request-info"}:
        packet.status = DealPacket.STATUS_NEEDS_INFO
        packet.decision_summary = "Additional information requested."

    packet.save(update_fields=["status", "decision_summary", "updated_at"])

    create_tenant_audit_event(
        tenant_id=resolution.tenant_id,
        run_id=run_id,
        source=channel,
        entity_type="deal_packet",
        entity_id=str(packet.id),
        event_type=event_type,
        details=details,
        idempotency_key=(request.headers.get("Idempotency-Key") or ""),
        tenant_resolution_source=resolution.source or "",
    )

    return JsonResponse({"deal_packet_id": packet.id, "status": packet.status}, status=200)
