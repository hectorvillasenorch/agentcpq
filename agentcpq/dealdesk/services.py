import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from cpq.models import (
    Account,
    ApprovalRule,
    ApprovalStep,
    ApprovalWorkflow,
    Opportunity,
    Quote,
    QuoteApproval,
    Tenant,
)

from .models import (
    AuditEvent,
    DealDeskApprovalInstance,
    DealPacket,
    PolicyConfig,
    PolicyEvaluation,
    SystemAuditEvent,
)

try:
    from jsonschema import Draft202012Validator
except Exception:  # pragma: no cover - dependency is present in runtime
    Draft202012Validator = None


DEFAULT_POLICY_VERSION = "default-v1"
DEFAULT_POLICY_CONFIG = {
    "routing_mode": "reuse_first_instance_fallback",
    "discount_thresholds": {
        "level_1": 10,
        "level_2": 20,
    },
    "roles": {
        "discount_level_1": ["Sales Director"],
        "discount_level_2": ["VP Sales", "Finance"],
        "high_risk_payment_terms": ["Finance", "Legal"],
        "custom_terms": ["Legal"],
    },
    "high_risk_payment_terms": ["net60", "net90", "due_on_receipt"],
    "idempotency_ttl_hours": 24,
}


@dataclass
class TenantResolution:
    ok: bool
    tenant_id: str | None = None
    source: str | None = None
    status_code: int = 400
    error_code: str | None = None
    error_message: str | None = None
    presented: dict[str, Any] | None = None


def _tenant_from_subdomain(host: str | None) -> tuple[str | None, str | None]:
    if not host:
        return None, None

    clean_host = host.split(":")[0].strip().lower()
    if clean_host in {"localhost", "127.0.0.1", ""}:
        return None, clean_host

    tenant = Tenant.objects.filter(domain__iexact=clean_host).first()
    if tenant and tenant.tenant_id:
        return tenant.tenant_id, clean_host

    labels = clean_host.split(".")
    if len(labels) < 3:
        return None, clean_host

    subdomain = labels[0]
    tenant = Tenant.objects.filter(tenant_id=subdomain).first()
    if tenant and tenant.tenant_id:
        return tenant.tenant_id, clean_host

    tenant = Tenant.objects.filter(domain__icontains=subdomain).first()
    if tenant and tenant.tenant_id:
        return tenant.tenant_id, clean_host

    return None, clean_host


def _tenant_from_api_key(request) -> str | None:
    api_key = (request.headers.get("X-API-KEY") or "").strip()
    if not api_key:
        return None
    tenant = Tenant.objects.filter(api_key=api_key).first()
    if not tenant:
        return None
    return tenant.tenant_id


def _tenant_from_session_user(request) -> str | None:
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return None

    owned_account_tenant = (
        Account.objects.filter(owner=user)
        .exclude(tenant_id__isnull=True)
        .exclude(tenant_id="")
        .values_list("tenant_id", flat=True)
        .first()
    )
    return owned_account_tenant


def _validate_explicit_tenant(explicit_tenant_id: str | None) -> str | None:
    if not explicit_tenant_id:
        return None
    exists = Tenant.objects.filter(tenant_id=explicit_tenant_id).exists()
    if not exists:
        return None
    return explicit_tenant_id


