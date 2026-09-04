import logging
import re
import uuid
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from html import escape

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from agentcpq.dealdesk.models import DealPacket, PolicyEvaluation
from agentcpq.dealdesk.services import (
    build_idempotency_key,
    compute_request_fingerprint,
    compute_status_from_policy,
    create_system_audit_event,
    create_tenant_audit_event,
    emit_result_payload,
    evaluate_policy,
    get_active_policy_config,
    route_approvals_for_packet,
    serialize_deal_packet,
    validate_deal_packet_schema,
)
from cpq.models import Quote, Tenant
from .utils.message_formatters import ERROR_ICON, INFO_ICON, SUCCESS_ICON, WARNING_ICON


logger = logging.getLogger(__name__)


def _chat_response(message: str, **extra):
    payload = {"message": message, "suppress_chat": True}
    payload.update(extra)
    return payload


def _line(icon: str, text: str):
    return f"{icon} {text}"


def _safe_text(value) -> str:
    return escape(str(value or ""))


def _status_chip(status_value: str):
    normalized = str(status_value or "").strip().lower()
    label_map = {
        "approved": "Approved",
        "in_approval": "In Approval",
        "needs_info": "Needs Info",
        "rejected": "Rejected",
        "draft": "Draft",
    }
    tone_map = {
        "approved": "success",
        "in_approval": "review",
        "needs_info": "risk",
        "rejected": "risk",
        "draft": "neutral",
    }
    label = label_map.get(normalized, normalized.replace("_", " ").title() if normalized else "Unknown")
    tone = tone_map.get(normalized, "neutral")
    return normalized, label, tone


def _build_notice_banner(html_text: str, tone: str = "info"):
    icon_map = {
        "info": "info",
        "success": "task_alt",
        "warning": "warning",
        "danger": "error",
    }
    icon = icon_map.get(tone, "info")
    return (
        f'<div class="dealdesk-ai-note dealdesk-ai-note--{tone}">'
        f'<span class="material-icons" aria-hidden="true">{icon}</span>'
        f'<div class="dealdesk-ai-note__text">{html_text}</div>'
        "</div>"
    )


def _is_force_submit(user_message: str) -> bool:
    lowered = (user_message or "").strip().lower()
    phrases = (
        "submit anyway",
        "force submit",
        "submit now",
        "confirm submit",
        "proceed to submit",
        "proceed with submit",
    )
    return any(phrase in lowered for phrase in phrases)


def _merge_preflight_results(payload: dict, policy_config: dict):
    schema_validation = validate_deal_packet_schema(payload)
    results_json = evaluate_policy(payload, policy_config)

    for required_field in schema_validation.get("required_fields", []):
        if required_field not in results_json["required_fields"]:
            results_json["required_fields"].append(required_field)

    for schema_error in schema_validation.get("errors", []):
        message = schema_error.get("message")
        if message:
            results_json["violations"].append(f"schema: {message}")

    results_json["required_fields"] = sorted(set(results_json.get("required_fields", [])))
    return results_json


def _required_roles(results_json: dict) -> list[str]:
    roles = []
    seen = set()
    for item in results_json.get("required_approvals", []):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if not role:
            continue
        key = role.lower()
        if key in seen:
            continue
        seen.add(key)
        roles.append(role)
    return roles


