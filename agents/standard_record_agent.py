import json
import logging
import os
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import openai
from django.contrib.auth import get_user_model
from django.db.models import ForeignKey, Q
from django.utils.dateparse import parse_date
from dotenv import load_dotenv

from agents.llm import chat_json, get_llm_client, get_model

from cpq.models import (
    Account,
    Activity,
    Contact,
    Contract,
    CustomField,
    CustomFieldValue,
    Knowledge,
    Lead,
    Opportunity,
    Option,
    Product,
    Quote,
    QuoteLine,
    Subscription,
    Tenant,
    default_opportunity_expected_close_date,
    generate_agentcpq_id,
)
from cpq.permissions import partner_can_access_record
from django.contrib.contenttypes.models import ContentType
from .utils.agents_utils import clean_llm_json
from .utils.message_formatters import SUCCESS_ICON
from .utils.orchestrator.context_handle_helpers import estimate_cost, extract_current_request
from .utils.session_context_helpers.session_context_helpers import get_session_context
from .utils.admin_agent.rules_helpers import check_for_validation_rules

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = get_llm_client()
logger = logging.getLogger(__name__)
User = get_user_model()

CREATE_SUPPORTED_OBJECTS = [
    "Lead",
    "Account",
    "Contact",
    "Opportunity",
    "Activity",
    "Contract",
    "Subscription",
    "Option",
    "Tenant",
    "Knowledge",
]

BULK_CREATE_SUPPORTED_OBJECTS = {
    "Lead",
    "Account",
    "Knowledge",
    "Tenant",
}
BULK_CREATE_THRESHOLD = int(os.getenv("BULK_CREATE_THRESHOLD", "2"))
BULK_CREATE_BATCH_SIZE = int(os.getenv("BULK_CREATE_BATCH_SIZE", "50"))
BATCH_UPDATE_DATA_MARKER = "__BATCH_DATA_START__"

# Update/delete now mirrors create: every chat-creatable object can also be
# updated/deleted. Lookups resolve via IDENTIFIER_FIELDS below.
UPDATE_DELETE_SUPPORTED_OBJECTS = [
    "Lead",
    "Account",
    "Contact",
    "Opportunity",
    "Activity",
    "Contract",
    "Subscription",
    "Option",
    "Tenant",
    "Knowledge",
]

REQUIRED_FIELDS: Dict[str, List[str]] = {
    "Lead": ["first_name", "last_name"],
    "Account": ["name"],
    "Contact": ["first_name", "email", "account"],
    "Opportunity": ["name", "account"],
    "Activity": ["subject", "activity_type"],
    "Contract": ["opportunity", "start_date", "contract_status"],
    "Subscription": ["quote", "quote_line", "product", "contract", "start_date", "end_date", "price_per_cycle", "term"],
    "Option": ["parent_product", "product_option"],
    "Tenant": ["name"],
    "Knowledge": ["title", "content_text"],
}

MODEL_MAP = {
    "Lead": Lead,
    "Account": Account,
    "Contact": Contact,
    "Opportunity": Opportunity,
    "Activity": Activity,
    "Contract": Contract,
    "Subscription": Subscription,
    "Option": Option,
    "Tenant": Tenant,
    "Knowledge": Knowledge,
}

# Optional extras that aren't model fields but we still accept (e.g., mapped into notes)
EXTRA_FIELDS = {
    "Lead": ["company", "company_name", "title"],
}

ALLOWED_FIELDS: Dict[str, List[str]] = {}
ALLOWED_FIELD_MAP: Dict[str, Dict[str, str]] = {}


def _business_rule_target_key(object_name: str) -> str:
    return str(object_name or "").strip().lower()


def _build_business_rule_context(record, object_name: str, user=None) -> Dict[str, object]:
    """
    Provide a context map for `fieldName` resolution.
    Root key defaults to the lowercased object_name used as BusinessRule.target_type.
    Also inject common related objects to support conditions like `quote.opportunity.stage`.
    """
    context: Dict[str, object] = {}
    root_key = _business_rule_target_key(object_name)
    if root_key:
        context[root_key] = record
        context["_default_root"] = root_key

    for rel in ("quote", "quote_line", "product", "account", "opportunity", "contract", "tenant"):
        try:
            value = getattr(record, rel, None)
        except Exception:
            value = None
        if value is not None:
            context[rel] = value

    # Allow rules to reference the acting user (e.g., user.is_superuser).
    if user is not None:
        context["user"] = user

    return context


def _refresh_allowed_fields():
    """Build allowed fields from model metadata + extras + custom fields."""
    global ALLOWED_FIELDS, ALLOWED_FIELD_MAP
    allowed: Dict[str, List[str]] = {}
    allowed_map: Dict[str, Dict[str, str]] = {}

    for obj, model in MODEL_MAP.items():
        model_fields = [
            f.name
            for f in model._meta.get_fields()
            if not getattr(f, "auto_created", False)
            and getattr(f, "editable", True)
            and not f.many_to_many  # avoid M2M intermediary
        ]
        extras = EXTRA_FIELDS.get(obj, [])

        try:
            custom_fields = CustomField.objects.filter(custom_object__isnull=True, object_type=obj)
            custom_field_names = []
            for cf in custom_fields:
                if cf.name:
                    custom_field_names.append(cf.name)
                if cf.label:
                    custom_field_names.append(cf.label)
        except Exception:
            custom_fields = []
            custom_field_names = []

        merged = list({*model_fields, *extras, *custom_field_names})
        allowed[obj] = merged
        obj_map: Dict[str, str] = {}

        # Base model + extras
        for name in model_fields + extras:
            obj_map[name.lower()] = name

        # Custom fields → allow name, label, and underscored label variants to map to canonical custom name
        for cf in custom_fields or []:
            canonical = cf.name or cf.label
            if not canonical:
                continue
            variants = [v for v in [cf.name, cf.label] if v]
            for var in variants:
                obj_map[var.lower()] = canonical
                underscored = re.sub(r"\s+", "_", var.strip()).lower()
                obj_map[underscored] = canonical

        # Common synonyms (keep additive)
        if obj == "Contract":
            obj_map.setdefault("status", "contract_status")
        if obj == "Subscription":
            obj_map.setdefault("billing_frequency", "billing_cycle")

        allowed_map[obj] = obj_map

    ALLOWED_FIELDS = allowed
    ALLOWED_FIELD_MAP = allowed_map


def standard_record_agent(user, action, user_message, session_data):
    # Chat CRUD is allowed for authenticated users.
    # Record-level authorization for update/delete is enforced in persistence helpers.

    if action == "CreateStandardRecord":
        return _create_standard_records(user, user_message, session_data)
    if action == "UpdateStandardRecord":
        return _update_standard_records(user, user_message, session_data)
    if action == "DeleteStandardRecord":
        return _delete_standard_records(user, user_message, session_data)
    return {"message": "⚠️ Unsupported action for standard records."}


def _apply_activity_defaults(user, user_message: str, data: dict) -> None:
    """Fill sensible defaults for an Activity create request so it succeeds immediately.

    Derives the subject + a related Opportunity/Contact from any referenced Account,
    defaults the type/status, and marks the request completed.
    """
    fields = data.setdefault("fields", {})

    account_ref = (
        fields.get("account")
        or fields.get("Account")
        or fields.get("account__c")
    )
    if not account_ref:
        match = re.search(
            r"(?:for|on|with)\s+(?:the\s+)?(?:account)\s+(.+?)(?:\s+please)?$",
            user_message.strip(),
            re.IGNORECASE,
        )
        if match:
            account_ref = match.group(1).strip()

    subject_name = "Activity"
    if account_ref:
        try:
            account = _find_record("Account", account_ref)
        except Exception:
            account = None
        if account:
            subject_name = getattr(account, "name", None) or subject_name
            if not (fields.get("opportunity") or fields.get("contact") or fields.get("lead")):
                opp = account.opportunities.first() if hasattr(account, "opportunities") else None
                if opp is not None:
                    fields["opportunity"] = getattr(opp, "name", None) or str(opp)
                else:
                    contact = account.contacts.first() if hasattr(account, "contacts") else None
                    if contact is not None:
                        fields["contact"] = getattr(contact, "email", None) or getattr(contact, "contactId", None) or str(contact)

    # If the LLM used the account reference as the subject, replace it with a real one.
    current_subject = str(fields.get("subject") or "").strip()
    if account_ref:
        ref_variants = {
            str(account_ref).strip().lower(),
            subject_name.lower(),
            f"account {str(account_ref).strip().lower()}",
        }
        if not current_subject or current_subject.lower() in ref_variants:
            fields["subject"] = f"Follow-up: {subject_name}"
    elif not current_subject:
        fields["subject"] = "Follow-up: Activity"

    if not fields.get("activity_type"):
        fields["activity_type"] = "call"
    if not fields.get("status"):
        fields["status"] = "not_started"


def _try_fast_activity_create(user, user_message: str) -> Optional[Dict[str, object]]:
    """Deterministically create an Activity for an explicitly named Account (no LLM)."""
    match = re.match(
        r"^(?:create|add|log|schedule)\s+(?:an?\s+)?activity\s+for\s+(?:the\s+)?account\s+(.+)$",
        user_message.strip(),
        re.IGNORECASE,
    )
    if not match:
        return None

    data: Dict[str, object] = {"object": "Activity", "fields": {}}
    _apply_activity_defaults(user, f"for account {match.group(1).strip()}", data)

    success, message, record_payload = _persist_record(user, "Activity", data["fields"])  # type: ignore[arg-type]
    if not success:
        return {"message": message or "⚠️ Could not create the activity."}

    response: Dict[str, object] = {
        "message": f"{SUCCESS_ICON} Created Activity '{record_payload['label']}'.",
        "hiddenMessage": False,
    }
    try:
        from agents.utils.record_agent.handle_helpers import serialize_record
        from agents.utils.analytics_agent.handle_helpers import get_object_metadata

        activity = Activity.objects.get(pk=record_payload.get("id"))
        metadata = get_object_metadata("Activity") or {}
        response["single_record"] = serialize_record(
            activity,
            "Activity",
            None,
            metadata.get("custom_fields") or [],
            user=user,
        )
    except Exception:
        logger.exception("Failed to attach Activity form (fast path)")
    return response


# Objects where we can detect an existing record by a natural key before creating.
# value = ordered candidate field names to compare (iexact) from the create payload.
_DUPLICATE_KEY_FIELDS = {
    "Account": ["name"],
    "Tenant": ["name"],
    "Contact": ["email", "phone"],
    "Lead": ["email", "phone"],
    "Opportunity": ["name"],
}


def _friendly_label(record) -> str:
    parts = [
        getattr(record, "first_name", None),
        getattr(record, "last_name", None),
    ]
    full_name = " ".join(str(p) for p in parts if p).strip()
    return (
        full_name
        or getattr(record, "name", None)
        or getattr(record, "email", None)
        or getattr(record, "title", None)
        or str(record)
    )