def resolve_tenant_context(request, *, channel: str, explicit_tenant_id: str | None = None) -> TenantResolution:
    channel = (channel or "api").lower()

    subdomain_tenant, host = _tenant_from_subdomain(request.get_host())
    api_key_tenant = _tenant_from_api_key(request)
    session_tenant = _tenant_from_session_user(request)
    explicit_tenant = _validate_explicit_tenant(explicit_tenant_id)

    presented = {
        "host": host,
        "subdomain_tenant_id": subdomain_tenant,
        "api_key_tenant_id": api_key_tenant,
        "session_user_tenant_id": session_tenant,
        "explicit_tenant_id": explicit_tenant_id,
    }

    if channel == "orchestrator":
        if not explicit_tenant:
            return TenantResolution(
                ok=False,
                status_code=400,
                error_code="tenant_missing_orchestrator",
                error_message="Orchestrator requests must include a valid explicit tenant_id.",
                presented=presented,
            )
        return TenantResolution(ok=True, tenant_id=explicit_tenant, source="explicit_tenant_id", presented=presented)

    if channel == "ui":
        if subdomain_tenant and session_tenant and subdomain_tenant != session_tenant:
            return TenantResolution(
                ok=False,
                status_code=403,
                error_code="tenant_conflict",
                error_message="Subdomain tenant does not match session user tenant.",
                presented=presented,
            )
        if subdomain_tenant:
            return TenantResolution(ok=True, tenant_id=subdomain_tenant, source="subdomain", presented=presented)
        if session_tenant:
            return TenantResolution(ok=True, tenant_id=session_tenant, source="session_user", presented=presented)
        return TenantResolution(
            ok=False,
            status_code=400,
            error_code="tenant_missing",
            error_message="UI request missing tenant context.",
            presented=presented,
        )

    # API / webhook channels
    if subdomain_tenant and api_key_tenant and subdomain_tenant != api_key_tenant:
        return TenantResolution(
            ok=False,
            status_code=403,
            error_code="tenant_conflict",
            error_message="Subdomain tenant does not match API key tenant.",
            presented=presented,
        )

    if subdomain_tenant:
        return TenantResolution(ok=True, tenant_id=subdomain_tenant, source="subdomain", presented=presented)
    if api_key_tenant:
        return TenantResolution(ok=True, tenant_id=api_key_tenant, source="api_key", presented=presented)

    return TenantResolution(
        ok=False,
        status_code=403,
        error_code="tenant_missing",
        error_message="Missing tenant context. Provide subdomain or X-API-KEY.",
        presented=presented,
    )


def create_tenant_audit_event(
    *,
    tenant_id: str,
    run_id: str,
    source: str,
    entity_type: str,
    entity_id: str,
    event_type: str,
    details: dict[str, Any] | None = None,
    idempotency_key: str = "",
    tenant_resolution_source: str = "",
    duplicate_request_detected: bool = False,
) -> AuditEvent:
    return AuditEvent.objects.create(
        tenant_id=tenant_id,
        run_id=run_id,
        source=source,
        idempotency_key=idempotency_key,
        tenant_resolution_source=tenant_resolution_source,
        duplicate_request_detected=duplicate_request_detected,
        entity_type=entity_type,
        entity_id=str(entity_id),
        event_type=event_type,
        details_json=details or {},
    )


def create_system_audit_event(
    *,
    source: str,
    event_type: str,
    request_meta: dict[str, Any] | None = None,
    idempotency_key: str = "",
) -> SystemAuditEvent:
    return SystemAuditEvent.objects.create(
        source=source,
        event_type=event_type,
        request_meta_json=request_meta or {},
        idempotency_key_if_present=idempotency_key,
    )


def _normalize_for_hash(value: Any):
    if isinstance(value, bool):
        return value

    if isinstance(value, dict):
        cleaned = {}
        for key in sorted(value.keys()):
            nested = _normalize_for_hash(value[key])
            if nested in (None, "", [], {}):
                continue
            cleaned[key] = nested
        return cleaned

    if isinstance(value, list):
        items = []
        for item in value:
            nested = _normalize_for_hash(item)
            if nested in (None, "", [], {}):
                continue
            items.append(nested)
        return items

    if isinstance(value, str):
        stripped = value.strip()
        if _looks_like_date(stripped):
            return _normalize_date_string(stripped)
        return stripped

    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")

    if isinstance(value, Decimal):
        return float(value.quantize(Decimal("0.01")))

    if isinstance(value, (int, float)):
        return round(float(value), 2)

    return value


def compute_request_fingerprint(payload: dict[str, Any]) -> str:
    normalized = _normalize_for_hash(payload or {})
    packed = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def build_idempotency_key(
    *,
    tenant_id: str,
    channel: str,
    external_ref_type: str,
    external_ref_id: str,
    payload: dict[str, Any],
    policy_version: str,
    client_key: str | None = None,
) -> str:
    if client_key:
        return f"ddrv1:{tenant_id}:client:{client_key.strip()}"

    fingerprint = compute_request_fingerprint(payload)
    payload_hash8 = fingerprint[:8]
    return (
        f"ddrv1:{tenant_id}:{channel}:{external_ref_type}:{external_ref_id}:{payload_hash8}:{policy_version}"
    )