def _pre_submit_suggestions(payload: dict, policy_config: dict, results_json: dict):
    suggestions = []
    required_fields = results_json.get("required_fields", [])
    violations = results_json.get("violations", [])
    required_roles = _required_roles(results_json)

    discount = Decimal(str((payload.get("policy_inputs") or {}).get("discount_percent") or 0))
    thresholds = policy_config.get("discount_thresholds") or {}
    level_1 = Decimal(str(thresholds.get("level_1", 10)))
    level_2 = Decimal(str(thresholds.get("level_2", 20)))

    if discount > level_2:
        suggestions.append(
            f"Lower discount to <= {level_2}% to reduce level-2 approvals (for example VP Sales/Finance)."
        )
    elif discount > level_1:
        suggestions.append(
            f"Lower discount to <= {level_1}% to avoid level-1 approval escalation."
        )

    payment_terms = str(
        (payload.get("commercial_terms") or {}).get("payment_terms")
        or (payload.get("policy_inputs") or {}).get("requested_payment_terms")
        or ""
    ).strip().lower()
    risky_terms = {str(term).strip().lower() for term in policy_config.get("high_risk_payment_terms", [])}
    if payment_terms and payment_terms in risky_terms:
        suggestions.append(
            f"Use a standard payment term (for example net30) instead of {payment_terms} to reduce Finance/Legal review."
        )

    has_custom_terms = bool((payload.get("policy_inputs") or {}).get("has_custom_terms"))
    if has_custom_terms:
        suggestions.append("Use standard terms to avoid Legal approval routing.")

    if required_fields:
        suggestions.append(f"Fill required data before submit: {', '.join(required_fields[:4])}.")
    if violations:
        suggestions.append(f"Resolve policy violations first: {', '.join(violations[:3])}.")

    if not suggestions and required_roles:
        suggestions.append("Current policy path is valid. Approval time mainly depends on approver response times.")
    if not suggestions:
        suggestions.append("Current deal shape looks optimized for a fast approval path.")

    if violations or required_fields:
        effort = "High"
        eta = "Cannot estimate until required fields and violations are resolved."
    elif len(required_roles) >= 3:
        effort = "High"
        eta = "Likely slower than normal due to multiple approvers."
    elif len(required_roles) == 2:
        effort = "Medium"
        eta = "Likely medium cycle time."
    elif len(required_roles) == 1:
        effort = "Low"
        eta = "Likely faster cycle with one approver."
    else:
        effort = "Low"
        eta = "Likely immediate or near-immediate decision."

    return {
        "status": compute_status_from_policy(results_json),
        "required_roles": required_roles,
        "required_fields": required_fields,
        "violations": violations,
        "suggestions": suggestions,
        "effort": effort,
        "eta_hint": eta,
    }


def _build_pre_submit_message(quote: Quote, policy_version: str, preview: dict):
    _, status_label, status_tone = _status_chip(preview.get("status"))
    safe_quote = _safe_text(quote.name)
    safe_policy = _safe_text(policy_version)
    safe_effort = _safe_text(preview.get("effort") or "Unknown")
    safe_eta = _safe_text(preview.get("eta_hint") or "No timing estimate available.")

    approver_pills = "".join(
        f'<span class="dealdesk-ai-pill">{_safe_text(role)}</span>'
        for role in (preview.get("required_roles") or [])[:6]
    )
    if not approver_pills:
        approver_pills = '<span class="dealdesk-ai-pill dealdesk-ai-pill--ghost">No manual approvers predicted</span>'

    recommendation_items = "".join(
        (
            '<li class="dealdesk-ai-list-item">'
            '<span class="material-icons" aria-hidden="true">subdirectory_arrow_right</span>'
            f"<span>{_safe_text(suggestion)}</span>"
            "</li>"
        )
        for suggestion in (preview.get("suggestions") or [])[:5]
    )

    risk_lines = []
    if preview.get("required_fields"):
        risk_lines.append(
            "<li><b>Missing required fields:</b> "
            + _safe_text(", ".join(preview["required_fields"][:5]))
            + "</li>"
        )
    if preview.get("violations"):
        risk_lines.append(
            "<li><b>Policy violations:</b> "
            + _safe_text(", ".join(preview["violations"][:4]))
            + "</li>"
        )
    risk_block = ""
    if risk_lines:
        risk_block = (
            '<div class="dealdesk-ai-risk">'
            '<div class="dealdesk-ai-risk__title"><span class="material-icons" aria-hidden="true">warning</span>'
            "<span>Approval blockers detected</span></div>"
            f"<ul>{''.join(risk_lines)}</ul>"
            "</div>"
        )

    return (
        '<section class="dealdesk-ai-card" data-card="dealdesk-pre-submit">'
        '<div class="dealdesk-ai-glow" aria-hidden="true"></div>'
        '<header class="dealdesk-ai-card__header">'
        '<div class="dealdesk-ai-card__eyebrow">'
        '<span class="material-icons" aria-hidden="true">auto_awesome</span>'
        "<span>Deal Desk Intelligence</span>"
        "</div>"
        f'<h3 class="dealdesk-ai-card__title">Pre-submit approval intelligence for <b>{safe_quote}</b></h3>'
        "</header>"
        '<div class="dealdesk-ai-metrics">'
        f'<span class="dealdesk-ai-chip dealdesk-ai-chip--policy"><b>Policy:</b> {safe_policy}</span>'
        f'<span class="dealdesk-ai-chip dealdesk-ai-chip--{status_tone}"><b>Predicted status:</b> {status_label}</span>'
        f'<span class="dealdesk-ai-chip dealdesk-ai-chip--effort"><b>Review effort:</b> {safe_effort}</span>'
        "</div>"
        f'<p class="dealdesk-ai-timing"><span class="material-icons" aria-hidden="true">schedule</span><span><b>Timing hint:</b> {safe_eta}</span></p>'
        '<div class="dealdesk-ai-approvers"><span class="dealdesk-ai-section-title">Likely approvers</span>'
        f'<div class="dealdesk-ai-pill-row">{approver_pills}</div></div>'
        f"{risk_block}"
        '<div class="dealdesk-ai-recommendations">'
        '<span class="dealdesk-ai-section-title">Recommendations</span>'
        f"<ul>{recommendation_items}</ul>"
        "</div>"
        '<div class="dealdesk-ai-actions">'
        '<button type="button" class="dealdesk-ai-action dealdesk-ai-action--primary" data-chat-reply="Submit anyway" data-chat-send="true">'
        '<span class="material-icons" aria-hidden="true">rocket_launch</span><span>Submit anyway</span></button>'
        '<button type="button" class="dealdesk-ai-action dealdesk-ai-action--secondary" data-chat-reply="Cancel submission" data-chat-send="true">'
        '<span class="material-icons" aria-hidden="true">close</span><span>Cancel submission</span></button>'
        "</div>"
        '<p class="dealdesk-ai-footnote">You can also type <b>Submit anyway</b> or <b>Cancel submission</b>.</p>'
        "</section>"
    )


