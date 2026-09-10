import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction

from cpq.models import Quote
from .utils.analytics_agent.handle_helpers import get_object_metadata
from .utils.admin_agent.rules_helpers import check_for_validation_rules
from .utils.record_agent.llm_helpers import extract_single_record_request
from .utils.record_agent.handle_helpers import (
    get_single_record_payload,
    serialize_record,
    update_record_field,
)
from cpq.permissions import partner_can_access_record
from .utils.quote_agent.general_helpers import set_active_quote_to_session_data
from .utils.session_context_helpers.session_context_helpers import get_session_context

logger = logging.getLogger(__name__)

_ACTIVE_RECORD_OBJECTS = {
    "account",
    "opportunity",
    "lead",
    "contact",
    "activity",
    "quote",
    "product",
    "contract",
    "subscription",
    "option",
    "tenant",
    "knowledge",
}

_ACTIVE_OBJECT_ALIASES = {
    "lead": "Lead",
    "account": "Account",
    "opportunity": "Opportunity",
    "opp": "Opportunity",
    "contact": "Contact",
    "activity": "Activity",
    "quote": "Quote",
    "product": "Product",
    "contract": "Contract",
    "subscription": "Subscription",
    "option": "Option",
    "tenant": "Tenant",
    "knowledge": "Knowledge",
}


def _try_active_record_reference(user, user_message, session_data):
    """Resolve generic follow-ups like 'show the lead' / 'open it' to the record that
    was most recently created or opened in this session (no LLM round-trip)."""
    from .utils.orchestrator.context_handle_helpers import extract_current_request

    text = (extract_current_request(user_message) or "").strip().rstrip(".!? ")
    lowered = re.sub(r"\s+", " ", text.lower())

    if lowered in ("show it", "open it", "view it", "show it again", "open it again", "show that", "open that", "show the record", "open the record"):
        active = session_data.get("active_record")
        if active and active.get("record_id"):
            return {"object": active["object"], "record_id": active["record_id"]}
        return None

    match = re.match(
        r"^(?:can\s+you\s+)?(?:show|display|open|get|give|view|see)\s+(?:me\s+)?(?:the\s+)?"
        r"(?:new\s+|latest\s+|current\s+)?(lead|account|opportunity|opp|contact|activity|quote|product|contract|subscription|option|tenant|knowledge)s?"
        r"(?:\s+(?:that|which|i|we|you|the)\s+(?:just\s+)?(?:created|opened|updated))?\s*$",
        lowered,
    )
    if not match:
        return None

    object_name = _ACTIVE_OBJECT_ALIASES[match.group(1)]
    object_key = object_name.lower()
    active = session_data.get("active_records", {}).get(object_key)
    if not active or not active.get("record_id"):
        return None
    return {"object": active["object"], "record_id": active["record_id"]}


def _set_active_record(session_data, record_payload):
    object_name = str(record_payload.get("object", "")).strip()
    record_id = record_payload.get("record_id")
    if not object_name or not record_id:
        return

    object_key = object_name.lower()
    if object_key not in _ACTIVE_RECORD_OBJECTS:
        return

    active_payload = {
        "object": object_name,
        "record_id": record_id,
        "record_label": record_payload.get("record_label"),
        "record_value": record_payload.get("record_value"),
    }

    session_data["active_record"] = active_payload
    session_data.setdefault("active_records", {})
    session_data["active_records"][object_key] = active_payload

    if active_payload.get("record_value"):
        session_data[object_key] = active_payload["record_value"]


def _get_active_record_request(session_data, show_requests):
    target_object = None
    if show_requests:
        data = show_requests[0].get("data") if isinstance(show_requests[0], dict) else None
        if isinstance(data, dict):
            target_object = data.get("object")

    if not target_object:
        return None

    object_key = str(target_object).lower()
    active_by_object = session_data.get("active_records", {}).get(object_key)
    if active_by_object:
        return {"object": active_by_object["object"], "record_id": active_by_object["record_id"]}

    return None