def get_active_policy_config(tenant_id: str) -> tuple[str, dict[str, Any], int]:
    policy = PolicyConfig.objects.filter(tenant_id=tenant_id, is_active=True).order_by("-updated_at").first()
    if not policy:
        return DEFAULT_POLICY_VERSION, dict(DEFAULT_POLICY_CONFIG), int(DEFAULT_POLICY_CONFIG["idempotency_ttl_hours"])

    merged = dict(DEFAULT_POLICY_CONFIG)
    merged.update(policy.config_json or {})
    ttl = int(merged.get("idempotency_ttl_hours", DEFAULT_POLICY_CONFIG["idempotency_ttl_hours"]))
    return policy.version, merged, ttl


_SCHEMA_CACHE = None


def _load_schema() -> dict[str, Any] | None:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE

    schema_path = Path(__file__).resolve().parent / "schemas" / "deal_packet_v1.schema.json"
    if not schema_path.exists():
        return None

    with schema_path.open("r", encoding="utf-8") as fh:
        _SCHEMA_CACHE = json.load(fh)
    return _SCHEMA_CACHE


def validate_deal_packet_schema(payload: dict[str, Any]) -> dict[str, Any]:
    schema = _load_schema()
    if not schema or Draft202012Validator is None:
        return {"valid": True, "required_fields": [], "errors": []}

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))

    required_fields = []
    parsed_errors = []

    for error in errors:
        path_bits = [str(bit) for bit in error.path]
        if error.validator == "required":
            missing = None
            if "'" in error.message:
                try:
                    missing = error.message.split("'")[1]
                except IndexError:
                    missing = None
            joined_path = ".".join(path_bits) if path_bits else ""
            field_path = f"{joined_path}.{missing}".strip(".") if missing else joined_path
            if field_path:
                required_fields.append(field_path)
        parsed_errors.append({"path": ".".join(path_bits), "message": error.message})

    return {
        "valid": len(errors) == 0,
        "required_fields": sorted(set(required_fields)),
        "errors": parsed_errors,
    }