def dealdesk_agent(user, action, user_message, session_data):
    handlers = {
        "SubmitForApproval": _submit_for_approval,
        "CheckApprovalStatus": _check_approval_status,
        "ApproveQuote": _approve_quote,
        "RejectQuote": _reject_quote,
        "RecallQuote": _recall_quote,
    }
    handler = handlers.get(action)
    if not handler:
        return _chat_response(_line(WARNING_ICON, "Unsupported Deal Desk action."))
    return handler(user, user_message or "", session_data or {})


def _current_tenant_or_error():
    tenant = Tenant.objects.first()
    if tenant and tenant.tenant_id:
        return tenant, None

    create_system_audit_event(
        source="orchestrator",
        event_type="tenant_missing_orchestrator",
        request_meta={"reason": "Tenant.objects.first() missing for chat orchestrator"},
        idempotency_key="",
    )
    return None, {
        "message": _line(WARNING_ICON, "No tenant is configured. Please create a Tenant first before using approvals in chat.")
    }


def _resolve_quote(user_message: str, session_data: dict):
    identifier = _extract_quote_identifier(user_message)
    quote = _find_quote_by_identifier(identifier) if identifier else None
    if quote:
        _set_active_quote(session_data, quote)
        return quote

    active_quote = session_data.get("active_quote") if isinstance(session_data, dict) else None
    quote_id = active_quote.get("quote_id") if isinstance(active_quote, dict) else None
    if quote_id:
        quote = Quote.objects.filter(id=quote_id).first()
        if quote:
            _set_active_quote(session_data, quote)
            return quote

    pending_submission = session_data.get("dealdesk_pending_submission") if isinstance(session_data, dict) else None
    pending_quote_id = pending_submission.get("quote_id") if isinstance(pending_submission, dict) else None
    if pending_quote_id:
        quote = Quote.objects.filter(id=pending_quote_id).first()
        if quote:
            _set_active_quote(session_data, quote)
            return quote

    return None


def _extract_quote_identifier(user_message: str):
    if not user_message:
        return None

    quoted_name = re.search(r"\bQ-\d{3,}\b", user_message, re.IGNORECASE)
    if quoted_name:
        return quoted_name.group(0)

    numeric_id = re.search(r"\bquote(?:\s+id)?\s*[:#]?\s*(\d+)\b", user_message, re.IGNORECASE)
    if numeric_id:
        return numeric_id.group(1)

    return None