def _check_create_duplicate(object_name: str, fields: Dict[str, object]) -> Optional[Dict[str, object]]:
    """Return the first existing record that matches the create payload's natural key."""
    key_fields = _DUPLICATE_KEY_FIELDS.get(object_name)
    if not key_fields:
        return None
    model = {
        "Account": Account,
        "Tenant": Tenant,
        "Contact": Contact,
        "Lead": Lead,
        "Opportunity": Opportunity,
    }.get(object_name)
    if model is None:
        return None

    queryset = model.objects.all()
    matched_filter = None
    matched_key = None
    for key in key_fields:
        value = fields.get(key) or fields.get(key.title()) or fields.get(key.upper())
        if not value:
            continue
        candidate = {f"{key}__iexact": str(value).strip()}
        # Opportunities only match when they belong to the same account, to avoid
        # blocking legitimately repeated names across different accounts.
        if object_name == "Opportunity":
            account_value = fields.get("account") or fields.get("Account")
            if account_value:
                account = _find_record("Account", account_value)
                if account is None:
                    continue
                candidate["account"] = account
            else:
                continue
        if queryset.filter(**candidate).exists():
            matched_filter = candidate
            matched_key = key
            break

    if matched_filter is None:
        return None

    record = queryset.filter(**matched_filter).first()
    if record is None:
        return None
    label = _friendly_label(record)
    id_field = _id_field_for_object(object_name)
    identifier = getattr(record, id_field, None) if hasattr(record, id_field) else getattr(record, "pk", None)
    return {
        "object": object_name,
        "key": matched_key,
        "label": label,
        "identifier": identifier,
        "record_id": getattr(record, "pk", None),
    }


def _auto_unique_name(model, base_name: str) -> str:
    """Return f'{base_name} 2' / '3' ... (first name not already used)."""
    existing = set(str(n).strip().lower() for n in model.objects.values_list("name", flat=True) if n)
    candidate = base_name
    counter = 2
    while candidate.strip().lower() in existing:
        candidate = f"{base_name} {counter}"
        counter += 1
    return candidate