def record_agent(user, action, user_message, session_data):
    action_map = {
        "ShowSingleRecord": show_single_record,
        "UpdateSingleRecordFromUI": update_single_record_from_ui,
        "ShowRecordSummary": show_record_summary,
        "ShowRecordActivities": show_record_activities,
    }

    handler = action_map.get(action)
    if handler:
        return handler(user, user_message, session_data)

    logger.warning("record_agent received unsupported action '%s'", action)
    return {"message": "🤖 Sorry, I couldn’t understand your request."}


_FAST_OBJECT_NAMES = [
    "Opportunity",
    "Account",
    "Contact",
    "Lead",
    "Activity",
    "Quote",
    "QuoteLine",
    "Product",
    "Contract",
    "Subscription",
    "Option",
    "Tenant",
    "Knowledge",
]


def _try_fast_single_record_request(user_message: str) -> Optional[Dict[str, str]]:
    """Deterministically parse '<Object> <identifier>' from related-records messages."""
    match = re.match(
        r"^(?:show|display|view)?\s*related\s+records?\s+for\s+(.+)$",
        user_message.strip(),
        re.IGNORECASE,
    )
    if not match:
        return None
    rest = match.group(1).strip()
    for obj_name in _FAST_OBJECT_NAMES:
        obj_match = re.search(rf"\b{re.escape(obj_name)}\b", rest, re.IGNORECASE)
        if obj_match:
            identifier = (rest[: obj_match.start()] + " " + rest[obj_match.end() :]).strip(" ,:-")
            return {"object": obj_name, "identifier": identifier}
    return None


# Friendly identifier (ID) field per standard object, as serialized in the payload.
_FRIENDLY_ID_FIELDS = {
    "Account": "accid",
    "Opportunity": "oppid",
    "Contact": "contactId",
    "Lead": "leadId",
    "Quote": "qteid",
    "Product": "prdid",
    "Activity": "activityid",
    "Tenant": "tenant_id",
}

# Preferred extra fields per standard object (serialized field names), in display order.
_RECORD_SUMMARY_FIELDS = {
    "Account": ["industry", "phone", "website", "city"],
    "Opportunity": ["account", "amount", "expected_close_date", "stage"],
    "Contact": ["first_name", "last_name", "email", "phone", "account", "company", "job_title"],
    "Lead": ["first_name", "last_name", "email", "phone", "source", "status"],
    "Quote": ["account", "opportunity", "net_amount", "status", "expiration_date"],
    "Activity": ["activity_type", "status", "due_date", "opportunity", "contact"],
    "Product": ["sku", "price", "family", "is_active"],
    "Tenant": ["domain", "contact_email", "phone_number", "plan"],
    "Contract": ["opportunity", "contract_status", "start_date", "end_date"],
    "Subscription": ["product", "contract", "quote", "price_per_cycle", "start_date", "end_date"],
    "Option": ["group_name", "parent_product", "product_option"],
    "Knowledge": ["title", "tags"],
}

# Fields never surfaced in the compact summary (system/lookup noise, long text).
_SYSTEM_SKIP_FIELDS = {
    "id", "external_id", "created_at", "updated_at", "created_by", "updated_by",
    "last_synced_at", "public_id", "notes", "notes__c", "description", "api_key",
    "api_secret", "logo", "synced", "hs_primary", "hs_deal_id", "hs_deal",
    "quickbooks_invoice_id", "sf_opportunity_id", "owner", "tenant_id",
}
_CURRENCY_FIELDS = {"amount", "net_amount", "price", "subtotal", "total_price", "discount_amount", "fixed_price"}
_DATE_FIELDS = {"expected_close_date", "due_date", "created_at", "updated_at", "expiration_date",
                "start_date", "end_date", "target_decision_date__c", "baseline__c"}
_MAX_SUMMARY_LINES = 5  # friendly ID + up to 4 key fields