def _find_quote_by_identifier(identifier):
    if not identifier:
        return None

    if str(identifier).isdigit():
        as_int = int(identifier)
        return Quote.objects.filter(
            Q(id=as_int)
            | Q(name=str(identifier))
            | Q(qteid=str(identifier))
            | Q(external_id=str(identifier))
        ).first()

    return Quote.objects.filter(
        Q(name__iexact=str(identifier))
        | Q(qteid__iexact=str(identifier))
        | Q(external_id__iexact=str(identifier))
    ).first()


def _set_active_quote(session_data: dict, quote: Quote):
    session_data["active_quote"] = {
        "quote_id": quote.id,
        "quote_name": quote.name,
        "account": quote.account.name if quote.account else "N/A",
        "opportunity": quote.opportunity.name if quote.opportunity else "N/A",
    }


def _extract_payment_terms(user_message: str):
    if not user_message:
        return "net30"

    net_terms = re.search(r"\bnet\s*(\d{1,3})\b", user_message, re.IGNORECASE)
    if net_terms:
        return f"net{net_terms.group(1)}"

    if re.search(r"\bdue\s+on\s+receipt\b", user_message, re.IGNORECASE):
        return "due_on_receipt"

    return "net30"


def _extract_justification(user_message: str):
    if not user_message:
        return "Submitted for approval via chat orchestrator."

    because = re.search(r"\bbecause\b(.+)$", user_message, re.IGNORECASE)
    if because:
        value = because.group(1).strip(" .")
        if value:
            return value
    return "Submitted for approval via chat orchestrator."


def _build_deal_packet_payload(quote: Quote, user_message: str):
    term_months = (
        quote.quote_lines.exclude(term__isnull=True)
        .exclude(term=0)
        .order_by("-term")
        .values_list("term", flat=True)
        .first()
        or 12
    )

    payment_terms = _extract_payment_terms(user_message)
    list_total = Decimal(str(quote.subtotal or 0))
    net_total = Decimal(str(quote.net_amount or 0))

    discount_percent = Decimal(str(quote.discount_percentage or 0))
    if discount_percent <= 0 and list_total > 0:
        discount_percent = ((list_total - net_total) / list_total) * Decimal("100.00")
    discount_percent = max(Decimal("0.00"), min(discount_percent, Decimal("100.00")))

    has_custom_terms = bool(re.search(r"\bcustom\s+terms?\b|\blegal\s+terms?\b", user_message or "", re.IGNORECASE))
    concessions = []
    if has_custom_terms:
        concessions.append(
            {
                "type": "custom_terms",
                "value": "legal",
                "description": "Custom terms requested in chat.",
            }
        )

    opportunity_amount = quote.opportunity.amount if quote.opportunity and quote.opportunity.amount else net_total
    close_date = (
        quote.opportunity.expected_close_date.isoformat()
        if quote.opportunity and quote.opportunity.expected_close_date
        else timezone.now().date().isoformat()
    )

    account_region = (quote.account.state or "").strip() if quote.account else ""
    account_region = account_region or "NA"
    size_band = "Unknown"

    payload = {
        "schema_version": "1.0",
        "account": {
            "id": quote.account_id,
            "industry": (quote.account.industry or "Unknown") if quote.account else "Unknown",
            "size_band": size_band,
            "region": account_region,
        },
        "opportunity": {
            "id": quote.opportunity_id,
            "name": quote.opportunity.name if quote.opportunity else f"Quote-{quote.id}",
            "amount": float(Decimal(str(opportunity_amount or 0))),
            "close_date": close_date,
            "stage": quote.opportunity.stage if quote.opportunity else "Prospecting",
        },
        "commercial_terms": {
            "term_months": int(term_months),
            "billing_frequency": "monthly",
            "payment_terms": payment_terms,
            "ramp_segments": [],
        },
        "pricing_summary": {
            "list_total": float(list_total),
            "discount_percent": float(discount_percent),
            "net_total": float(net_total),
            "margin_band": None,
        },
        "concessions": concessions,
        "attachments": [],
        "request_context": {
            "request_reason": "Quote approval submission",
            "justification": _extract_justification(user_message),
            "competitor": None,
            "deal_notes": f"Submitted from chat for quote {quote.name}.",
        },
        "policy_inputs": {
            "discount_percent": float(discount_percent),
            "requested_payment_terms": payment_terms,
            "margin_percent": None,
            "has_custom_terms": has_custom_terms,
            "requires_legal": has_custom_terms,
            "required_attachments": [],
            "segment": None,
            "region_override": None,
        },
    }
    return payload