def resolve_duplicate_confirmation(user, user_message, session_data):
    """Handle the user's reply to a duplicate-creation prompt.

    Returns a response dict to CONSUME the message (use / create-new / cancel), or
    None when the message is not a decision (pending state is cleared so normal
    routing continues).
    """
    pending = (session_data.get("state") or {}).get("duplicate_confirmation")
    if not pending:
        return None
    session_data.setdefault("state", {}).pop("duplicate_confirmation", None)

    object_name = str(pending.get("object") or "")
    fields = dict(pending.get("fields") or {})
    label = str(pending.get("label") or "")
    identifier = pending.get("identifier")
    record_id = pending.get("record_id")

    model = {"Account": Account, "Tenant": Tenant, "Contact": Contact, "Lead": Lead, "Opportunity": Opportunity}.get(object_name)
    text = extract_current_request(user_message).strip().rstrip(".!? ")
    lowered = text.lower()

    # --- Cancel ---------------------------------------------------------
    if lowered in ("cancel", "no", "skip", "stop", "abort", "nevermind", "never mind", "no thanks", "don't", "do not") or lowered.startswith(
        ("cancel ", "no thanks", "nevermind", "never mind")
    ):
        return {"message": "🛑 Cancelled. No new record was created."}

    # --- Use the existing record ----------------------------------------
    looks_like_use = lowered in ("use it", "use", "use the existing", "use existing", "use that", "use this", "yes", "yep", "yeah", "open it", "show it", "show me it")
    looks_like_use = looks_like_use or lowered.startswith(("use ", "yes ", "open it", "show it"))
    if not looks_like_use and identifier is not None:
        looks_like_use = lowered == str(identifier).lower() or lowered == label.lower()
    if looks_like_use:
        try:
            from agents.utils.record_agent.handle_helpers import get_single_record_payload
            _, payload = get_single_record_payload(user, {"object": object_name, "record_id": record_id})
            if payload:
                return {
                    "message": f"{SUCCESS_ICON} Using existing {object_name}: <b>{label}</b>.",
                    "single_record": payload,
                }
        except Exception:
            logger.exception("Failed to load existing record for duplicate confirmation")
        return {"message": f"{SUCCESS_ICON} Using existing {object_name}: <b>{label}</b>."}

    # --- Create a new record (possibly with a modified name) ------------
    new_name = re.sub(
        r"^(create|new|a new one|instead|as|named|called|it|please|yes|use)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip(" ,:;-")
    if not new_name or new_name.lower() == label.lower() or new_name.lower() in ("a new one", "one"):
        if model is not None and "name" in (fields or {}):
            base = str(fields.get("name") or label or f"New {object_name}")
            new_name = _auto_unique_name(model, base)
        else:
            new_name = f"{label} 2"

    if "name" in fields:
        fields["name"] = new_name
    # Email/phone duplicates: don't re-create; treat as use? Keep simple: name-based objects handled above.
    success, message, record_payload = _persist_record(user, object_name, fields)
    if not success:
        return {"message": message or f"⚠️ Could not create the {object_name}."}

    _remember_active_record(session_data, object_name, record_payload)
    response = {"message": f"{SUCCESS_ICON} Created {object_name} '{record_payload['label']}'."}
    try:
        from agents.utils.record_agent.handle_helpers import serialize_record
        from agents.utils.analytics_agent.handle_helpers import get_object_metadata

        created = model.objects.get(pk=record_payload.get("id")) if model else None
        if created is not None:
            metadata = get_object_metadata(object_name) or {}
            response["single_record"] = serialize_record(
                created, object_name, None, metadata.get("custom_fields") or [], user=user
            )
    except Exception:
        logger.exception("Failed to attach created record form after duplicate resolution")
    return response


def _remember_active_record(session_data, object_name, record_payload):
    """Make a freshly created record the session's 'active record' so generic
    follow-ups ('show the lead', 'open it') can open it without re-asking."""
    try:
        from agents.record_agent import _set_active_record

        _set_active_record(
            session_data,
            {
                "object": object_name,
                "record_id": record_payload.get("id") or record_payload.get("record_id"),
                "record_label": object_name,
                "record_value": record_payload.get("label"),
            },
        )
    except Exception:
        pass


def _remember_active_from_response(session_data, response):
    single = (response or {}).get("single_record")
    if isinstance(single, dict):
        _remember_active_record(
            session_data,
            single.get("object"),
            {"id": single.get("record_id"), "label": single.get("record_value")},
        )


def _create_standard_records(user, user_message, session_data):
    # Fast path: "create an activity for account X" — no LLM, ~instant.
    fast_result = _try_fast_activity_create(user, extract_current_request(user_message))
    if fast_result is not None:
        _remember_active_from_response(session_data, fast_result)
        return fast_result

    _refresh_allowed_fields()
    current_state, previous_summary = get_session_context("create_standard_record", session_data)

    llm_result, tokens_used, cost_est = _extract_create_requests(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary,
    )

    if not llm_result:
        return {"message": "⚠️ I couldn’t understand which record you want to create."}

    create_requests = llm_result.get("create_standard_record", [])

    # Fill sensible defaults for Activities so "create an activity for X" works
    # immediately (no clarification loop), then show the editable form.
    for req in create_requests:
        data = req.get("data") or {}
        obj_lower = str(data.get("object") or "").lower()
        if obj_lower == "activity":
            _apply_activity_defaults(user, user_message, data)
            req["completed"] = True
        elif obj_lower == "lead":
            # Deterministic fallback: the extractor often misses the employer in
            # "create lead for company X" — pull it out of the message text.
            _fill_lead_company_from_text(user_message, data)

    completed_requests = [req for req in create_requests if req.get("completed")]
    remaining_requests = [req for req in create_requests if not req.get("completed")]

    session_data.setdefault("state", {})
    session_data["state"]["create_standard_record"] = remaining_requests
    session_data["state"]["summary"] = llm_result.get("summary")

    if not completed_requests:
        return {
            "message": llm_result.get(
                "agent_message",
                "⚠️ I need the object and required details to create the record (e.g., \"Create lead John Doe with email...\")."
            ),
            "session_summary": llm_result.get("summary"),
        }

    # 🔍 Duplicate detector: for a single create request, if a record with the same
    # natural key (name/email/phone) already exists, ask before creating.
    if len(completed_requests) == 1:
        dup_data = completed_requests[0].get("data") or {}
        dup_object = str(dup_data.get("object") or "")
        dup_fields = dict(dup_data.get("fields") or {})
        existing = _check_create_duplicate(dup_object, dup_fields)
        if existing is not None:
            existing["fields"] = dup_fields
            id_display = existing.get("identifier")
            question = (
                f"⚠️ I found an existing {dup_object} named <b>“{existing['label']}”</b>"
                + (f" (id: {id_display})" if id_display else "")
                + ".<br><br>Do you want to <b>use it</b> — reply “use it” — or create a new one? "
                f"I can name it “{existing['label']} 2” if you’d like, or tell me a different name. "
                "Reply “cancel” to skip."
            )
            session_data.setdefault("state", {})
            session_data["state"]["duplicate_confirmation"] = existing
            return {
                "message": question,
                "session_summary": llm_result.get("summary"),
            }

    created_records = []
    errors = []

    grouped_requests = defaultdict(list)
    for req in completed_requests:
        obj_name = (req.get("data") or {}).get("object")
        if obj_name:
            grouped_requests[obj_name].append(req)

    handled_requests = set()

    for obj_name, requests in grouped_requests.items():
        if obj_name in BULK_CREATE_SUPPORTED_OBJECTS and len(requests) >= BULK_CREATE_THRESHOLD:
            bulk_created, bulk_errors = _bulk_create_standard_records(user, obj_name, requests)
            created_records.extend(bulk_created)
            errors.extend(bulk_errors)
            handled_requests.update(id(req) for req in requests)

    for req in completed_requests:
        if id(req) in handled_requests:
            continue
        obj_name = req["data"].get("object")
        fields = req["data"].get("fields") or {}
        success, message, record_payload = _persist_record(user, obj_name, fields)
        if success:
            if obj_name == "Lead":
                _enforce_lead_company_after_create(user_message, record_payload)
            created_records.append(record_payload)
            _remember_active_record(session_data, obj_name, record_payload)
        else:
            errors.append(message)

    message_parts = []
    if created_records:
        success_lines = []
        for item in created_records:
            line = f"{SUCCESS_ICON} Created {item['object']} '{item['label']}'."
            rid = item.get("id") or item.get("record_id")
            obj_name = str(item.get("object") or "")
            if rid and obj_name in ("Lead", "Contact"):
                try:
                    from agents.standard_record_agent import MODEL_MAP
                    rec_model = MODEL_MAP.get(obj_name)
                    rec = rec_model.objects.filter(pk=rid).first() if rec_model else None
                    if rec is not None:
                        present = [f"{k}: {getattr(rec, k)}" for k in ("email", "phone") if getattr(rec, k, None)]
                        missing = [k for k in ("email", "phone") if not getattr(rec, k, None)]
                        if present:
                            line += " " + " · ".join(present)
                        if missing:
                            line += f" ⚠️ (no {', '.join(missing)} saved — reply with the missing value(s) and I'll update the {obj_name.lower()})"
                except Exception:
                    pass
            success_lines.append(line)
        message_parts.append("<br>".join(success_lines))
    if errors:
        message_parts.append("<br>".join(errors))

    response = {
        "message": "<br>".join(message_parts) if message_parts else "",
        "session_summary": llm_result.get("summary"),
        "hiddenMessage": False,
    }

    # If a single Activity was created, attach the editable form so the UI shows it right away.
    if created_records and len(created_records) == 1 and created_records[0].get("object") == "Activity":
        try:
            from agents.utils.record_agent.handle_helpers import serialize_record
            from agents.utils.analytics_agent.handle_helpers import get_object_metadata

            activity = Activity.objects.get(pk=created_records[0].get("id"))
            metadata = get_object_metadata("Activity") or {}
            response["single_record"] = serialize_record(
                activity,
                "Activity",
                None,
                metadata.get("custom_fields") or [],
                user=user,
            )
        except Exception:
            logger.exception("Failed to attach Activity form after create")

    return response


def _bulk_create_standard_records(user, object_name: str, requests: List[dict]) -> Tuple[List[dict], List[str]]:
    created_records: List[dict] = []
    errors: List[str] = []

    build_map = {
        "Lead": _build_bulk_lead_instance,
        "Account": _build_bulk_account_instance,
        "Knowledge": _build_bulk_knowledge_instance,
        "Tenant": _build_bulk_tenant_instance,
    }
    build_fn = build_map.get(object_name)
    if not build_fn:
        for req in requests:
            fields = (req.get("data") or {}).get("fields") or {}
            success, message, record_payload = _persist_record(user, object_name, fields)
            if success:
                created_records.append(record_payload)
            else:
                errors.append(message)
        return created_records, errors

    required_fields = REQUIRED_FIELDS.get(object_name, [])
    custom_map = _get_custom_field_map(object_name)
    instances = []
    instance_fields = []

    for req in requests:
        fields = (req.get("data") or {}).get("fields") or {}
        missing = [f for f in required_fields if not fields.get(f)]
        if missing:
            errors.append(f"⚠️ Missing required fields for {object_name}: {', '.join(missing)}.")
            continue

        instance, error = build_fn(user, fields, custom_map)
        if error:
            errors.append(error)
            continue

        instances.append(instance)
        instance_fields.append((instance, fields))

    if not instances:
        return created_records, errors

    model = instances[0].__class__
    model.objects.bulk_create(instances, batch_size=BULK_CREATE_BATCH_SIZE)

    if object_name in {"Lead", "Account", "Tenant"}:
        id_field = {"Lead": "leadId", "Account": "accid", "Tenant": "tenant_id"}[object_name]
        identifiers = [getattr(instance, id_field, None) for instance in instances if getattr(instance, id_field, None)]
        if identifiers:
            fetched = model.objects.filter(**{f"{id_field}__in": identifiers})
            id_map = {getattr(row, id_field): row for row in fetched}
            for instance in instances:
                identifier = getattr(instance, id_field, None)
                if not identifier:
                    continue
                match = id_map.get(identifier)
                if match:
                    instance.id = match.id

    _bulk_save_custom_fields(instance_fields, object_name, user)

    for instance in instances:
        created_records.append(_record_payload(object_name, instance))

    return created_records, errors


def _bulk_save_custom_fields(records_with_fields: List[Tuple[object, Dict[str, object]]], object_name: str, user):
    if not records_with_fields:
        return
    custom_map = _get_custom_field_map(object_name)
    if not custom_map:
        return

    try:
        ct = ContentType.objects.get_for_model(records_with_fields[0][0].__class__)
    except Exception:
        return

    values = []
    for record, fields in records_with_fields:
        if not getattr(record, "id", None):
            continue
        for key, value in (fields or {}).items():
            cf = custom_map.get(_normalize_key(key))
            if not cf:
                continue
            values.append(
                CustomFieldValue(
                    field=cf,
                    content_type=ct,
                    object_id=record.id,
                    value="" if value is None else str(value),
                    record=None,
                    updated_by_user=user,
                )
            )

    if values:
        CustomFieldValue.objects.bulk_create(values, batch_size=BULK_CREATE_BATCH_SIZE)


def _enforce_lead_company_after_create(user_message: str, record_payload: Dict[str, object]) -> None:
    """Guarantee the employer lands on the Lead when the message says "company X"."""
    try:
        lead_id = (record_payload or {}).get("id")
        if not lead_id:
            return
        lead = Lead.objects.filter(pk=lead_id).first()
        if lead is None or (lead.company or "").strip():
            return
        data = {"object": "Lead", "fields": {}}
        _fill_lead_company_from_text(user_message, data)
        company = (data.get("fields") or {}).get("company")
        if company:
            lead.company = str(company)
            lead.save(update_fields=["company"])
    except Exception:
        logger.debug("post-create lead company enforcement failed", exc_info=True)


def _fill_lead_company_from_text(user_message: str, data: Dict[str, object]) -> None:
    """Set data['fields']['company'] from phrases like "for company Acme Corp"."""
    try:
        fields = data.setdefault("fields", {})  # type: ignore[arg-type]
        if not isinstance(fields, dict):
            return
        if fields.get("company") or fields.get("company_name"):
            return
        from agents.utils.orchestrator.context_handle_helpers import extract_current_request

        text = extract_current_request(user_message) or user_message
        match = re.search(
            r"\b(?:for|at|from|with)\s+(?:the\s+)?(?:company|org(?:anization|anisation)?|employer)\s+"
            r"([^,;]+?)(?=\s*(?:,|;|$|\bcontact\b|\be-?mail\b|\bphone\b|\bmobile\b))",
            text or "",
            re.IGNORECASE,
        )
        if match:
            company = match.group(1).strip(" .")
            if company:
                fields["company"] = company
    except Exception:
        logger.debug("lead company fallback failed", exc_info=True)


def _build_bulk_lead_instance(user, fields: Dict[str, object], custom_map: Dict[str, CustomField]) -> Tuple[Optional[Lead], str]:
    status = fields.get("status")
    if status and status not in dict(Lead.STATUS_CHOICES):
        return None, f"⚠️ Invalid lead status '{status}'. Allowed: {', '.join(dict(Lead.STATUS_CHOICES))}."

    notes = (fields.get("notes") or "").strip()
    extras = []

    def _has_cf(key: str) -> bool:
        return key and key.lower() in custom_map

    # The extraction LLM sometimes reports the employer under company/company_name,
    # but other times under organization/org/account — normalize them all here so
    # the company is actually persisted (and used later at lead conversion).
    _full = f"{fields.get('first_name') or ''} {fields.get('last_name') or ''}".strip().lower()
    _company = ""
    for key in ("company", "company_name", "organization", "org", "account"):
        val = str(fields.get(key) or "").strip()
        if val and val.lower() != _full:
            _company = val
            break
    if _company:
        fields["company"] = _company

    for key in ("company", "company_name"):
        if fields.get(key) and not _has_cf(key):
            extras.append(f"Company: {fields.get(key)}")
            break
    if fields.get("title") and not _has_cf("title"):
        extras.append(f"Title: {fields.get('title')}")
    if extras:
        notes = (notes + ("\n" if notes else "") + "\n".join(extras)).strip()

    lead = Lead(
        first_name=str(fields.get("first_name")),
        last_name=str(fields.get("last_name")),
        email=fields.get("email") or "",
        phone=fields.get("phone") or "",
        leadId=fields.get("leadId") or generate_agentcpq_id(),
        source=fields.get("source") or "",
        company=fields.get("company") or fields.get("company_name") or "",
        title=fields.get("title") or "",
        rating=fields.get("rating") or "warm",
        website=fields.get("website") or None,
        status=status or Lead.STATUS_CHOICES[0][0],
        notes=notes,
        assigned_to=fields.get("assigned_to") or "",
        owner=_resolve_user(fields.get("owner")),
        created_by=user,
    )

    return lead, ""


def _build_bulk_account_instance(user, fields: Dict[str, object], custom_map: Dict[str, CustomField]) -> Tuple[Optional[Account], str]:
    account = Account(
        name=str(fields.get("name")),
        industry=fields.get("industry") or "",
        website=fields.get("website") or None,
        phone=fields.get("phone") or None,
        street=fields.get("street") or None,
        city=fields.get("city") or None,
        state=fields.get("state") or None,
        zip_code=fields.get("zip_code") or None,
        tenant_id=fields.get("tenant_id") or None,
        accid=fields.get("accid") or generate_agentcpq_id(),
        owner=_resolve_user(fields.get("owner")),
        created_by=user,
    )
    return account, ""


def _build_bulk_knowledge_instance(user, fields: Dict[str, object], custom_map: Dict[str, CustomField]) -> Tuple[Optional[Knowledge], str]:
    knowledge = Knowledge(
        title=str(fields.get("title")),
        content_text=str(fields.get("content_text")),
        video_url=fields.get("video_url") or None,
        image_url=fields.get("image_url") or None,
        tags=fields.get("tags") or "",
        language=fields.get("language") or "en",
        created_by=user,
        updated_by=user,
        is_active=_coerce_bool(fields.get("is_active") if fields.get("is_active") is not None else True),
    )
    return knowledge, ""


def _build_bulk_tenant_instance(user, fields: Dict[str, object], custom_map: Dict[str, CustomField]) -> Tuple[Optional[Tenant], str]:
    if not getattr(user, "is_superuser", False):
        return None, "⚠️ Only superusers can create Tenants via chat."
    tenant = Tenant(
        tenant_id=fields.get("tenant_id") or generate_agentcpq_id(),
        name=str(fields.get("name")),
        domain=fields.get("domain") or None,
        contact_email=fields.get("contact_email") or None,
        phone_number=fields.get("phone_number") or None,
        street_address=fields.get("street_address") or None,
        city=fields.get("city") or None,
        state=fields.get("state") or None,
        version=fields.get("version") or Tenant._meta.get_field("version").default,
        plan=fields.get("plan") or Tenant._meta.get_field("plan").default,
    )
    return tenant, ""


def _update_standard_records(user, user_message, session_data):
    _refresh_allowed_fields()
    current_state, previous_summary = get_session_context("update_standard_record", session_data)

    llm_result, _, _ = _extract_update_requests(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary,
    )

    if not llm_result:
        return {"message": "⚠️ I couldn’t understand which record you want to update."}

    update_requests = llm_result.get("update_standard_record", [])
    completed_requests = [req for req in update_requests if req.get("completed")]
    remaining_requests = [req for req in update_requests if not req.get("completed")]

    session_data.setdefault("state", {})
    session_data["state"]["update_standard_record"] = remaining_requests
    session_data["state"]["summary"] = llm_result.get("summary")

    if not completed_requests:
        return {
            "message": llm_result.get(
                "agent_message",
                "⚠️ I need the object, which record to update, and the fields to change.",
            ),
            "session_summary": llm_result.get("summary"),
        }

    updated_records = []
    errors = []

    for req in completed_requests:
        obj_name = (req.get("data") or {}).get("object")
        identifier = (req.get("data") or {}).get("identifier")
        fields = (req.get("data") or {}).get("fields") or {}
        success, message, record_payload = _persist_update(user, obj_name, identifier, fields)
        if success:
            updated_records.append(record_payload)
        else:
            errors.append(message)

    message_parts = []
    if updated_records:
        success_lines = [
            f"{SUCCESS_ICON} Updated {item['object']} '{item['label']}'."
            for item in updated_records
        ]
        message_parts.append("<br>".join(success_lines))
    if errors:
        message_parts.append("<br>".join(errors))

    return {
        "message": "<br>".join(message_parts) if message_parts else "",
        "session_summary": llm_result.get("summary"),
        "hiddenMessage": False,
    }


def _delete_standard_records(user, user_message, session_data):
    # Confirmation phase: a pending delete exists and the user confirmed it.
    pending_delete = session_data.get("pending_delete")
    if isinstance(pending_delete, dict):
        session_data.pop("pending_delete", None)
        deleted = []
        errors = []
        for req in pending_delete.get("requests") or []:
            success, message, payload = _persist_delete(user, req.get("object"), req.get("identifier"))
            if success:
                deleted.append(payload)
            else:
                errors.append(message)

        message_parts = []
        if deleted:
            deleted_lines = [
                f"{SUCCESS_ICON} Deleted {item['object']} '{item['label']}'."
                for item in deleted
            ]
            message_parts.append("<br>".join(deleted_lines))
        if errors:
            message_parts.append("<br>".join(errors))

        return {
            "message": "<br>".join(message_parts) if message_parts else "",
            "hiddenMessage": False,
        }

    # 🧠 Deterministic "delete product <id>" — bypass the LLM here: Product isn't
    # a supported chat object, so the extraction LLM used to guess the type
    # (e.g. 'Option') and then claim the record wasn't found.
    try:
        from agents.utils.orchestrator.context_handle_helpers import extract_current_request
        _raw_msg = (extract_current_request(user_message) or user_message)
    except Exception:
        _raw_msg = user_message
    _lower_msg = str(_raw_msg).strip().lower()
    if re.match(r"^(please\s+)?delete\s+(?:the\s+)?product(?:\s+record)?\b", _lower_msg):
        _m_id = re.search(r"product(?:\s+record)?\s+([0-9A-Za-z_.@-]+)", str(_raw_msg).strip(), re.IGNORECASE)
        _identifier = _m_id.group(1) if _m_id else ""
        if not _identifier:
            return {"message": "⚠️ Which Product do you want to delete? Include its prdid, SKU, or name."}
        _product = _find_product(_identifier)
        if _product is None:
            return {"message": f"⚠️ No Product found matching '{_identifier}' (checked prdid, SKU, and name)."}
        session_data["pending_delete"] = {
            "requests": [{"object": "Product", "identifier": _product.prdid or str(_product.pk)}]
        }
        return {
            "message": (
                f"⚠️ Delete Product '<b>{_product.name}</b>' ({_product.prdid})? This can't be undone. "
                "Reply <strong>yes</strong> to delete or <strong>cancel</strong> to keep it."
            ),
            "session_summary": "User wants to delete a Product; waiting for confirmation.",
            "hiddenMessage": False,
        }

    _refresh_allowed_fields()
    current_state, previous_summary = get_session_context("delete_standard_record", session_data)

    llm_result, _, _ = _extract_delete_requests(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary,
    )

    if not llm_result:
        return {"message": "⚠️ I couldn’t understand which record you want to delete."}

    delete_requests = llm_result.get("delete_standard_record", [])
    completed_requests = [req for req in delete_requests if req.get("completed")]
    remaining_requests = [req for req in delete_requests if not req.get("completed")]

    session_data.setdefault("state", {})
    session_data["state"]["delete_standard_record"] = remaining_requests
    session_data["state"]["summary"] = llm_result.get("summary")

    if not completed_requests:
        return {
            "message": llm_result.get(
                "agent_message",
                "⚠️ I need the object and which record to delete (e.g., id or unique identifier).",
            ),
            "session_summary": llm_result.get("summary"),
        }

    # Destructive operation: ask for confirmation before deleting.
    requests = []
    labels = []
    for req in completed_requests:
        obj_name = (req.get("data") or {}).get("object")
        identifier = (req.get("data") or {}).get("identifier")
        requests.append({"object": obj_name, "identifier": identifier})
        if obj_name == "Product":
            record = _find_product(identifier)
            label = record.name if record is not None else None
        else:
            record = _find_record(obj_name, identifier)
            label = _record_payload(obj_name, record).get("label") if record is not None else None
        labels.append(label or identifier or obj_name)

    session_data["pending_delete"] = {"requests": requests}
    if len(labels) == 1:
        target = f"{requests[0]['object']} '{labels[0]}'"
    else:
        target = f"{len(labels)} records"

    return {
        "message": (
            f"⚠️ Delete {target}? This can't be undone. "
            "Reply <strong>yes</strong> to delete or <strong>cancel</strong> to keep it."
        ),
        "session_summary": llm_result.get("summary"),
        "hiddenMessage": False,
    }


def _extract_create_requests(user_message: str, current_state, previous_summary: Optional[str]):
    _refresh_allowed_fields()

    allowed_fields_prompt = "\n".join(
        [f"   - {obj}: {', '.join(sorted(ALLOWED_FIELDS.get(obj, [])))}" for obj in CREATE_SUPPORTED_OBJECTS]
    )

    system_prompt = f"""
You convert user requests into structured attempts to create standard CRM records.
Return ONLY JSON matching this schema:
{{
  "create_standard_record": [
    {{"data": {{"object": null, "fields": {{}} }}, "completed": false}}
  ],
  "agent_message": "",
  "summary": ""
}}

Rules:
1. Supported objects: {', '.join(CREATE_SUPPORTED_OBJECTS)}. Use singular names.
2. Allowed fields per object:
{allowed_fields_prompt}
3. Required fields:
   - Lead: first_name, last_name
   - Account: name
   - Contact: first_name, email, account
   - Opportunity: name, account
   - Activity: subject, activity_type
   - Contract: opportunity, start_date, contract_status
   - Subscription: quote, quote_line, product, contract, start_date, end_date, price_per_cycle, term (billing_cycle defaults to monthly if omitted)
   - Option: parent_product, product_option
   - Tenant: name
   - Knowledge: title, content_text
4. For Contact/Opportunity, the account value should be the account name or identifier mentioned by the user—do not invent one.
5. For Contract/Subscription/Activity relations (account/opportunity/quote/product/etc.), use the identifier provided by the user (id, custom id, sku, or name). Do not invent.
5. completed=true only when object plus all required fields are present and non-empty.
6. agent_message should ask concisely for whatever is missing. Keep it HTML safe; use <br> for line breaks if needed.
7. summary should extend the prior summary in plain text.
8. No extra keys or text outside the JSON.
"""

    user_prompt = f"""
User message: "{user_message}"

Current state:
{json.dumps(current_state, indent=2)}

Previous summary:
{previous_summary if previous_summary else "None"}

Return only JSON.
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    tokens_used, cost_est = estimate_cost(messages, model=get_model("structured"))
    logger.info("💰 Standard-record LLM estimate → tokens: %s | approx cost: $%.6f", tokens_used, cost_est)

    response = chat_json(
        client,
        model=get_model("structured"),
        messages=messages,
        temperature=0.2,
    )

    raw_response = response.choices[0].message.content.strip()
    logger.info("🔍 Standard-record LLM raw response:\n%s", raw_response)

    cleaned = clean_llm_json(raw_response)
    if cleaned is None:
        logger.error("❌ Unable to parse LLM JSON for create standard record request")
        return None, tokens_used, cost_est

    create_requests = cleaned.get("create_standard_record")
    if not isinstance(create_requests, list):
        cleaned["create_standard_record"] = []
        create_requests = []

    normalized_requests = []
    for item in create_requests:
        data = item.get("data") if isinstance(item, dict) else {}
        obj = _sanitize(data.get("object"))
        fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
        allowed_map = ALLOWED_FIELD_MAP.get(obj, {})
        normalized_fields = {}
        for k, v in fields.items():
            if not isinstance(k, str):
                continue
            canonical = allowed_map.get(k.lower())
            if canonical:
                normalized_fields[canonical] = v

        # Heuristic merge: capture common key/value pairs that the LLM may miss,
        # especially when continuing an incomplete request.
        normalized_fields = _merge_user_message_hints(obj, user_message, normalized_fields)

        required = REQUIRED_FIELDS.get(obj or "", [])
        completed = bool(obj and all(normalized_fields.get(f) not in (None, "", []) for f in required))

        normalized_requests.append(
            {
                "data": {
                    "object": obj,
                    "fields": normalized_fields,
                },
                "completed": completed,
            }
        )

    cleaned["create_standard_record"] = normalized_requests
    return cleaned, tokens_used, cost_est


def _resolve_batch_update_object(line: str) -> Optional[str]:
    normalized_line = _normalize_key(line)
    if not re.search(r"\b(update|edit|change|modify|set)\b", normalized_line):
        return None

    aliases = {
        "Lead": ["lead", "leads"],
        "Account": ["account", "accounts"],
        "Contact": ["contact", "contacts"],
        "Opportunity": ["opportunity", "opportunities", "deal", "deals", "opp", "opps"],
    }

    for object_name in UPDATE_DELETE_SUPPORTED_OBJECTS:
        for alias in aliases.get(object_name, [object_name.lower()]):
            if re.search(rf"\b{re.escape(alias)}\b", normalized_line):
                return object_name
    return None


def _resolve_batch_update_header(raw_header: str, normalized_allowed_map: Dict[str, str]) -> Optional[str]:
    token = _normalize_key(raw_header)
    if token in {"identifier", "record id", "recordid", "id"}:
        return "identifier"
    alias_map = {
        "ext id": "external_id",
        "external id": "external_id",
        "lead id": "leadId",
        "contact id": "contactId",
        "account id": "accid",
        "opportunity id": "oppid",
        "email address": "email",
        "e mail": "email",
    }
    alias_target = alias_map.get(token)
    if alias_target:
        if alias_target in normalized_allowed_map.values():
            return alias_target
    return normalized_allowed_map.get(token)


def _extract_batch_identifier_hint(line: str, normalized_allowed_map: Dict[str, str]) -> Optional[str]:
    normalized_line = _normalize_key(line)
    match = re.search(r"\bby\s+([a-z0-9_ ]+?)(?:\s+(?:for|with|using|where|from)\b|$)", normalized_line)
    if not match:
        return None

    raw_hint = _normalize_key(match.group(1))
    if raw_hint in {"identifier", "record id", "recordid", "id"}:
        return "identifier"

    if raw_hint in normalized_allowed_map:
        return normalized_allowed_map.get(raw_hint)
    return None


def _find_identifier_index_from_hint(
    identifier_hint: Optional[str],
    header_entries: List[Dict[str, Optional[str]]],
) -> Optional[int]:
    if not identifier_hint:
        return None

    normalized_hint = _normalize_key(identifier_hint)
    for idx, entry in enumerate(header_entries):
        resolved = entry.get("resolved")
        raw = _normalize_key(entry.get("raw"))
        if resolved and _normalize_key(resolved) == normalized_hint:
            return idx
        if normalized_hint == "email" and "email" in raw:
            return idx
        if normalized_hint and raw == normalized_hint:
            return idx
    return None


def _parse_batch_update_requests(user_message: str):
    raw_lines = [str(line).rstrip("\r") for line in str(user_message or "").splitlines()]
    if len(raw_lines) < 4:
        return None

    operation_idx = None
    object_name = None
    for idx, line in enumerate(raw_lines):
        resolved = _resolve_batch_update_object(line.strip())
        if resolved:
            operation_idx = idx
            object_name = resolved
            break
        # If we reached likely data rows before detecting an update intent, bail out.
        if idx > 4:
            break

    if operation_idx is None or not object_name:
        return None

    allowed_map = ALLOWED_FIELD_MAP.get(object_name, {})
    if not allowed_map:
        return None

    normalized_allowed_map: Dict[str, str] = {}
    for key, canonical in allowed_map.items():
        normalized_allowed_map[_normalize_key(key)] = canonical
        normalized_allowed_map[_normalize_key(canonical)] = canonical

    identifier_hint = _extract_batch_identifier_hint(raw_lines[operation_idx], normalized_allowed_map)

    payload_lines = raw_lines[operation_idx + 1:]
    marker_idx = None
    for idx, line in enumerate(payload_lines):
        if line.strip() == BATCH_UPDATE_DATA_MARKER:
            marker_idx = idx
            break

    raw_headers: List[str] = []
    data_lines: List[str] = []
    if marker_idx is not None:
        raw_headers = [line.strip() for line in payload_lines[:marker_idx] if line.strip()]
        data_lines = payload_lines[marker_idx + 1:]
    else:
        # Backwards compatibility with older payloads (no marker).
        data_start_idx = 0
        if identifier_hint == "email":
            for idx, line in enumerate(payload_lines):
                candidate = _sanitize(line)
                if candidate and re.search(r"@", str(candidate)):
                    data_start_idx = idx
                    break
            else:
                return None
            raw_headers = [line.strip() for line in payload_lines[:data_start_idx] if line.strip()]
        else:
            headers: List[str] = []
            for idx, line in enumerate(payload_lines):
                stripped_line = line.strip()
                if not stripped_line:
                    continue
                resolved_header = _resolve_batch_update_header(stripped_line, normalized_allowed_map)
                if not resolved_header:
                    if len(headers) >= 2:
                        data_start_idx = idx
                        break
                    return None
                headers.append(resolved_header)
            else:
                data_start_idx = len(payload_lines)
            raw_headers = [line.strip() for line in payload_lines[:data_start_idx] if line.strip()]
        data_lines = payload_lines[data_start_idx:]

    if not raw_headers:
        return None

    header_entries: List[Dict[str, Optional[str]]] = []
    for raw in raw_headers:
        header_entries.append(
            {
                "raw": raw,
                "resolved": _resolve_batch_update_header(raw, normalized_allowed_map),
            }
        )

    resolved_headers = [entry["resolved"] for entry in header_entries]
    known_headers = [header for header in resolved_headers if header]
    if len(known_headers) < 2:
        return None

    if not data_lines:
        return None

    def _find_header_index(header_name: str) -> Optional[int]:
        for idx, candidate in enumerate(resolved_headers):
            if candidate == header_name:
                return idx
        return None

    identifier_index = None
    if "identifier" in resolved_headers:
        identifier_index = _find_header_index("identifier")
    elif identifier_hint:
        identifier_index = _find_identifier_index_from_hint(identifier_hint, header_entries)
    else:
        preferred_identifier_fields = []
        if object_name in {"Lead", "Contact"}:
            preferred_identifier_fields.append("email")
        preferred_identifier_fields.extend(
            [
                _id_field_for_object(object_name),
                "external_id",
                "name",
                "id",
            ]
        )
        for field in preferred_identifier_fields:
            identifier_index = _find_header_index(field)
            if identifier_index is not None:
                break

    if identifier_index is None:
        return None

    row_size = len(header_entries)
    if row_size <= 1:
        return None
    remainder = len(data_lines) % row_size
    if remainder:
        data_lines = data_lines + [""] * (row_size - remainder)

    parsed_requests = []
    for offset in range(0, len(data_lines), row_size):
        row = data_lines[offset: offset + row_size]
        identifier = _sanitize(row[identifier_index] if identifier_index < len(row) else None)
        if identifier_hint == "email":
            # Protect against column drift: ensure identifier is an email.
            if not identifier or "@" not in str(identifier):
                fallback_email = None
                for idx, value in enumerate(row):
                    text_value = _sanitize(value)
                    if text_value and "@" in str(text_value):
                        header_raw = _normalize_key(header_entries[idx].get("raw"))
                        if "email" in header_raw:
                            fallback_email = text_value
                            break
                if fallback_email:
                    identifier = fallback_email

        fields: Dict[str, object] = {}
        for idx, entry in enumerate(header_entries):
            header = entry.get("resolved")
            if not header:
                continue
            if idx == identifier_index or header == "identifier":
                continue
            value = _sanitize(row[idx] if idx < len(row) else None)
            if value is None:
                continue
            fields[header] = value

        if identifier_hint == "email" and (not identifier or "@" not in str(identifier)):
            identifier = None

        completed = bool(object_name and identifier and fields)
        parsed_requests.append(
            {
                "data": {
                    "object": object_name,
                    "identifier": identifier,
                    "fields": fields,
                },
                "completed": completed,
            }
        )

    return parsed_requests if parsed_requests else None


def _extract_update_requests(user_message: str, current_state, previous_summary: Optional[str]):
    _refresh_allowed_fields()

    marker_in_message = BATCH_UPDATE_DATA_MARKER in str(user_message or "")
    batch_requests = _parse_batch_update_requests(user_message)
    if batch_requests:
        object_name = (batch_requests[0].get("data") or {}).get("object") or "records"
        batch_summary = f"Batch update parsed for {object_name} ({len(batch_requests)} rows)."
        summary = previous_summary or ""
        summary = f"{summary}\n{batch_summary}".strip() if summary else batch_summary
        return {
            "update_standard_record": batch_requests,
            "agent_message": "",
            "summary": summary,
        }, 0, 0
    if marker_in_message:
        # Deterministic batch payload was provided; never fall back to LLM guessing.
        return {
            "update_standard_record": [],
            "agent_message": (
                "⚠️ Batch update payload could not be parsed. "
                "Please include the identifier column exactly as requested (for example, email) "
                "and re-upload the CSV."
            ),
            "summary": previous_summary or "",
        }, 0, 0

    allowed_fields_prompt = "\n".join(
        [f"   - {obj}: {', '.join(sorted(ALLOWED_FIELDS.get(obj, [])))}" for obj in UPDATE_DELETE_SUPPORTED_OBJECTS]
    )

    system_prompt = f"""
You convert user requests into structured attempts to update standard CRM records.
Return ONLY JSON matching this schema:
{{
  "update_standard_record": [
    {{"data": {{"object": null, "identifier": null, "fields": {{}} }}, "completed": false}}
  ],
  "agent_message": "",
  "summary": ""
}}

Rules:
1. Supported objects: {', '.join(UPDATE_DELETE_SUPPORTED_OBJECTS)}. Use singular names.
2. Allowed fields per object:
{allowed_fields_prompt}
3. identifier is the value used to find the record (id, accid/leadId/contactId/oppid, email, or name). Do not invent.
4. fields must include ONLY the fields to change. Do not include identifier inside fields.
5. completed=true only when object AND identifier are present AND fields has at least 1 key.
6. agent_message should ask concisely for whatever is missing. Keep it HTML safe; use <br> for line breaks if needed.
7. summary should extend the prior summary in plain text.
8. No extra keys or text outside the JSON.
"""

    user_prompt = f"""
User message: "{user_message}"

Current state:
{json.dumps(current_state, indent=2)}

Previous summary:
{previous_summary if previous_summary else "None"}

Return only JSON.
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    tokens_used, cost_est = estimate_cost(messages, model=get_model("structured"))
    logger.info("💰 Standard-record update LLM estimate → tokens: %s | approx cost: $%.6f", tokens_used, cost_est)

    response = chat_json(
        client,
        model=get_model("structured"),
        messages=messages,
        temperature=0.2,
    )

    raw_response = response.choices[0].message.content.strip()
    logger.info("🔍 Standard-record update LLM raw response:\n%s", raw_response)

    cleaned = clean_llm_json(raw_response)
    if cleaned is None:
        logger.error("❌ Unable to parse LLM JSON for update standard record request")
        return None, tokens_used, cost_est

    update_requests = cleaned.get("update_standard_record")
    if not isinstance(update_requests, list):
        cleaned["update_standard_record"] = []
        update_requests = []

    normalized_requests = []
    for item in update_requests:
        data = item.get("data") if isinstance(item, dict) else {}
        obj = _sanitize(data.get("object"))
        identifier = _sanitize(data.get("identifier"))
        fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
        allowed_map = ALLOWED_FIELD_MAP.get(obj, {})
        normalized_fields = {}
        for k, v in fields.items():
            if not isinstance(k, str):
                continue
            canonical = allowed_map.get(k.lower())
            if canonical:
                normalized_fields[canonical] = v

        completed = bool(obj and identifier and len(normalized_fields) > 0)
        normalized_requests.append(
            {
                "data": {
                    "object": obj,
                    "identifier": identifier,
                    "fields": normalized_fields,
                },
                "completed": completed,
            }
        )

    cleaned["update_standard_record"] = normalized_requests
    return cleaned, tokens_used, cost_est


def _extract_delete_requests(user_message: str, current_state, previous_summary: Optional[str]):
    system_prompt = f"""
You convert user requests into structured attempts to delete standard CRM records.
Return ONLY JSON matching this schema:
{{
  "delete_standard_record": [
    {{"data": {{"object": null, "identifier": null}}, "completed": false}}
  ],
  "agent_message": "",
  "summary": ""
}}

Rules:
1. Supported objects: {', '.join(UPDATE_DELETE_SUPPORTED_OBJECTS)}. Use singular names.
2. identifier is the value used to find the record (id, accid/leadId/contactId/oppid, email, or name). Do not invent.
3. completed=true only when object AND identifier are present.
4. agent_message should ask concisely for whatever is missing. Keep it HTML safe; use <br> for line breaks if needed.
5. summary should extend the prior summary in plain text.
6. No extra keys or text outside the JSON.
"""

    user_prompt = f"""
User message: "{user_message}"

Current state:
{json.dumps(current_state, indent=2)}

Previous summary:
{previous_summary if previous_summary else "None"}

Return only JSON.
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    tokens_used, cost_est = estimate_cost(messages, model=get_model("structured"))
    logger.info("💰 Standard-record delete LLM estimate → tokens: %s | approx cost: $%.6f", tokens_used, cost_est)

    response = chat_json(
        client,
        model=get_model("structured"),
        messages=messages,
        temperature=0.2,
    )

    raw_response = response.choices[0].message.content.strip()
    logger.info("🔍 Standard-record delete LLM raw response:\n%s", raw_response)

    cleaned = clean_llm_json(raw_response)
    if cleaned is None:
        logger.error("❌ Unable to parse LLM JSON for delete standard record request")
        return None, tokens_used, cost_est

    delete_requests = cleaned.get("delete_standard_record")
    if not isinstance(delete_requests, list):
        cleaned["delete_standard_record"] = []
        delete_requests = []

    normalized_requests = []
    for item in delete_requests:
        data = item.get("data") if isinstance(item, dict) else {}
        obj = _sanitize(data.get("object"))
        identifier = _sanitize(data.get("identifier"))
        completed = bool(obj and identifier)
        normalized_requests.append(
            {
                "data": {
                    "object": obj,
                    "identifier": identifier,
                },
                "completed": completed,
            }
        )

    cleaned["delete_standard_record"] = normalized_requests
    return cleaned, tokens_used, cost_est


def _persist_record(user, object_name: str, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    if object_name not in CREATE_SUPPORTED_OBJECTS:
        return False, f"⚠️ Unsupported object '{object_name}'.", {}

    required_missing = [f for f in REQUIRED_FIELDS[object_name] if not fields.get(f)]
    if required_missing:
        return False, f"⚠️ Missing required fields for {object_name}: {', '.join(required_missing)}.", {}

    try:
        if object_name == "Lead":
            success, message, record = _create_lead(user, fields)
        if object_name == "Account":
            success, message, record = _create_account(user, fields)
        if object_name == "Contact":
            success, message, record = _create_contact(user, fields)
        if object_name == "Opportunity":
            success, message, record = _create_opportunity(user, fields)
        if object_name == "Activity":
            success, message, record = _create_activity(user, fields)
        if object_name == "Contract":
            success, message, record = _create_contract(user, fields)
        if object_name == "Subscription":
            success, message, record = _create_subscription(user, fields)
        if object_name == "Option":
            success, message, record = _create_option(user, fields)
        if object_name == "Tenant":
            success, message, record = _create_tenant(user, fields)
        if object_name == "Knowledge":
            success, message, record = _create_knowledge(user, fields)
    except Exception as exc:
        logger.exception("Failed to create %s", object_name)
        return False, f"⚠️ Failed to create {object_name}: {exc}", {}

    if not success:
        return False, message, {}

    _save_custom_fields(record, fields, object_name, user)

    # Optional validation enforcement (only blocks if matching rules exist).
    try:
        target_key = _business_rule_target_key(object_name)
        context = _build_business_rule_context(record, object_name, user=user)
        violations = check_for_validation_rules(target_key, context, rule_type="validation")
        if violations:
            # Clean up custom field values stored via GFK (not a FK cascade).
            try:
                ct = ContentType.objects.get_for_model(record.__class__)
                CustomFieldValue.objects.filter(content_type=ct, object_id=record.id).delete()
            except Exception:
                pass
            try:
                record.delete()
            except Exception:
                pass
            return False, "🚫 Validation failed:<br>" + "<br>".join(violations), {}
    except Exception:
        # Never block creation due to validator errors; keep legacy behavior.
        logger.exception("BusinessRule validation check failed for %s create", object_name)

    return True, message, _record_payload(object_name, record)


def _persist_update(user, object_name: str, identifier: str, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    if object_name not in UPDATE_DELETE_SUPPORTED_OBJECTS:
        return False, f"⚠️ Unsupported object '{object_name}'.", {}
    if not identifier:
        return False, f"⚠️ Missing identifier for {object_name}.", {}
    if not fields:
        return False, f"⚠️ No fields provided to update for {object_name}.", {}

    record = _find_record(object_name, identifier)
    if record is None:
        candidates = _find_record_candidates(object_name, identifier)
        if candidates:
            return (
                False,
                f"⚠️ I found multiple {object_name} matches for '{identifier}'. Please specify a unique id ({_id_field_for_object(object_name)}), numeric id, or email where applicable.<br>{_format_candidates(object_name, candidates)}",
                {},
            )
        return False, f"⚠️ {object_name} '{identifier}' not found.", {}

    if not partner_can_access_record(user, object_name, record, permission="change"):
        return False, f"⚠️ You do not have permission to update this {object_name}.", {}

    try:
        _apply_updates(user, object_name, record, fields)

        # Validate BEFORE saving changes (no rollback needed).
        try:
            target_key = _business_rule_target_key(object_name)
            context = _build_business_rule_context(record, object_name, user=user)
            violations = check_for_validation_rules(target_key, context, rule_type="validation")
            if violations:
                return False, "🚫 Validation failed:<br>" + "<br>".join(violations), {}
        except Exception:
            logger.exception("BusinessRule validation check failed for %s update", object_name)

        record.save()
    except Exception as exc:
        logger.exception("Failed to update %s", object_name)
        return False, f"⚠️ Failed to update {object_name}: {exc}", {}

    _save_custom_fields(record, fields, object_name, user)
    return True, "", _record_payload(object_name, record)


def _find_product(value) -> Optional["Product"]:
    """Resolve a Product by numeric pk, prdid, SKU, external_id, or name."""
    if value is None or str(value).strip() == "":
        return None
    from cpq.models import Product

    raw = str(value).strip()
    try:
        pk_candidate = int(raw)
    except (TypeError, ValueError):
        pk_candidate = None
    if pk_candidate is not None:
        product = Product.objects.filter(pk=pk_candidate).first()
        if product is not None:
            return product
    q = Q()
    for field in ("prdid", "sku", "external_id", "name"):
        q |= Q(**{f"{field}__iexact": raw})
    product = Product.objects.filter(q).first()
    if product is not None:
        return product
    return Product.objects.filter(name__icontains=raw).first()


def _product_delete_error(record) -> Optional[str]:
    """Refuse to delete a Product that anything references (delete cascades)."""
    refs = [
        ("quote line", getattr(record, "quote_lines").count()),
        ("subscription", getattr(record, "subscriptions").count()),
        ("bundle option", getattr(record, "options").count()),
        ("pricing rule", getattr(record, "pricing_rules").count() + getattr(record, "related_rules").count()),
        ("asset", getattr(record, "assets").count()),
        ("pricebook entry", getattr(record, "pricebook_entries").count()),
        ("usage record", getattr(record, "usage_records").count()),
    ]
    used = [(name, n) for name, n in refs if n]
    if not used:
        return None
    detail = ", ".join(f"{n} {name}(s)" for name, n in used)
    return (
        f"⚠️ Can't delete Product '{record.name}' — it's referenced by {detail}. "
        "Delete/archive those records first, or set the product inactive instead."
    )


def _persist_delete(user, object_name: str, identifier: str) -> Tuple[bool, str, Dict[str, object]]:
    if object_name == "Product":
        if not identifier:
            return False, "⚠️ Missing product identifier.", {}
        record = _find_product(identifier)
        if record is None:
            return False, f"⚠️ Product '{identifier}' not found.", {}
        refuse = _product_delete_error(record)
        if refuse:
            return False, refuse, {}
        payload = {"object": "Product", "label": record.name, "id": record.pk}
        try:
            record.delete()
            return True, "", payload
        except Exception as exc:
            return False, f"⚠️ Failed to delete Product: {exc}", {}
    if object_name not in UPDATE_DELETE_SUPPORTED_OBJECTS:
        return False, f"⚠️ Unsupported object '{object_name}'.", {}
    if not identifier:
        return False, f"⚠️ Missing identifier for {object_name}.", {}

    record = _find_record(object_name, identifier)
    if record is None:
        candidates = _find_record_candidates(object_name, identifier)
        if candidates:
            return (
                False,
                f"⚠️ I found multiple {object_name} matches for '{identifier}'. Please specify a unique id ({_id_field_for_object(object_name)}), numeric id, or email where applicable.<br>{_format_candidates(object_name, candidates)}",
                {},
            )
        return False, f"⚠️ {object_name} '{identifier}' not found.", {}

    if not partner_can_access_record(user, object_name, record, permission="delete"):
        return False, f"⚠️ You do not have permission to delete this {object_name}.", {}

    payload = _record_payload(object_name, record)
    try:
        record.delete()
    except Exception as exc:
        logger.exception("Failed to delete %s", object_name)
        return False, f"⚠️ Failed to delete {object_name}: {exc}", {}

    return True, "", payload


# Per-object natural lookup fields, used to resolve a record by identifier.
# Kept consistent with the single-record ("show") lookup so update/delete resolve
# records the same way. All entries are scalar fields (no FKs).
IDENTIFIER_FIELDS: Dict[str, List[str]] = {
    "Lead": ["email", "phone", "leadId", "external_id", "first_name", "last_name"],
    "Account": ["name", "accid", "external_id"],
    "Contact": ["email", "contactId", "external_id", "first_name", "last_name"],
    "Opportunity": ["name", "oppid", "external_id"],
    "Activity": ["subject", "activityid", "external_id"],
    "Contract": ["external_id"],
    "Subscription": ["public_id", "external_id"],
    "Option": ["group_name"],
    "Tenant": ["name", "tenant_id", "domain", "contact_email"],
    "Knowledge": ["title", "tags"],
}


def _id_field_for_object(object_name: str) -> str:
    return {
        "Lead": "leadId",
        "Account": "accid",
        "Contact": "contactId",
        "Opportunity": "oppid",
        "Activity": "activityid",
        "Subscription": "public_id",
        "Tenant": "tenant_id",
    }.get(object_name, "id")


def _find_record(object_name: str, identifier: str):
    candidates = _find_record_candidates(object_name, identifier)
    if len(candidates) == 1:
        return candidates[0]
    return None


def _find_record_candidates(object_name: str, identifier: str) -> List[object]:
    if not identifier:
        return []
    raw = str(identifier).strip()
    model = MODEL_MAP.get(object_name)
    if not model:
        return []

    qs = model.objects.all()

    # 1) Numeric PK
    try:
        return list(qs.filter(pk=int(raw))[:5])
    except Exception:
        pass

    lookup_fields = IDENTIFIER_FIELDS.get(object_name, [])

    # ⚠️ ID-like fields must win over display fields: a record whose *name* happens
    # to equal an id (junk row) must never shadow the record with that actual id.
    id_like = [f for f in lookup_fields if f.lower().endswith("id") or f in {"sku", "public_id"}]
    ordered_fields = id_like + [f for f in lookup_fields if f not in id_like]

    # 2) Exact (case-insensitive) matches on natural identifier fields
    for field in ordered_fields:
        try:
            found = list(qs.filter(**{f"{field}__iexact": raw})[:5])
        except Exception:
            continue
        if found:
            return found

    # 3) Partial (icontains) matches
    for field in ordered_fields:
        try:
            found = list(qs.filter(**{f"{field}__icontains": raw})[:5])
        except Exception:
            continue
        if found:
            return found

    # 4) Lead phone digit normalization
    if object_name == "Lead":
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits:
            try:
                found = list(qs.filter(phone__icontains=digits)[:5])
                if found:
                    return found
            except Exception:
                pass

    # 5) Lead full-name search (first + last split)
    if object_name == "Lead":
        try:
            parts = raw.split()
            if len(parts) >= 2:
                return list(qs.filter(first_name__iexact=parts[0], last_name__iexact=" ".join(parts[1:]))[:5])
        except Exception:
            pass

    return []


def _format_candidates(object_name: str, candidates: List[object]) -> str:
    lines = []
    id_field = _id_field_for_object(object_name)
    for c in candidates[:5]:
        label = getattr(c, "name", None) or getattr(c, "email", None) or str(c)
        uid = getattr(c, id_field, None) or getattr(c, "id", None)
        lines.append(f"- {label} ({id_field}: {uid})")
    return "Matches:<br>" + "<br>".join(lines)


def _normalize_opportunity_stage_value(raw_stage, stage_choices, default_stage=None):
    stage_value = raw_stage if raw_stage not in (None, "") else default_stage
    if stage_value in (None, ""):
        return stage_value

    normalized = re.sub(r"[^a-z0-9]+", "", str(stage_value).strip().lower())

    key_map = {}
    label_map = {}
    for key, label in (stage_choices or []):
        key_norm = re.sub(r"[^a-z0-9]+", "", str(key).strip().lower())
        label_norm = re.sub(r"[^a-z0-9]+", "", str(label).strip().lower())
        key_map[key_norm] = key
        label_map[label_norm] = key

    alias_map = {
        "qualification": "qualifiedtobuy",
        "qualified": "qualifiedtobuy",
        "qualify": "qualifiedtobuy",
        "qualifiedbuy": "qualifiedtobuy",
        "qualifiedtobuy": "qualifiedtobuy",
    }

    if normalized in key_map:
        return key_map[normalized]
    if normalized in label_map:
        return label_map[normalized]
    if normalized in alias_map:
        alias_key = alias_map[normalized]
        alias_norm = re.sub(r"[^a-z0-9]+", "", alias_key.lower())
        if not key_map or alias_norm in key_map:
            return alias_key
    return stage_value


def _apply_updates(user, object_name: str, record, fields: Dict[str, object]) -> None:
    blocked_fields = {
        "id",
        "pk",
        "created_at",
        "updated_at",
        "created_by",
        "accid",
        "leadId",
        "contactId",
        "oppid",
    }
    if object_name == "Opportunity" and "stage" in fields:
        from cpq.models import picklist_choices, picklist_default_key
        stage_choices = picklist_choices("Opportunity", "stage")
        stage_value = _normalize_opportunity_stage_value(
            fields.get("stage"),
            stage_choices,
            picklist_default_key("Opportunity", "stage"),
        )
        valid_stages = [choice[0] for choice in stage_choices] if stage_choices else []
        if stage_value and valid_stages and stage_value not in valid_stages:
            raise ValueError(f"Invalid stage '{stage_value}'. Allowed: {', '.join(valid_stages)}.")
        fields["stage"] = stage_value

    for key, value in fields.items():
        if key in blocked_fields:
            continue
        if key == "account" and object_name in {"Contact", "Opportunity"}:
            account_ref = _find_account(value)
            if not account_ref:
                if object_name == "Opportunity":
                    account_ref = Account.objects.create(name=str(value), created_by=user)
                else:
                    raise ValueError(f"Account '{value}' not found.")
            setattr(record, "account", account_ref)
            continue

        if key == "owner":
            if hasattr(record, "owner"):
                setattr(record, "owner", _resolve_user(value))
            continue

        if key == "amount" and object_name == "Opportunity":
            setattr(record, "amount", _coerce_decimal(value))
            continue

        if key == "expected_close_date" and object_name == "Opportunity":
            setattr(record, "expected_close_date", _coerce_date(value))
            continue

        if key == "is_primary" and object_name == "Contact":
            setattr(record, "is_primary", _coerce_bool(value))
            continue

        # Default: set model field if it exists; otherwise treat as custom field.
        try:
            record._meta.get_field(key)
        except Exception:
            continue

        field_obj = record._meta.get_field(key)
        if not getattr(field_obj, "editable", True):
            continue

        # ForeignKey: resolve the related record by identifier (id / name / SKU / ...).
        if isinstance(field_obj, ForeignKey):
            if value in (None, ""):
                if getattr(field_obj, "null", False):
                    setattr(record, key, None)
                continue
            related = _resolve_related_instance(field_obj.related_model, value)
            if related is None:
                raise ValueError(f"Related record for '{key}' not found with value '{value}'.")
            setattr(record, key, related)
            continue

        if field_obj.get_internal_type() in {"DecimalField"}:
            setattr(record, key, _coerce_decimal(value))
            continue
        if field_obj.get_internal_type() in {"DateField"}:
            setattr(record, key, _coerce_date(value))
            continue
        if field_obj.get_internal_type() in {"BooleanField"}:
            setattr(record, key, _coerce_bool(value))
            continue

        setattr(record, key, "" if value is None else value)


def _create_lead(user, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    status = fields.get("status")
    if status and status not in dict(Lead.STATUS_CHOICES):
        return False, f"⚠️ Invalid lead status '{status}'. Allowed: {', '.join(dict(Lead.STATUS_CHOICES))}.", {}

    # Capture optional company/title into notes only when no matching custom field exists
    notes = (fields.get("notes") or "").strip()
    extras = []
    custom_map = _get_custom_field_map("Lead")
    def _has_cf(key):
        return key and key.lower() in custom_map

    for key in ("company", "company_name"):
        if fields.get(key) and not _has_cf(key):
            extras.append(f"Company: {fields.get(key)}")
            break
    if fields.get("title") and not _has_cf("title"):
        extras.append(f"Title: {fields.get('title')}")
    if extras:
        notes = (notes + ("\n" if notes else "") + "\n".join(extras)).strip()

    lead = Lead.objects.create(
        first_name=str(fields.get("first_name")),
        last_name=str(fields.get("last_name")),
        email=fields.get("email") or "",
        phone=fields.get("phone") or "",
        source=fields.get("source") or "",
        status=status or Lead.STATUS_CHOICES[0][0],
        notes=notes,
        assigned_to=fields.get("assigned_to") or "",
        owner=_resolve_user(fields.get("owner")),
        created_by=user,
    )

    return True, "", lead


def _create_account(user, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    account = Account.objects.create(
        name=str(fields.get("name")),
        industry=fields.get("industry") or "",
        website=fields.get("website") or None,
        phone=fields.get("phone") or None,
        street=fields.get("street") or None,
        city=fields.get("city") or None,
        state=fields.get("state") or None,
        zip_code=fields.get("zip_code") or None,
        tenant_id=fields.get("tenant_id") or None,
        owner=_resolve_user(fields.get("owner")),
        created_by=user,
    )

    return True, "", account


def _create_contact(user, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    account_ref = _find_account(fields.get("account"))
    if not account_ref:
        return False, f"⚠️ Account '{fields.get('account')}' not found for Contact.", {}

    contact = Contact.objects.create(
        first_name=str(fields.get("first_name")),
        last_name=str(fields.get("last_name") or ""),
        email=str(fields.get("email")),
        phone=fields.get("phone") or "",
        company=fields.get("company") or "",
        job_title=fields.get("job_title") or "",
        notes=fields.get("notes") or "",
        account=account_ref,
        is_primary=_coerce_bool(fields.get("is_primary")),
        created_by=user,
    )

    return True, "", contact


def _create_opportunity(user, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    account_ref = _find_account(fields.get("account"))
    if not account_ref:
        try:
            account_ref = Account.objects.create(
                name=str(fields.get("account")),
                created_by=user,
            )
        except Exception:
            return False, f"⚠️ Account '{fields.get('account')}' not found for Opportunity.", {}

    from cpq.models import picklist_choices, picklist_default_key
    stage_choices = picklist_choices("Opportunity", "stage")
    stage_value = _normalize_opportunity_stage_value(
        fields.get("stage"),
        stage_choices,
        picklist_default_key("Opportunity", "stage"),
    )
    valid_stages = [choice[0] for choice in stage_choices] if stage_choices else []
    if stage_value not in valid_stages:
        return False, f"⚠️ Invalid stage '{stage_value}'. Allowed: {', '.join(valid_stages)}.", {}

    expected_close_date = (
        _coerce_date(fields.get("expected_close_date"))
        or default_opportunity_expected_close_date()
    )

    opportunity = Opportunity.objects.create(
        name=str(fields.get("name")),
        account=account_ref,
        amount=_coerce_decimal(fields.get("amount")),
        stage=stage_value,
        expected_close_date=expected_close_date,
        owner=_resolve_user(fields.get("owner")),
        created_by=user,
    )

    return True, "", opportunity


def _record_payload(object_name: str, record) -> Dict[str, object]:
    name_parts = []
    if getattr(record, "first_name", None):
        name_parts.append(str(record.first_name))
    if getattr(record, "last_name", None):
        name_parts.append(str(record.last_name))
    combined_name = " ".join([p for p in name_parts if p])

    return {
        "object": object_name,
        "id": getattr(record, "id", None),
        "label": getattr(record, "name", None)
        or combined_name
        or getattr(record, "email", None)
        or getattr(record, "first_name", None)
        or str(record),
    }


def _create_activity(user, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    activity_type = fields.get("activity_type")
    if activity_type and activity_type not in dict(Activity.ACTIVITY_TYPE_CHOICES):
        return (
            False,
            f"⚠️ Invalid activity_type '{activity_type}'. Allowed: {', '.join(dict(Activity.ACTIVITY_TYPE_CHOICES))}.",
            {},
        )

    status = fields.get("status")
    if status and status not in dict(Activity.STATUS_CHOICES):
        return (
            False,
            f"⚠️ Invalid status '{status}'. Allowed: {', '.join(dict(Activity.STATUS_CHOICES))}.",
            {},
        )

    lead_ref = _find_lead(fields.get("lead")) if fields.get("lead") else None
    opp_ref = _find_opportunity(fields.get("opportunity")) if fields.get("opportunity") else None
    contact_ref = _find_contact(fields.get("contact")) if fields.get("contact") else None

    if fields.get("lead") and not lead_ref:
        return False, f"⚠️ Lead '{fields.get('lead')}' not found for Activity.", {}
    if fields.get("opportunity") and not opp_ref:
        return False, f"⚠️ Opportunity '{fields.get('opportunity')}' not found for Activity.", {}
    if fields.get("contact") and not contact_ref:
        return False, f"⚠️ Contact '{fields.get('contact')}' not found for Activity.", {}

    activity = Activity.objects.create(
        subject=str(fields.get("subject")),
        activity_type=activity_type or Activity.ACTIVITY_TYPE_CHOICES[0][0],
        status=status or Activity.STATUS_CHOICES[0][0],
        due_date=_coerce_date(fields.get("due_date")),
        lead=lead_ref,
        opportunity=opp_ref,
        contact=contact_ref,
        notes=fields.get("notes") or "",
        created_by=user,
    )

    return True, "", activity


def _create_contract(user, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    opp_value = fields.get("opportunity")
    opportunity_ref = _find_opportunity(opp_value)
    if not opportunity_ref:
        # Safe fallback: if the user provided both Account + Opportunity names, create them.
        account_value = (
            fields.get("account")
            or fields.get("account__c")
            or fields.get("Account")
            or fields.get("tenant__c")
        )
        if account_value and opp_value:
            success, message, opportunity_ref = _create_opportunity(
                user,
                {
                    "name": str(opp_value),
                    "account": str(account_value),
                },
            )
            if not success:
                return False, message or f"⚠️ Opportunity '{opp_value}' not found for Contract.", {}
        else:
            return False, f"⚠️ Opportunity '{opp_value}' not found for Contract.", {}

    status = fields.get("contract_status") or fields.get("status")
    if isinstance(status, str):
        status = status.strip()
        if status:
            status = status[:1].upper() + status[1:].lower()
    if status and status not in {"Active", "Expired", "Renewed"}:
        return False, "⚠️ Invalid contract_status. Allowed: Active, Expired, Renewed.", {}

    start_date = _coerce_date(fields.get("start_date"))
    if not start_date:
        return False, "⚠️ Please provide a valid start_date (YYYY-MM-DD).", {}

    contract = Contract.objects.create(
        opportunity=opportunity_ref,
        start_date=start_date,
        end_date=_coerce_date(fields.get("end_date")),
        contract_status=status or "Active",
    )

    return True, "", contract


def _create_subscription(user, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    quote_ref = _find_quote(fields.get("quote"))
    if not quote_ref:
        return False, f"⚠️ Quote '{fields.get('quote')}' not found for Subscription.", {}

    quote_line_ref = _find_quote_line(fields.get("quote_line"))
    if not quote_line_ref:
        return False, f"⚠️ QuoteLine '{fields.get('quote_line')}' not found for Subscription.", {}

    product_ref = _find_product(fields.get("product"))
    if not product_ref:
        return False, f"⚠️ Product '{fields.get('product')}' not found for Subscription.", {}

    contract_ref = _find_contract(fields.get("contract"))
    if not contract_ref:
        return False, f"⚠️ Contract '{fields.get('contract')}' not found for Subscription.", {}

    billing_cycle = fields.get("billing_cycle") or fields.get("billing_frequency") or "monthly"
    allowed_cycles = {"monthly", "quarterly", "annual", "one_time"}
    if billing_cycle not in allowed_cycles:
        return False, f"⚠️ Invalid billing_cycle '{billing_cycle}'. Allowed: {', '.join(sorted(allowed_cycles))}.", {}

    subscription = Subscription.objects.create(
        quote=quote_ref,
        quote_line=quote_line_ref,
        product=product_ref,
        contract=contract_ref,
        start_date=_coerce_date(fields.get("start_date")),
        end_date=_coerce_date(fields.get("end_date")),
        billing_cycle=billing_cycle,
        price_per_cycle=_coerce_decimal(fields.get("price_per_cycle")),
        term=int(fields.get("term")),
    )

    return True, "", subscription


def _create_option(user, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    parent_product = _find_product(fields.get("parent_product"))
    if not parent_product:
        return False, f"⚠️ Parent product '{fields.get('parent_product')}' not found.", {}

    product_option = _find_product(fields.get("product_option"))
    if not product_option:
        return False, f"⚠️ Product option '{fields.get('product_option')}' not found.", {}

    option = Option.objects.create(
        parent_product=parent_product,
        product_option=product_option,
        quantity=int(fields.get("quantity") or 1),
        is_required=_coerce_bool(fields.get("is_required")),
        min_quantity=int(fields.get("min_quantity") or 1),
        max_quantity=int(fields.get("max_quantity") or 10),
        default_selected=_coerce_bool(fields.get("default_selected") if fields.get("default_selected") is not None else True),
        group_name=fields.get("group_name") or None,
    )

    return True, "", option


def _create_tenant(user, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    # Extra safety: tenant creation is superuser-only.
    if not getattr(user, "is_superuser", False):
        return False, "⚠️ Only superusers can create Tenants via chat.", {}

    tenant = Tenant.objects.create(
        name=str(fields.get("name")),
        domain=fields.get("domain") or None,
        contact_email=fields.get("contact_email") or None,
        phone_number=fields.get("phone_number") or None,
        street_address=fields.get("street_address") or None,
        city=fields.get("city") or None,
        state=fields.get("state") or None,
        version=fields.get("version") or Tenant._meta.get_field("version").default,
        plan=fields.get("plan") or Tenant._meta.get_field("plan").default,
    )

    return True, "", tenant


def _create_knowledge(user, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    knowledge = Knowledge.objects.create(
        title=str(fields.get("title")),
        content_text=str(fields.get("content_text")),
        video_url=fields.get("video_url") or None,
        image_url=fields.get("image_url") or None,
        tags=fields.get("tags") or "",
        language=fields.get("language") or "en",
        created_by=user,
        updated_by=user,
        is_active=_coerce_bool(fields.get("is_active") if fields.get("is_active") is not None else True),
    )

    return True, "", knowledge


def _merge_user_message_hints(object_name: str, user_message: str, fields: Dict[str, object]) -> Dict[str, object]:
    if not object_name or not user_message:
        return fields

    merged = dict(fields or {})
    text = str(user_message)

    def _extract_date(label: str) -> Optional[str]:
        # Accept "Start Date = 2025-07-07" / "Start Date: 2025-07-07" / "start_date 2025-07-07"
        match = re.search(rf"(?i)\\b{re.escape(label)}\\b\\s*[:=]?\\s*(\\d{{4}}-\\d{{2}}-\\d{{2}})", text)
        return match.group(1) if match else None

    def _extract_value(label: str) -> Optional[str]:
        match = re.search(rf"(?i)\\b{re.escape(label)}\\b\\s*[:=]\\s*([^\\n\\r]+)", text)
        return match.group(1).strip() if match else None

    if object_name == "Contract":
        if not merged.get("start_date"):
            start = _extract_date("Start Date") or _extract_date("start_date")
            if start:
                merged["start_date"] = start
        if not merged.get("end_date"):
            end = _extract_date("End Date") or _extract_date("end_date")
            if end:
                merged["end_date"] = end
        if not merged.get("contract_status"):
            status = _extract_value("Status") or _extract_value("contract_status")
            if status:
                merged["contract_status"] = status
        if not merged.get("opportunity"):
            opp = _extract_value("Opportunity")
            if opp:
                merged["opportunity"] = opp
        if not (merged.get("account") or merged.get("account__c")):
            acct = _extract_value("Account")
            if acct:
                merged["account__c"] = acct

    return merged

def _normalize_key(key: str) -> str:
    if key is None:
        return ""
    return re.sub(r"\s+", " ", str(key).replace("_", " ").strip().lower())


def _get_custom_field_map(object_name: str) -> Dict[str, CustomField]:
    try:
        qs = CustomField.objects.filter(custom_object__isnull=True, object_type=object_name)
        mapping: Dict[str, CustomField] = {}
        for cf in qs:
            for variant in [cf.name, cf.label]:
                if not variant:
                    continue
                normalized = _normalize_key(variant)
                mapping[normalized] = cf
        return mapping
    except Exception:
        return {}


def _save_custom_fields(record, fields: Dict[str, object], object_name: str, user):
    if not record or not fields:
        return
    custom_map = _get_custom_field_map(object_name)
    if not custom_map:
        return

    try:
        ct = ContentType.objects.get_for_model(record.__class__)
    except Exception:
        return

    for key, value in fields.items():
        cf = custom_map.get(_normalize_key(key))
        if not cf:
            continue
        try:
            CustomFieldValue.objects.update_or_create(
                field=cf,
                content_type=ct,
                object_id=record.id,
                defaults={
                    "value": "" if value is None else str(value),
                    "record": None,
                    "updated_by_user": user,
                },
            )
        except Exception:
            logger.exception("Failed to save custom field %s for %s", key, object_name)


def _find_lead(value) -> Optional[Lead]:
    if not value:
        return None
    candidates = _find_record_candidates("Lead", value)
    return candidates[0] if candidates else None


def _find_contact(value) -> Optional[Contact]:
    if not value:
        return None
    candidates = _find_record_candidates("Contact", value)
    return candidates[0] if candidates else None


def _find_opportunity(value) -> Optional[Opportunity]:
    if not value:
        return None
    candidates = _find_record_candidates("Opportunity", value)
    return candidates[0] if candidates else None


def _find_account(value) -> Optional[Account]:
    if not value:
        return None
    try:
        value = str(value).strip()
    except Exception:
        pass

    try:
        return Account.objects.get(pk=value)
    except Exception:
        pass

    try:
        return Account.objects.filter(accid=str(value)).first()
    except Exception:
        pass

    try:
        return Account.objects.filter(external_id=str(value)).first()
    except Exception:
        pass

    try:
        return Account.objects.filter(name__iexact=str(value)).first()
    except Exception:
        pass

    try:
        return Account.objects.filter(name__icontains=str(value)).first()
    except Exception:
        return None


def _resolve_related_instance(related_model, value):
    """Resolve a related model instance by identifier (numeric id, name, SKU, etc.)."""
    if value in (None, ""):
        return None
    raw = str(value).strip()

    # 1) Numeric primary key
    try:
        return related_model.objects.get(pk=int(raw))
    except Exception:
        pass

    # 2) Natural identifier fields (case-insensitive exact match)
    for field in (
        "name",
        "sku",
        "external_id",
        "subject",
        "title",
        "email",
        "phone",
        "username",
        "custom_identifier",
        "prdid",
        "qteid",
        "public_id",
        "accid",
        "leadId",
        "contactId",
        "oppid",
    ):
        if not hasattr(related_model, field):
            continue
        try:
            found = related_model.objects.filter(**{f"{field}__iexact": raw}).first()
        except Exception:
            continue
        if found:
            return found

    return None


def _find_quote(value) -> Optional[Quote]:
    return _resolve_related_instance(Quote, value) if value else None


def _find_quote_line(value) -> Optional[QuoteLine]:
    return _resolve_related_instance(QuoteLine, value) if value else None


def _find_product(value) -> Optional[Product]:
    return _resolve_related_instance(Product, value) if value else None


def _find_contract(value) -> Optional[Contract]:
    return _resolve_related_instance(Contract, value) if value else None


def _resolve_user(value) -> Optional[User]:
    if not value:
        return None
    try:
        return User.objects.filter(username__iexact=str(value)).first()
    except Exception:
        return None


def _coerce_decimal(value) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _coerce_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        parsed = parse_date(str(value))
        return parsed
    except Exception:
        return None


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "y"}:
            return True
    return False


def _sanitize(value):
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value