def _to_decimal(value: Any, default: Decimal = Decimal("0.00")) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _looks_like_date(value: str) -> bool:
    if len(value) != 10:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _normalize_date_string(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return value


def evaluate_policy(payload: dict[str, Any], policy_config: dict[str, Any]) -> dict[str, Any]:
    results: dict[str, Any] = {
        "flags": [],
        "required_approvals": [],
        "required_fields": [],
        "violations": [],
        "recommendations": [],
        "comps": [],
    }

    commercial = payload.get("commercial_terms") or {}
    request_context = payload.get("request_context") or {}
    pricing_summary = payload.get("pricing_summary") or {}
    concessions = payload.get("concessions") or []
    policy_inputs = payload.get("policy_inputs") or {}

    if not commercial.get("term_months"):
        results["required_fields"].append("commercial_terms.term_months")
    if not str(commercial.get("payment_terms") or "").strip():
        results["required_fields"].append("commercial_terms.payment_terms")
    if not str(request_context.get("justification") or "").strip():
        results["required_fields"].append("request_context.justification")

    discount_percent = _to_decimal(
        policy_inputs.get("discount_percent", pricing_summary.get("discount_percent", 0))
    )

    thresholds = policy_config.get("discount_thresholds") or {}
    level_1 = _to_decimal(thresholds.get("level_1", 10))
    level_2 = _to_decimal(thresholds.get("level_2", 20))

    roles_config = policy_config.get("roles") or {}

    def _add_approval(role_name: str, reason: str, trigger: str):
        role = str(role_name or "").strip()
        if not role:
            return
        existing = {(item.get("role"), item.get("trigger")) for item in results["required_approvals"]}
        key = (role, trigger)
        if key in existing:
            return
        results["required_approvals"].append(
            {
                "role": role,
                "reason": reason,
                "trigger": trigger,
            }
        )

    if discount_percent > level_1:
        for role in roles_config.get("discount_level_1", ["Sales Director"]):
            _add_approval(role, f"Discount {discount_percent}% exceeds {level_1}% threshold.", "discount_threshold_1")

    if discount_percent > level_2:
        for role in roles_config.get("discount_level_2", ["VP Sales", "Finance"]):
            _add_approval(role, f"Discount {discount_percent}% exceeds {level_2}% threshold.", "discount_threshold_2")

    payment_terms = str(
        commercial.get("payment_terms")
        or policy_inputs.get("requested_payment_terms")
        or ""
    ).strip().lower()

    risky_terms = {str(term).strip().lower() for term in policy_config.get("high_risk_payment_terms", [])}
    if payment_terms and payment_terms in risky_terms:
        for role in roles_config.get("high_risk_payment_terms", ["Finance", "Legal"]):
            _add_approval(role, f"Payment terms {payment_terms} requires extra review.", "payment_terms")

    has_custom_terms = bool(policy_inputs.get("has_custom_terms")) or any(
        (item.get("type") == "custom_terms") for item in concessions if isinstance(item, dict)
    )
    if has_custom_terms:
        for role in roles_config.get("custom_terms", ["Legal"]):
            _add_approval(role, "Custom terms require legal review.", "custom_terms")

    list_total = _to_decimal(pricing_summary.get("list_total"))
    net_total = _to_decimal(pricing_summary.get("net_total"))

    if list_total < 0 or net_total < 0:
        results["violations"].append("pricing_summary totals cannot be negative")

    if list_total > 0 and net_total > list_total and not str(request_context.get("justification") or "").strip():
        results["violations"].append("net_total cannot exceed list_total without justification")

    for segment in commercial.get("ramp_segments") or []:
        if not isinstance(segment, dict):
            continue
        start_date = segment.get("start_date")
        end_date = segment.get("end_date")
        if start_date and end_date and _looks_like_date(str(start_date)) and _looks_like_date(str(end_date)):
            start = datetime.strptime(str(start_date), "%Y-%m-%d").date()
            end = datetime.strptime(str(end_date), "%Y-%m-%d").date()
            if end < start:
                results["violations"].append("commercial_terms.ramp_segments end_date cannot be before start_date")

    results["required_fields"] = sorted(set(results["required_fields"]))
    return results


def compute_status_from_policy(results_json: dict[str, Any]) -> str:
    if results_json.get("required_fields") or results_json.get("violations"):
        return DealPacket.STATUS_NEEDS_INFO
    if results_json.get("required_approvals"):
        return DealPacket.STATUS_IN_APPROVAL
    return DealPacket.STATUS_APPROVED


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def find_opportunity(payload: dict[str, Any]) -> Opportunity | None:
    opportunity_data = payload.get("opportunity") or {}
    opp_ref = opportunity_data.get("id")
    if opp_ref is None:
        return None

    opp_id = _coerce_int(opp_ref)
    if opp_id is not None:
        found = Opportunity.objects.filter(id=opp_id).first()
        if found:
            return found

    ref_str = str(opp_ref)
    return Opportunity.objects.filter(
        Q(oppid=ref_str) | Q(external_id=ref_str) | Q(name=ref_str)
    ).first()


def resolve_quote_for_packet(
    *,
    deal_packet: DealPacket,
    payload: dict[str, Any],
    actor=None,
) -> tuple[Quote | None, str | None]:
    quote_ref = payload.get("quote_ref")
    if isinstance(quote_ref, dict):
        quote_ref = quote_ref.get("id")

    if quote_ref is None and deal_packet.external_ref_type == DealPacket.EXTERNAL_REF_QUOTE:
        quote_ref = deal_packet.external_ref_id

    if quote_ref is not None:
        quote_id = _coerce_int(quote_ref)
        if quote_id is not None:
            quote = Quote.objects.filter(id=quote_id).first()
            if quote:
                return quote, None

        quote = Quote.objects.filter(Q(qteid=str(quote_ref)) | Q(name=str(quote_ref)) | Q(external_id=str(quote_ref))).first()
        if quote:
            return quote, None

    opportunity = find_opportunity(payload)
    if not opportunity:
        return None, "opportunity_not_found"

    existing_quote = Quote.objects.filter(opportunity=opportunity).order_by("-created_at").first()
    if existing_quote:
        return existing_quote, None

    actor_user = None
    UserModel = get_user_model()
    if isinstance(actor, UserModel):
        actor_user = actor

    quote = Quote.objects.create(
        name=f"DD-SHELL-{uuid.uuid4().hex[:10]}",
        account=opportunity.account,
        opportunity=opportunity,
        net_amount=Decimal("0.00"),
        status="Draft",
        created_by=actor_user,
        updated_by=actor_user,
        owner=actor_user,
    )
    return quote, None


def _roles_from_rule(rule: ApprovalRule) -> list[str]:
    return list(rule.steps.order_by("sequence").values_list("approver_role", flat=True))


def _extract_required_roles(results_json: dict[str, Any]) -> list[str]:
    required = []
    seen = set()
    for item in results_json.get("required_approvals") or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if not role:
            continue
        key = role.lower()
        if key in seen:
            continue
        seen.add(key)
        required.append(role)
    return required


def _find_matching_template(required_roles: list[str]) -> tuple[ApprovalWorkflow | None, ApprovalRule | None]:
    if not required_roles:
        return None, None

    workflows = ApprovalWorkflow.objects.prefetch_related("rules__steps").all()
    for workflow in workflows:
        for rule in workflow.rules.all():
            if _roles_from_rule(rule) == required_roles:
                return workflow, rule
    return None, None


def _create_instance_workflow(required_roles: list[str], deal_packet: DealPacket) -> tuple[ApprovalWorkflow, ApprovalRule]:
    workflow = ApprovalWorkflow.objects.create(
        name=f"DealDesk Instance {deal_packet.id}",
        description=f"Auto-generated workflow instance for DealPacket {deal_packet.id}",
    )
    rule = ApprovalRule.objects.create(
        workflow=workflow,
        name=f"DealDesk Rule {deal_packet.id}",
        priority=0,
    )
    for seq, role in enumerate(required_roles, start=1):
        ApprovalStep.objects.create(rule=rule, sequence=seq, approver_role=role)

    return workflow, rule


def build_instance_key(
    *,
    tenant_id: str,
    deal_packet_id: int,
    quote_ref: str,
    policy_version: str,
    required_approvals: list[dict[str, Any]],
) -> str:
    normalized_approvals = []
    for item in required_approvals or []:
        if not isinstance(item, dict):
            continue
        normalized_approvals.append(
            {
                "role": str(item.get("role") or "").strip().lower(),
                "trigger": str(item.get("trigger") or "").strip().lower(),
                "reason": str(item.get("reason") or "").strip().lower(),
            }
        )

    normalized_approvals.sort(key=lambda row: (row["role"], row["trigger"], row["reason"]))

    canonical = {
        "tenant_id": tenant_id,
        "deal_packet_id": deal_packet_id,
        "quote_ref": str(quote_ref),
        "policy_version": policy_version,
        "required_approvals": normalized_approvals,
    }
    packed = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(packed.encode("utf-8")).hexdigest()[:32]
    return f"ddai:v1:{digest}"


def route_approvals_for_packet(
    *,
    deal_packet: DealPacket,
    quote: Quote,
    results_json: dict[str, Any],
    policy_version: str,
) -> dict[str, Any]:
    required_roles = _extract_required_roles(results_json)
    if not required_roles:
        return {"routed": False, "reason": "no_required_approvals"}

    instance_key = build_instance_key(
        tenant_id=deal_packet.tenant_id,
        deal_packet_id=deal_packet.id,
        quote_ref=quote.id,
        policy_version=policy_version,
        required_approvals=results_json.get("required_approvals") or [],
    )

    with transaction.atomic():
        existing_instance = DealDeskApprovalInstance.objects.filter(
            tenant_id=deal_packet.tenant_id,
            deal_packet=deal_packet,
            instance_key=instance_key,
        ).select_related("quoteapproval", "template_workflow_ref", "instance_workflow_ref").first()

        if existing_instance:
            return {
                "routed": True,
                "replayed": True,
                "routing_mode": existing_instance.routing_mode,
                "approval_instance_id": existing_instance.id,
                "quoteapproval_id": existing_instance.quoteapproval_id,
                "instance_key": instance_key,
            }

        workflow, rule = _find_matching_template(required_roles)
        routing_mode = DealDeskApprovalInstance.ROUTING_TEMPLATE_USED
        template_workflow_ref = workflow
        instance_workflow_ref = None

        if not workflow or not rule:
            workflow, rule = _create_instance_workflow(required_roles, deal_packet)
            routing_mode = DealDeskApprovalInstance.ROUTING_INSTANCE_FALLBACK
            template_workflow_ref = None
            instance_workflow_ref = workflow

        first_step = rule.steps.order_by("sequence").first()
        if not first_step:
            return {"routed": False, "error": "missing_approval_step"}

        quoteapproval, _ = QuoteApproval.objects.get_or_create(
            quote=quote,
            workflow=workflow,
            step=first_step,
            defaults={
                "status": "Pending",
            },
        )

        if quote.status != "Pending Approval":
            quote.status = "Pending Approval"
            quote.save(update_fields=["status"])

        try:
            instance = DealDeskApprovalInstance.objects.create(
                tenant_id=deal_packet.tenant_id,
                deal_packet=deal_packet,
                quoteapproval=quoteapproval,
                routing_mode=routing_mode,
                template_workflow_ref=template_workflow_ref,
                instance_workflow_ref=instance_workflow_ref,
                instance_key=instance_key,
            )
        except IntegrityError:
            instance = DealDeskApprovalInstance.objects.get(
                tenant_id=deal_packet.tenant_id,
                deal_packet=deal_packet,
                instance_key=instance_key,
            )

    return {
        "routed": True,
        "routing_mode": routing_mode,
        "approval_instance_id": instance.id,
        "quoteapproval_id": instance.quoteapproval_id,
        "workflow_id": workflow.id,
        "step_id": first_step.id,
        "instance_key": instance_key,
    }


def emit_result_payload(
    *,
    deal_packet: DealPacket,
    policy_eval: PolicyEvaluation | None = None,
) -> dict[str, Any]:
    payload = {
        "dealdesk_status": deal_packet.status,
        "dealdesk_last_decision": deal_packet.status,
        "dealdesk_summary": deal_packet.decision_summary,
        "deal_packet_id": deal_packet.id,
        "public_id": str(deal_packet.public_id),
    }

    if policy_eval is not None:
        payload["policy_version"] = policy_eval.policy_version
        payload["required_approvals"] = policy_eval.results_json.get("required_approvals", [])

    return payload


def serialize_deal_packet(packet: DealPacket) -> dict[str, Any]:
    return {
        "id": packet.id,
        "public_id": str(packet.public_id),
        "tenant_id": packet.tenant_id,
        "external_ref_type": packet.external_ref_type,
        "external_ref_id": packet.external_ref_id,
        "status": packet.status,
        "payload_json": packet.payload_json,
        "decision_summary": packet.decision_summary,
        "created_at": packet.created_at.isoformat() if packet.created_at else None,
        "updated_at": packet.updated_at.isoformat() if packet.updated_at else None,
    }


def serialize_audit_event(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "tenant_id": event.tenant_id,
        "run_id": event.run_id,
        "source": event.source,
        "idempotency_key": event.idempotency_key,
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "details_json": event.details_json,
        "duplicate_request_detected": event.duplicate_request_detected,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def compute_template_checksum(workflow_ids: list[int]) -> str:
    workflows = list(
        ApprovalWorkflow.objects.filter(id__in=workflow_ids)
        .order_by("id")
        .values("id", "name", "description")
    )
    rules = list(
        ApprovalRule.objects.filter(workflow_id__in=workflow_ids)
        .order_by("id")
        .values("id", "workflow_id", "name", "priority")
    )
    rule_ids = [row["id"] for row in rules]
    steps = list(
        ApprovalStep.objects.filter(rule_id__in=rule_ids)
        .order_by("id")
        .values("id", "rule_id", "sequence", "approver_role")
    )

    payload = {
        "workflows": workflows,
        "rules": rules,
        "steps": steps,
    }
    packed = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()