def _latest_packet_for_quote(tenant_id: str, quote: Quote):
    return (
        DealPacket.objects.filter(
            tenant_id=tenant_id,
            external_ref_type=DealPacket.EXTERNAL_REF_QUOTE,
            external_ref_id=str(quote.id),
        )
        .order_by("-created_at")
        .first()
    )


def _current_step_name(packet: DealPacket):
    instance = (
        packet.approval_instances.select_related("quoteapproval", "quoteapproval__step")
        .order_by("-created_at")
        .first()
    )
    if instance and instance.quoteapproval and instance.quoteapproval.step:
        return instance.quoteapproval.step.approver_role
    return None


def _track_session(session_data: dict, quote: Quote, packet: DealPacket, policy_eval: PolicyEvaluation | None):
    _set_active_quote(session_data, quote)
    session_data["active_dealdesk"] = {
        "deal_packet_id": packet.id,
        "quote_id": quote.id,
        "status": packet.status,
    }
    if policy_eval is not None:
        session_data["active_dealdesk"]["required_approvals"] = policy_eval.results_json.get("required_approvals", [])


def _submit_for_approval(user, user_message: str, session_data: dict):
    tenant, tenant_error = _current_tenant_or_error()
    if tenant_error:
        return tenant_error

    quote = _resolve_quote(user_message, session_data)
    if not quote:
        return _chat_response(
            _line(WARNING_ICON, "No active quote found. Mention a quote (for example Q-00010) or open a quote first.")
        )

    payload = _build_deal_packet_payload(quote, user_message)
    policy_version, policy_config, ttl_hours = get_active_policy_config(tenant.tenant_id)
    preview_results = _merge_preflight_results(payload, policy_config)
    preview = _pre_submit_suggestions(payload, policy_config, preview_results)

    if not _is_force_submit(user_message):
        session_data["dealdesk_pending_submission"] = {
            "quote_id": quote.id,
            "tenant_id": tenant.tenant_id,
            "policy_version": policy_version,
            "preview_status": preview["status"],
        }
        return _chat_response(
            _build_pre_submit_message(quote, policy_version, preview),
            approval_preview=preview,
            quote_id=quote.id,
        )

    session_data.pop("dealdesk_pending_submission", None)

    run_id = f"ddrun-{uuid.uuid4().hex[:12]}"

    idempotency_key = build_idempotency_key(
        tenant_id=tenant.tenant_id,
        channel="orchestrator",
        external_ref_type=DealPacket.EXTERNAL_REF_QUOTE,
        external_ref_id=str(quote.id),
        payload=payload,
        policy_version=policy_version,
    )
    fingerprint = compute_request_fingerprint(payload)

    existing = (
        DealPacket.objects.filter(tenant_id=tenant.tenant_id, idempotency_key=idempotency_key)
        .order_by("-created_at")
        .first()
    )
    if existing:
        age = timezone.now() - existing.created_at
        if age <= timedelta(hours=ttl_hours):
            create_tenant_audit_event(
                tenant_id=tenant.tenant_id,
                run_id=run_id,
                source="orchestrator",
                entity_type="deal_packet",
                entity_id=str(existing.id),
                event_type="idempotency_replay",
                details={"replayed": True},
                idempotency_key=idempotency_key,
                tenant_resolution_source="tenant_first",
                duplicate_request_detected=True,
            )
            latest_eval = existing.policy_evaluations.order_by("-created_at").first()
            _track_session(session_data, quote, existing, latest_eval)
            return _chat_response(
                "<br>".join(
                    [
                        _line(INFO_ICON, f"Deal Desk reused the latest review for quote <b>{quote.name}</b>."),
                        _line(INFO_ICON, f"Current status: <b>{existing.status}</b>."),
                    ]
                ),
                deal_packet=serialize_deal_packet(existing),
                replayed=True,
                policy_evaluation=latest_eval.results_json if latest_eval else {},
                crm_sync_payload=emit_result_payload(deal_packet=existing, policy_eval=latest_eval),
            )

        idempotency_key = build_idempotency_key(
            tenant_id=tenant.tenant_id,
            channel="orchestrator",
            external_ref_type=DealPacket.EXTERNAL_REF_QUOTE,
            external_ref_id=str(quote.id),
            payload=payload,
            policy_version=policy_version,
            client_key=f"chat-{uuid.uuid4().hex[:12]}",
        )

    try:
        with transaction.atomic():
            packet = DealPacket.objects.create(
                tenant_id=tenant.tenant_id,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
                external_ref_type=DealPacket.EXTERNAL_REF_QUOTE,
                external_ref_id=str(quote.id),
                crm_source="chat_orchestrator",
                payload_json=payload,
                status=DealPacket.STATUS_DRAFT,
                created_by=user if getattr(user, "is_authenticated", False) else None,
            )
    except IntegrityError:
        packet = DealPacket.objects.filter(tenant_id=tenant.tenant_id, idempotency_key=idempotency_key).first()
        if not packet:
            return _chat_response(_line(ERROR_ICON, "Unable to create a Deal Desk packet for this quote."))
        latest_eval = packet.policy_evaluations.order_by("-created_at").first()
        _track_session(session_data, quote, packet, latest_eval)
        return _chat_response(
            "<br>".join(
                [
                    _line(INFO_ICON, f"Deal Desk reused the latest review for quote <b>{quote.name}</b>."),
                    _line(INFO_ICON, f"Current status: <b>{packet.status}</b>."),
                ]
            ),
            deal_packet=serialize_deal_packet(packet),
            replayed=True,
            policy_evaluation=latest_eval.results_json if latest_eval else {},
            crm_sync_payload=emit_result_payload(deal_packet=packet, policy_eval=latest_eval),
        )

    create_tenant_audit_event(
        tenant_id=tenant.tenant_id,
        run_id=run_id,
        source="orchestrator",
        entity_type="deal_packet",
        entity_id=str(packet.id),
        event_type="review_created",
        details={"external_ref_type": DealPacket.EXTERNAL_REF_QUOTE, "external_ref_id": str(quote.id)},
        idempotency_key=idempotency_key,
        tenant_resolution_source="tenant_first",
    )

    results_json = deepcopy(preview_results)

    policy_eval = PolicyEvaluation.objects.create(
        tenant_id=tenant.tenant_id,
        deal_packet=packet,
        policy_version=policy_version,
        results_json=results_json,
    )

    route_info = {}
    packet.status = compute_status_from_policy(results_json)
    if packet.status == DealPacket.STATUS_IN_APPROVAL:
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
        tenant_id=tenant.tenant_id,
        run_id=run_id,
        source="orchestrator",
        entity_type="policy_eval",
        entity_id=str(policy_eval.id),
        event_type="policy_evaluated",
        details={"status": packet.status},
        idempotency_key=idempotency_key,
        tenant_resolution_source="tenant_first",
    )
    if route_info.get("routed"):
        create_tenant_audit_event(
            tenant_id=tenant.tenant_id,
            run_id=run_id,
            source="orchestrator",
            entity_type="approval",
            entity_id=str(route_info.get("approval_instance_id") or ""),
            event_type="approval_routed",
            details={"routing_mode": route_info.get("routing_mode")},
            idempotency_key=idempotency_key,
            tenant_resolution_source="tenant_first",
        )

    _track_session(session_data, quote, packet, policy_eval)

    if packet.status == DealPacket.STATUS_NEEDS_INFO:
        required_fields = policy_eval.results_json.get("required_fields", [])
        violations = policy_eval.results_json.get("violations", [])
        issues = required_fields + violations
        issue_text = ", ".join(issues[:4]) if issues else "missing required data"
        message = (
            '<div class="dealdesk-ai-stack">'
            + _build_notice_banner(
                f"Deal Desk needs more information for quote <b>{_safe_text(quote.name)}</b>.",
                tone="warning",
            )
            + _build_notice_banner(
                f"<b>Details:</b> {_safe_text(issue_text)}.",
                tone="info",
            )
            + "</div>"
        )
    elif packet.status == DealPacket.STATUS_APPROVED:
        message = _build_notice_banner(
            f"Deal Desk auto-approved quote <b>{_safe_text(quote.name)}</b>.",
            tone="success",
        )
    else:
        current_step = _current_step_name(packet) or "Pending"
        message = (
            '<div class="dealdesk-ai-stack">'
            + _build_notice_banner(
                f"Deal Desk submitted quote <b>{_safe_text(quote.name)}</b> for approval.",
                tone="success",
            )
            + _build_notice_banner(
                f"Current step: <b>{_safe_text(current_step)}</b>.",
                tone="info",
            )
            + "</div>"
        )

    return _chat_response(
        message,
        deal_packet=serialize_deal_packet(packet),
        policy_evaluation=policy_eval.results_json,
        route_info=route_info,
        replayed=False,
        crm_sync_payload=emit_result_payload(deal_packet=packet, policy_eval=policy_eval),
    )


