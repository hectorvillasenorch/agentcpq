import json
import logging
import os
import re
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import openai
from django.contrib.auth import get_user_model
from django.utils.dateparse import parse_date
from dotenv import load_dotenv

from cpq.models import Account, Contact, Lead, Opportunity, CustomField, CustomFieldValue
from django.contrib.contenttypes.models import ContentType
from .utils.agents_utils import clean_llm_json
from .utils.message_formatters import SUCCESS_ICON
from .utils.orchestrator.context_handle_helpers import estimate_cost
from .utils.session_context_helpers.session_context_helpers import get_session_context

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"

client = openai.OpenAI(api_key=OPENAI_API_KEY)
logger = logging.getLogger(__name__)
User = get_user_model()

SUPPORTED_OBJECTS = ["Lead", "Account", "Contact", "Opportunity"]

REQUIRED_FIELDS: Dict[str, List[str]] = {
    "Lead": ["first_name", "last_name"],
    "Account": ["name"],
    "Contact": ["first_name", "email", "account"],
    "Opportunity": ["name", "account"],
}

MODEL_MAP = {
    "Lead": Lead,
    "Account": Account,
    "Contact": Contact,
    "Opportunity": Opportunity,
}

# Optional extras that aren't model fields but we still accept (e.g., mapped into notes)
EXTRA_FIELDS = {
    "Lead": ["company", "company_name", "title"],
}

ALLOWED_FIELDS: Dict[str, List[str]] = {}
ALLOWED_FIELD_MAP: Dict[str, Dict[str, str]] = {}


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

        allowed_map[obj] = obj_map

    ALLOWED_FIELDS = allowed
    ALLOWED_FIELD_MAP = allowed_map


def standard_record_agent(user, action, user_message, session_data):
    if action == "CreateStandardRecord":
        return _create_standard_records(user, user_message, session_data)
    if action == "UpdateStandardRecord":
        return _update_standard_records(user, user_message, session_data)
    if action == "DeleteStandardRecord":
        return _delete_standard_records(user, user_message, session_data)
    return {"message": "⚠️ Unsupported action for standard records."}


def _create_standard_records(user, user_message, session_data):
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

    created_records = []
    errors = []

    for req in completed_requests:
        obj_name = req["data"].get("object")
        fields = req["data"].get("fields") or {}
        success, message, record_payload = _persist_record(user, obj_name, fields)
        if success:
            created_records.append(record_payload)
        else:
            errors.append(message)

    message_parts = []
    if created_records:
        success_lines = [
            f"{SUCCESS_ICON} Created {item['object']} '{item['label']}' (id: {item['id']})."
            for item in created_records
        ]
        message_parts.append("<br>".join(success_lines))
    if errors:
        message_parts.append("<br>".join(errors))

    return {
        "message": "<br>".join(message_parts) if message_parts else "",
        "session_summary": llm_result.get("summary"),
        "hiddenMessage": False,
    }


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
            f"{SUCCESS_ICON} Updated {item['object']} '{item['label']}' (id: {item['id']})."
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

    deleted = []
    errors = []
    for req in completed_requests:
        obj_name = (req.get("data") or {}).get("object")
        identifier = (req.get("data") or {}).get("identifier")
        success, message, payload = _persist_delete(obj_name, identifier)
        if success:
            deleted.append(payload)
        else:
            errors.append(message)

    message_parts = []
    if deleted:
        deleted_lines = [
            f"{SUCCESS_ICON} Deleted {item['object']} '{item['label']}' (id: {item['id']})."
            for item in deleted
        ]
        message_parts.append("<br>".join(deleted_lines))
    if errors:
        message_parts.append("<br>".join(errors))

    return {
        "message": "<br>".join(message_parts) if message_parts else "",
        "session_summary": llm_result.get("summary"),
        "hiddenMessage": False,
    }