def _format_summary_value(field_name: str, raw: str) -> str:
    raw = str(raw or "")
    if not raw or raw in ("None", "—", ""):
        return ""
    lower_name = field_name.lower()
    if lower_name in _CURRENCY_FIELDS or any(t in lower_name for t in ("amount", "price", "cost", "revenue", "fee", "total", "arr", "mrr", "value")):
        try:
            n = float(raw)
            return "${:,.0f}".format(n) if n.is_integer() else "${:,.2f}".format(n)
        except (TypeError, ValueError):
            return raw
    if lower_name in _DATE_FIELDS or "_date" in lower_name or "close" in lower_name:
        # The serialized value is typically YYYY-MM-DD or ISO; shorten to a friendly date.
        import datetime as _dt

        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                d = _dt.datetime.strptime(raw[:19], fmt)
                return d.strftime("%b %d, %Y")
            except (ValueError, TypeError):
                continue
        return raw
    return raw


def _summary_field_value(field) -> object:
    raw = field.get("display_value")
    if raw in (None, "", "—"):
        raw = field.get("value")
    return raw


def _build_record_summary(obj_name: str, payload: Dict[str, object]) -> Tuple[str, List[str]]:
    """Build compact text lines: Name (header), friendly ID, then a few key fields."""
    fields_by_name = {f.get("name"): f for f in payload.get("fields", [])}

    # 1) Record name (shown in the header; also used as fallback display).
    record_value = payload.get("record_value")
    name_value = str(record_value) if record_value not in (None, "") else ""
    if not name_value:
        for cand in ("name", "title", "subject"):
            field = fields_by_name.get(cand)
            if field:
                candidate = _summary_field_value(field)
                if candidate:
                    name_value = str(candidate)
                    break
    if not name_value:
        first = fields_by_name.get("first_name")
        last = fields_by_name.get("last_name")
        if first or last:
            parts = [str(_summary_field_value(x) or "") for x in (first, last) if x]
            name_value = " ".join(p for p in parts if p).strip()
    else:
        # Contacts/Leads: prefer "First Last" over an email address in the header.
        first = fields_by_name.get("first_name")
        last = fields_by_name.get("last_name")
        if (first or last) and "@" in name_value:
            parts = [str(_summary_field_value(x) or "") for x in (first, last) if x]
            full_name = " ".join(p for p in parts if p).strip()
            if full_name:
                name_value = full_name

    lines: List[str] = []

    # 2) Friendly ID line (always first).
    id_field_name = _FRIENDLY_ID_FIELDS.get(obj_name, "id")
    id_field = fields_by_name.get(id_field_name)
    id_line = None
    if id_field:
        raw_id = _summary_field_value(id_field)
        if raw_id:
            id_line = f"<b>{id_field.get('label') or 'ID'}:</b> {raw_id}"
    if not id_line:
        rid = payload.get("record_id")
        if rid not in (None, ""):
            id_line = f"<b>ID:</b> {str(rid).rstrip('.0')}"
    if id_line:
        lines.append(id_line)

    used = {id_field_name, "name", "title", "subject"}
    if not name_value and name_value != "":
        pass

    # 3) Preferred key fields per object.
    for field_name in _RECORD_SUMMARY_FIELDS.get(obj_name, []):
        field = fields_by_name.get(field_name)
        if not field or field_name in used:
            continue
        raw = _summary_field_value(field)
        value = _format_summary_value(field_name, str(raw or ""))
        if value:
            lines.append(f"<b>{field.get('label') or field_name}:</b> {value}")
            used.add(field_name)
        if len(lines) >= _MAX_SUMMARY_LINES:
            break

    # 4) Fallback fill (custom objects, unknown schemas): next informative fields.
    if len(lines) < 3:
        for field in payload.get("fields", []):
            field_name = str(field.get("name") or "")
            if field_name in used or field_name in _SYSTEM_SKIP_FIELDS:
                continue
            if field_name in _FRIENDLY_ID_FIELDS.values():
                continue
            raw = _summary_field_value(field)
            value = _format_summary_value(field_name, str(raw or ""))
            if value:
                lines.append(f"<b>{field.get('label') or field_name}:</b> {value}")
                used.add(field_name)
            if len(lines) >= _MAX_SUMMARY_LINES:
                break

    if not lines:
        lines.append(f"<b>{name_value or obj_name}</b>")
    return name_value, lines


def _display_object_label(obj_name: str) -> str:
    """Friendly label for the header (custom objects use their label, e.g. POV)."""
    if obj_name in _FAST_OBJECT_NAMES or obj_name in _RECORD_SUMMARY_FIELDS:
        return obj_name
    try:
        from cpq.models import CustomObject

        custom = CustomObject.objects.filter(name__iexact=obj_name).first()
        if custom and custom.label:
            return custom.label
    except Exception:
        pass
    return obj_name