def _check_approval_status(user, user_message: str, session_data: dict):
    tenant, tenant_error = _current_tenant_or_error()
    if tenant_error:
        return tenant_error

    quote = _resolve_quote(user_message, session_data)
    if not quote:
        return _chat_response(_line(WARNING_ICON, "No active quote found to check approval status."))

    packet = _latest_packet_for_quote(tenant.tenant_id, quote)
    if not packet:
        payload = _build_deal_packet_payload(quote, user_message)
        policy_version, policy_config, _ = get_active_policy_config(tenant.tenant_id)
        preview_results = _merge_preflight_results(payload, policy_config)
        preview = _pre_submit_suggestions(payload, policy_config, preview_results)
        session_data["dealdesk_pending_submission"] = {
            "quote_id": quote.id,
            "tenant_id": tenant.tenant_id,
            "policy_version": policy_version,
            "preview_status": preview["status"],
        }
        return _chat_response(
            '<div class="dealdesk-ai-stack">'
            + _build_notice_banner(
                f"Quote <b>{_safe_text(quote.name)}</b> has not been submitted to Deal Desk yet.",
                tone="info",
            )
            + _build_pre_submit_message(quote, policy_version, preview)
            + "</div>",
            approval_preview=preview,
            quote_id=quote.id,
        )

    latest_eval = packet.policy_evaluations.order_by("-created_at").first()
    current_step = _current_step_name(packet)
    _track_session(session_data, quote, packet, latest_eval)

    _, status_label, status_tone = _status_chip(packet.status)
    message = (
        '<div class="dealdesk-ai-stack">'
        + _build_notice_banner(
            f'Deal Desk status for quote <b>{_safe_text(quote.name)}</b>: <span class="dealdesk-ai-inline-status dealdesk-ai-inline-status--{status_tone}">{_safe_text(status_label)}</span>.',
            tone="info",
        )
        + (
            _build_notice_banner(f"Current step: <b>{_safe_text(current_step)}</b>.", tone="info")
            if current_step
            else ""
        )
        + "</div>"
    )

    return _chat_response(
        message,
        deal_packet_id=packet.id,
        deal_packet_status=packet.status,
        decision_summary=packet.decision_summary,
        current_step=current_step,
        required_approvals=(latest_eval.results_json.get("required_approvals", []) if latest_eval else []),
        deal_packet=serialize_deal_packet(packet),
    )