def _extract_create_requests(user_message: str, current_state, previous_summary: Optional[str]):
    _refresh_allowed_fields()

    allowed_fields_prompt = "\n".join(
        [f"   - {obj}: {', '.join(sorted(ALLOWED_FIELDS.get(obj, [])))}" for obj in SUPPORTED_OBJECTS]
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
1. Supported objects: {', '.join(SUPPORTED_OBJECTS)}. Use singular names.
2. Allowed fields per object:
{allowed_fields_prompt}
3. Required fields:
   - Lead: first_name, last_name
   - Account: name
   - Contact: first_name, email, account
   - Opportunity: name, account
4. For Contact/Opportunity, the account value should be the account name or identifier mentioned by the user—do not invent one.
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

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logger.info("💰 Standard-record LLM estimate → tokens: %s | approx cost: $%.6f", tokens_used, cost_est)

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
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


def _extract_update_requests(user_message: str, current_state, previous_summary: Optional[str]):
    _refresh_allowed_fields()

    allowed_fields_prompt = "\n".join(
        [f"   - {obj}: {', '.join(sorted(ALLOWED_FIELDS.get(obj, [])))}" for obj in SUPPORTED_OBJECTS]
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
1. Supported objects: {', '.join(SUPPORTED_OBJECTS)}. Use singular names.
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

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logger.info("💰 Standard-record update LLM estimate → tokens: %s | approx cost: $%.6f", tokens_used, cost_est)

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
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
1. Supported objects: {', '.join(SUPPORTED_OBJECTS)}. Use singular names.
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

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logger.info("💰 Standard-record delete LLM estimate → tokens: %s | approx cost: $%.6f", tokens_used, cost_est)

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
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
    if object_name not in SUPPORTED_OBJECTS:
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
    except Exception as exc:
        logger.exception("Failed to create %s", object_name)
        return False, f"⚠️ Failed to create {object_name}: {exc}", {}

    if not success:
        return False, message, {}

    _save_custom_fields(record, fields, object_name, user)
    return True, message, _record_payload(object_name, record)


def _persist_update(user, object_name: str, identifier: str, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    if object_name not in SUPPORTED_OBJECTS:
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

    try:
        _apply_updates(user, object_name, record, fields)
        record.save()
    except Exception as exc:
        logger.exception("Failed to update %s", object_name)
        return False, f"⚠️ Failed to update {object_name}: {exc}", {}

    _save_custom_fields(record, fields, object_name, user)
    return True, "", _record_payload(object_name, record)


def _persist_delete(object_name: str, identifier: str) -> Tuple[bool, str, Dict[str, object]]:
    if object_name not in SUPPORTED_OBJECTS:
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

    payload = _record_payload(object_name, record)
    try:
        record.delete()
    except Exception as exc:
        logger.exception("Failed to delete %s", object_name)
        return False, f"⚠️ Failed to delete {object_name}: {exc}", {}

    return True, "", payload


def _id_field_for_object(object_name: str) -> str:
    return {
        "Lead": "leadId",
        "Account": "accid",
        "Contact": "contactId",
        "Opportunity": "oppid",
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

    # Prefer strict identifiers first
    id_field = _id_field_for_object(object_name)

    # 1) Numeric PK
    try:
        return list(qs.filter(pk=int(raw))[:5])
    except Exception:
        pass

    # 2) Custom id field (accid/leadId/contactId/oppid)
    try:
        if hasattr(model, id_field):
            found = list(qs.filter(**{id_field: raw})[:5])
            if found:
                return found
    except Exception:
        pass

    # 3) External id where available
    try:
        if hasattr(model, "external_id"):
            found = list(qs.filter(external_id=raw)[:5])
            if found:
                return found
    except Exception:
        pass

    # 4) Email for Lead/Contact
    if object_name in {"Lead", "Contact"}:
        try:
            found = list(qs.filter(email__iexact=raw)[:5])
            if found:
                return found
        except Exception:
            pass

    # 5) Name / partial name
    if hasattr(model, "name"):
        try:
            found = list(qs.filter(name__iexact=raw)[:5])
            if found:
                return found
        except Exception:
            pass
        try:
            return list(qs.filter(name__icontains=raw)[:5])
        except Exception:
            return []

    # 6) Lead full name search
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
        stage_value = fields.get("stage") or picklist_default_key("Opportunity", "stage")
        valid_stages = [choice[0] for choice in stage_choices] if stage_choices else []
        if stage_value and valid_stages and stage_value not in valid_stages:
            raise ValueError(f"Invalid stage '{stage_value}'. Allowed: {', '.join(valid_stages)}.")

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
    stage_value = fields.get("stage") or picklist_default_key("Opportunity", "stage")
    valid_stages = [choice[0] for choice in stage_choices] if stage_choices else []
    if stage_value not in valid_stages:
        return False, f"⚠️ Invalid stage '{stage_value}'. Allowed: {', '.join(valid_stages)}.", {}

    opportunity = Opportunity.objects.create(
        name=str(fields.get("name")),
        account=account_ref,
        amount=_coerce_decimal(fields.get("amount")),
        stage=stage_value,
        expected_close_date=_coerce_date(fields.get("expected_close_date")),
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
        or getattr(record, "first_name", None),
    }

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