def _parse_object_identifier(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract '<Object> <identifier>' from free text like 'opportunity Cloud Migration Sprint'."""
    for obj_name in _FAST_OBJECT_NAMES:
        obj_match = re.search(rf"\b{re.escape(obj_name)}\b", text, re.IGNORECASE)
        if obj_match:
            identifier = (text[: obj_match.start()] + " " + text[obj_match.end() :]).strip(" ,:-")
            return obj_name, identifier
    # Custom objects: match by API name or label (e.g. "pov__c" or "POV").
    try:
        from cpq.models import CustomObject

        for custom in CustomObject.objects.all():
            for keyword in (custom.name, custom.label):
                if not keyword:
                    continue
                obj_match = re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE)
                if obj_match:
                    identifier = (text[: obj_match.start()] + " " + text[obj_match.end() :]).strip(" ,:-")
                    if identifier:
                        return custom.name, identifier
    except Exception:
        pass
    return None, None


def show_record_activities(user, user_message, session_data):
    """List the Activities linked to a record ("show all activities for Opportunity <id>").

    Works for the objects an Activity can link to: Lead, Opportunity, Contact and
    Account (through its opportunities/contacts). Renders as a table card.
    """
    from .utils.orchestrator.context_handle_helpers import extract_current_request

    text = extract_current_request(user_message).strip()
    match = re.match(
        r"^(?:(?:can\s+you\s+)?(?:show|list|view|display|get|find|open)\s+)?(?:me\s+)?(?:all\s+|the\s+|any\s+|my\s+)?"
        r"activi\w*\s+(?:for|of|on|related\s+to|linked\s+to)\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    target_text = (match.group(1) if match else text).strip()
    # Normalize abbreviations AND typos ("Opp", "oppty", "opportuntiy", "acct")
    # by accepting any word that starts with the known prefix.
    for pattern, canonical in (
        (r"\bopp[a-z]*\b", "Opportunity"),
        (r"\bacct[a-z]*\b", "Account"),
        (r"\baccount[a-z]*\b", "Account"),
        (r"\blead[a-z]*\b", "Lead"),
        (r"\bcontact[a-z]*\b", "Contact"),
        (r"\bquote[a-z]*\b", "Quote"),
        (r"\bcustomer[a-z]*\b", "Account"),
    ):
        target_text = re.sub(pattern, canonical, target_text, flags=re.IGNORECASE)
    target_text = target_text.strip()

    object_name, identifier = _parse_object_identifier(target_text)
    if identifier:
        # Drop filler words users put before the id: "with id = 0004…", "number 12", "the 0004…"
        previous = None
        while identifier and identifier != previous:
            previous = identifier
            identifier = re.sub(
                r"^(?:with|the|is|id|ids|number|no\.?|named|called|for)\b[\s:=#-]*",
                "",
                identifier,
                flags=re.IGNORECASE,
            ).strip(" ,:=#-")
    if not object_name or not identifier:
        return {
            "message": (
                "Tell me which record, e.g. \"show all activities for Opportunity 0004ACPQJTXKLIW7GC\" "
                "or \"show activities for lead Jane Doe\"."
            )
        }

    supported = {"Lead": "lead", "Opportunity": "opportunity", "Contact": "contact"}
    if object_name not in supported and object_name != "Account":
        return {"message": f"⚠️ Activities can't be linked directly to {object_name}."}

    # Resolve the target record with the shared finder used by show/update/delete.
    from agents.standard_record_agent import _find_record, _find_record_candidates

    record = _find_record(object_name, identifier)
    if record is None:
        candidates = _find_record_candidates(object_name, identifier)
        if candidates:
            listing = ", ".join(f"{c} (id: {getattr(c, 'pk', '')})" for c in candidates[:5])
            return {"message": f"⚠️ Multiple {object_name} match '{identifier}': {listing}. Use a unique id."}
        return {"message": f"⚠️ No {object_name} found matching '{identifier}'."}

    from cpq.models import Activity
    from django.db.models import Q

    if object_name == "Account":
        qs = Activity.objects.filter(Q(opportunity__account=record) | Q(contact__account=record)).distinct()
    else:
        qs = Activity.objects.filter(**{supported[object_name]: record})

    qs = qs.order_by("-created_at")[:50]

    from .utils.analytics_agent.handle_helpers import safe_serialize_queryset

    rows = safe_serialize_queryset(qs, "Activity") or []
    type_labels = dict(Activity.ACTIVITY_TYPE_CHOICES)
    status_labels = dict(Activity.STATUS_CHOICES)
    for row in rows:
        if isinstance(row, dict):
            if "activity_type" in row:
                row["activity_type"] = type_labels.get(row["activity_type"], row["activity_type"])
            if "status" in row:
                row["status"] = status_labels.get(row["status"], row["status"])
            notes = row.get("notes")
            if isinstance(notes, str) and len(notes) > 80:
                row["notes"] = notes[:77] + "…"

    label = getattr(record, "name", None) or str(record)
    if not rows:
        return {
            "message": (
                f"No activities yet for {object_name} '<b>{label}</b>'. "
                "Open the record form and use <b>Log activity</b> to add one."
            )
        }

    return {
        "message": f"📋 Showing {len(rows)} activity(s) for {object_name} '<b>{label}</b>'.",
        "retrieved_records": {"Activity": rows},
        "object_labels": {"Activity": "Activities"},
        "hiddenMessage": True,
    }


def show_record_summary(user, user_message, session_data):
    """Compact text-only record details (ID, Name, plus a few key fields per object)
    plus a hint for the UI to offer an eye-icon that expands the full editable form.
    Works for every standard object and custom-object records."""
    # Deterministic parsers must operate on the raw request — strip any
    # conversation-context prefix injected by orchestrate_request_trigger.
    from .utils.orchestrator.context_handle_helpers import extract_current_request

    text = extract_current_request(user_message).strip()
    match = re.match(
        r"^(?:(?:can\s+you\s+)?(?:show|display|view|get|give|open)\s+)?(?:me\s+)?(?:the\s+)?details\s+(?:about|for|of|on)\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    rest = match.group(1).strip() if match else text

    obj_name, identifier = _parse_object_identifier(rest)
    if not obj_name or not identifier:
        return {"message": "⚠️ I couldn't determine the record. Try: show details for opportunity <name>."}

    record_message, record_payload = get_single_record_payload(
        user, {"object": obj_name, "identifier": identifier}
    )
    if not record_payload:
        return {"message": record_message or f"⚠️ No {obj_name} found matching '{identifier}'."}

    name_value, lines = _build_record_summary(obj_name, record_payload)
    display_label = _display_object_label(obj_name)
    record_label = name_value or obj_name

    summary = "<br>".join(lines)
    message = f"📋 {display_label}: <b>{record_label}</b>"
    if summary:
        message += f"<br>{summary}"

    return {
        "message": message,
        "single_record_summary": {
            "object": obj_name,
            "record_id": record_payload.get("record_id"),
            "name": record_label,
        },
        "hiddenMessage": False,
    }


def show_single_record(user, user_message, session_data):
    """Displays a single record detail card for any supported object."""

    # Fast path: "show related records for <Object> <identifier>" — parse the
    # object + identifier deterministically (no LLM round-trip). The single-record
    # form already renders the Related records section.
    from .utils.orchestrator.context_handle_helpers import extract_current_request

    fast_request = _try_fast_single_record_request(extract_current_request(user_message))
    if fast_request:
        record_message, record_payload = get_single_record_payload(user, fast_request)
        if record_payload:
            return {
                "message": record_message or "Here's what I found:",
                "single_record": record_payload,
                "hiddenMessage": True,
            }
        return {"message": record_message}

    # Follow-up references: "show the lead" / "open it" → the record just created/opened.
    active_ref = _try_active_record_reference(user, user_message, session_data)
    if active_ref:
        record_message, record_payload = get_single_record_payload(user, active_ref)
        if record_payload:
            _set_active_record(session_data, record_payload)
            return {
                "message": record_message or "Here's what I found:",
                "single_record": record_payload,
                "hiddenMessage": True,
            }

    current_state, previous_summary = get_session_context("show_single_record", session_data)

    llm_result, tokens_used, cost_est = extract_single_record_request(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary,
    )

    if not llm_result:
        return {
            "message": "⚠️ I wasn’t able to understand which record you’d like to review. Could you rephrase that request?"
        }

    show_requests = llm_result.get("show_single_record", [])
    if not isinstance(show_requests, list):
        show_requests = []

    completed_requests = [item["data"] for item in show_requests if item.get("completed")]
    remaining_requests = [item for item in show_requests if not item.get("completed")]

    # Persist remaining state for follow-up turns
    session_data.setdefault("state", {})
    session_data["state"]["show_single_record"] = remaining_requests
    session_data["state"]["summary"] = llm_result.get("summary")

    if not completed_requests:
        fallback_request = _get_active_record_request(session_data, show_requests)
        if fallback_request:
            record_message, record_payload = get_single_record_payload(user, fallback_request)
            if record_payload:
                display_message = record_message or "Here’s what I found:"
                _set_active_record(session_data, record_payload)
                return {
                    "message": display_message,
                    "single_record": record_payload,
                    "session_summary": llm_result.get("summary"),
                    "hiddenMessage": True,
                    "llm": {
                        "tokens_used": tokens_used,
                        "cost_estimate": cost_est,
                    },
                }

        agent_message = llm_result.get(
            "agent_message",
            "⚠️ I still need the record name or identifier you’d like me to open."
        )
        return {
            "message": agent_message,
            "session_summary": llm_result.get("summary")
        }

    request_payload = completed_requests[0]

    record_message, record_payload = get_single_record_payload(user, request_payload)
    if not record_payload:
        # The helper already returned a user-facing message for failure scenarios
        return {
            "message": record_message,
            "session_summary": llm_result.get("summary")
        }

    display_message = record_message or "Here’s what I found:"

    if record_payload and str(record_payload.get("object", "")).lower() == "quote":
        quote_id = record_payload.get("record_id")
        if quote_id:
            try:
                quote = Quote.objects.get(id=quote_id)
                set_active_quote_to_session_data(session_data, quote)
            except Quote.DoesNotExist:
                logger.warning("Quote %s not found when setting active quote.", quote_id)
            except Exception as exc:
                logger.warning("Unable to set active quote from single record: %s", exc)

    if record_payload:
        _set_active_record(session_data, record_payload)

    return {
        "message": display_message,
        "single_record": record_payload,
        "session_summary": llm_result.get("summary"),
        "hiddenMessage": True,
        "llm": {
            "tokens_used": tokens_used,
            "cost_estimate": cost_est,
        },
    }


def update_single_record_from_ui(user, user_message, session_data):
    """Handle inline updates to single-record fields triggered from the UI."""

    try:
        payload_str = user_message.replace("Update Record:", "", 1).strip()
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        # Fallback: strip any conversation-context prefix before retrying.
        from .utils.orchestrator.context_handle_helpers import extract_current_request

        payload_str = extract_current_request(user_message).replace("Update Record:", "", 1).strip()
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON payload for Update Record request: %s", user_message)
            return {
                "message": "⚠️ I couldn’t understand that update payload.",
                "hiddenMessage": True,
            }

    object_name = payload.get("object")
    record_id = payload.get("record_id")
    updates_payload = payload.get("updates")

    if updates_payload and isinstance(updates_payload, list):
        normalized_updates = updates_payload
    else:
        # Fallback to legacy single-field payload
        field_name = payload.get("field")
        if not field_name:
            return {
                "message": "⚠️ Missing field information for the update.",
                "hiddenMessage": True,
            }
        normalized_updates = [{
            "field": field_name,
            "value": payload.get("value"),
            "data_type": payload.get("data_type"),
            "is_custom": payload.get("is_custom", False),
            "field_id": payload.get("field_id"),
        }]

    if not object_name or not record_id or not normalized_updates:
        return {
            "message": "⚠️ Missing object, record, or field information for the update.",
            "hiddenMessage": True,
        }

    metadata = get_object_metadata(object_name)
    if metadata is None:
        return {
            "message": f"⚠️ I can’t update records for <strong>{object_name}</strong>.",
            "hiddenMessage": True,
        }

    model = metadata["model"]
    custom_object = metadata["custom_object"]
    custom_fields = metadata["custom_fields"]

    record_queryset = model.objects.all()
    if custom_object:
        record_queryset = record_queryset.filter(object_type=custom_object)

    try:
        record = record_queryset.get(id=record_id)
    except model.DoesNotExist:
        return {
            "message": "⚠️ I couldn’t find that record anymore. Try refreshing the card.",
            "hiddenMessage": True,
        }

    if not partner_can_access_record(user, object_name, record, custom_object=custom_object, permission="change"):
        return {
            "message": "⚠️ You don’t have permission to update that record.",
            "hiddenMessage": True,
        }

    messages_success: List[str] = []
    messages_error: List[str] = []

    successful_fields: List[str] = []
    failed_fields: List[str] = []

    def _normalize_target_type(name: str) -> str:
        normalized = (name or "").strip().lower().replace(" ", "_")
        if normalized == "quoteline":
            return "quote_line"
        return normalized

    target_type = _normalize_target_type(object_name)

    try:
        with transaction.atomic():
            for update in normalized_updates:
                field_name = update.get("field")
                if not field_name:
                    messages_error.append("Missing field name in update payload.")
                    failed_fields.append("Unknown field")
                    continue

                success, message = update_record_field(
                    record,
                    object_name,
                    field_name,
                    update.get("value"),
                    data_type=update.get("data_type"),
                    is_custom=update.get("is_custom", False),
                    field_id=update.get("field_id"),
                    custom_fields=custom_fields,
                    user=user,
                )

                if success:
                    messages_success.append(message)
                    successful_fields.append(field_name)
                else:
                    messages_error.append(message)
                    failed_fields.append(field_name)

            # Enforce BusinessRule validations for UI updates (extends functionality; does not affect flows without rules).
            if successful_fields and target_type:
                if target_type.endswith("__c"):
                    context = {"custom_record": record, "_default_root": "custom_record"}
                else:
                    context = {target_type: record, "_default_root": target_type}
                    for rel in ("quote", "quote_line", "product", "account", "opportunity", "contract", "tenant"):
                        try:
                            value = getattr(record, rel, None)
                        except Exception:
                            value = None
                        if value is not None:
                            context[rel] = value

                # Allow conditions like user.is_superuser == false.
                if user is not None:
                    context["user"] = user

                violations = check_for_validation_rules(target_type, context, rule_type="validation")
                if violations:
                    raise ValueError("🚫 Validation failed:<br>" + "<br>".join(violations))
    except ValueError as exc:
        # Transaction rolled back; return the current (unchanged) record payload.
        record.refresh_from_db()
        updated_payload = serialize_record(record, object_name, custom_object, custom_fields, user=user)
        return {
            "message": str(exc),
            "single_record": updated_payload,
            "hiddenMessage": True,
            "suppress_chat": True,
            "updated_fields": [],
            "failed_fields": list({*failed_fields, *successful_fields}) if (failed_fields or successful_fields) else [],
        }

    record.refresh_from_db()

    updated_payload = serialize_record(record, object_name, custom_object, custom_fields, user=user)

    combined_messages = []
    if messages_success:
        combined_messages.append("<br>".join(messages_success))
    if messages_error:
        combined_messages.append("<br>".join(messages_error))

    response: Dict[str, Any] = {
        "message": "<br>".join(combined_messages) if combined_messages else "",
        "single_record": updated_payload,
        "hiddenMessage": True,
        "suppress_chat": True,
    }

    response["updated_fields"] = successful_fields
    response["failed_fields"] = failed_fields

    return response


def _find_field_metadata(payload: Dict[str, Any], field_name: str, is_custom: bool, field_id: Optional[int]):
    for field in payload.get("fields", []):
        if field.get("name") != field_name:
            continue
        if bool(field.get("is_custom")) != bool(is_custom):
            continue
        if is_custom and field_id is not None and field.get("field_id") != field_id:
            continue
        return field
    return None