def _approve_quote(user, user_message: str, session_data: dict):
    tenant, tenant_error = _current_tenant_or_error()
    if tenant_error:
        return tenant_error

    quote = _resolve_quote(user_message, session_data)
    if not quote:
        return _chat_response(_line(WARNING_ICON, "No active quote found to approve."))

    packet = _latest_packet_for_quote(tenant.tenant_id, quote)
    if not packet:
        return _chat_response(_line(WARNING_ICON, f"Quote <b>{quote.name}</b> has no Deal Desk approval packet."))

    instance = (
        packet.approval_instances.select_related("quoteapproval", "quoteapproval__step")
        .order_by("-created_at")
        .first()
    )
    if not instance or not instance.quoteapproval:
        return _chat_response(_line(WARNING_ICON, f"No pending approval instance found for quote <b>{quote.name}</b>."))

    approval = instance.quoteapproval
    if approval.status == "Approved":
        return _chat_response(_line(INFO_ICON, f"Quote <b>{quote.name}</b> is already approved."))
    if approval.status == "Rejected":
        return _chat_response(_line(WARNING_ICON, f"Quote <b>{quote.name}</b> is already rejected and cannot be approved."))
    if approval.status != "Pending":
        return _chat_response(
            _line(WARNING_ICON, f"Unsupported approval status <b>{approval.status}</b> for quote <b>{quote.name}</b>.")
        )

    approval.status = "Approved"
    approval.approved_by = getattr(user, "username", "System")
    approval.approved_at = timezone.now()
    approval.save(update_fields=["status", "approved_by", "approved_at"])

    quote.status = "Approved"
    quote.save(update_fields=["status"])

    packet.status = DealPacket.STATUS_APPROVED
    packet.decision_summary = "Deal approved."
    packet.save(update_fields=["status", "decision_summary", "updated_at"])

    create_tenant_audit_event(
        tenant_id=tenant.tenant_id,
        run_id=f"ddrun-{uuid.uuid4().hex[:12]}",
        source="orchestrator",
        entity_type="deal_packet",
        entity_id=str(packet.id),
        event_type="approved",
        details={"approved_by": approval.approved_by},
        idempotency_key=packet.idempotency_key,
        tenant_resolution_source="tenant_first",
    )

    _track_session(session_data, quote, packet, packet.policy_evaluations.order_by("-created_at").first())
    return _chat_response(
        _line(SUCCESS_ICON, f"Quote <b>{quote.name}</b> approved in Deal Desk."),
        deal_packet_id=packet.id,
        status=packet.status,
    )


def _reject_quote(user, user_message: str, session_data: dict):
    tenant, tenant_error = _current_tenant_or_error()
    if tenant_error:
        return tenant_error

    quote = _resolve_quote(user_message, session_data)
    if not quote:
        return _chat_response(_line(WARNING_ICON, "No active quote found to reject."))

    packet = _latest_packet_for_quote(tenant.tenant_id, quote)
    if not packet:
        return _chat_response(_line(WARNING_ICON, f"Quote <b>{quote.name}</b> has no Deal Desk approval packet."))

    instance = (
        packet.approval_instances.select_related("quoteapproval", "quoteapproval__step")
        .order_by("-created_at")
        .first()
    )
    if not instance or not instance.quoteapproval:
        return _chat_response(_line(WARNING_ICON, f"No pending approval instance found for quote <b>{quote.name}</b>."))

    approval = instance.quoteapproval
    if approval.status == "Rejected":
        return _chat_response(_line(INFO_ICON, f"Quote <b>{quote.name}</b> is already rejected."))
    if approval.status == "Approved":
        return _chat_response(_line(WARNING_ICON, f"Quote <b>{quote.name}</b> is already approved and cannot be rejected."))
    if approval.status != "Pending":
        return _chat_response(
            _line(WARNING_ICON, f"Unsupported approval status <b>{approval.status}</b> for quote <b>{quote.name}</b>.")
        )

    approval.status = "Rejected"
    approval.approved_by = getattr(user, "username", "System")
    approval.approved_at = timezone.now()
    approval.save(update_fields=["status", "approved_by", "approved_at"])

    quote.status = "Rejected"
    quote.save(update_fields=["status"])

    packet.status = DealPacket.STATUS_REJECTED
    packet.decision_summary = "Deal rejected."
    packet.save(update_fields=["status", "decision_summary", "updated_at"])

    create_tenant_audit_event(
        tenant_id=tenant.tenant_id,
        run_id=f"ddrun-{uuid.uuid4().hex[:12]}",
        source="orchestrator",
        entity_type="deal_packet",
        entity_id=str(packet.id),
        event_type="rejected",
        details={"rejected_by": approval.approved_by},
        idempotency_key=packet.idempotency_key,
        tenant_resolution_source="tenant_first",
    )

    _track_session(session_data, quote, packet, packet.policy_evaluations.order_by("-created_at").first())
    return _chat_response(
        _line(ERROR_ICON, f"Quote <b>{quote.name}</b> rejected in Deal Desk."),
        deal_packet_id=packet.id,
        status=packet.status,
    )


def _recall_quote(user, user_message: str, session_data: dict):
    return _chat_response(
        _line(WARNING_ICON, "Recall is not supported in Deal Desk chat flow yet. Use reject and resubmit after edits.")
    )
