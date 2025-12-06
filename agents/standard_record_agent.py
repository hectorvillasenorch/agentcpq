import json
import logging
import os
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import openai
from django.contrib.auth import get_user_model
from django.utils.dateparse import parse_date
from dotenv import load_dotenv

from cpq.models import Account, Contact, Lead, Opportunity
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

ALLOWED_FIELDS: Dict[str, List[str]] = {
    "Lead": ["first_name", "last_name", "email", "phone", "source", "status", "notes", "assigned_to", "owner"],
    "Account": ["name", "industry", "website", "phone", "street", "city", "state", "zip_code", "tenant_id", "owner"],
    "Contact": ["first_name", "last_name", "email", "phone", "company", "job_title", "notes", "account", "is_primary"],
    "Opportunity": ["name", "account", "amount", "stage", "expected_close_date", "owner"],
}


def standard_record_agent(user, action, user_message, session_data):
    if action != "CreateStandardRecord":
        return {"message": "⚠️ Unsupported action for standard records."}

    return _create_standard_records(user, user_message, session_data)


def _create_standard_records(user, user_message, session_data):
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
        "hiddenMessage": True,
    }


def _extract_create_requests(user_message: str, current_state, previous_summary: Optional[str]):
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
   - Lead: first_name, last_name, email, phone, source, status, notes, assigned_to, owner
   - Account: name, industry, website, phone, street, city, state, zip_code, tenant_id, owner
   - Contact: first_name, last_name, email, phone, company, job_title, notes, account, is_primary
   - Opportunity: name, account, amount, stage, expected_close_date, owner
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
        normalized_fields = {k: v for k, v in fields.items() if isinstance(k, str)}

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


def _persist_record(user, object_name: str, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    if object_name not in SUPPORTED_OBJECTS:
        return False, f"⚠️ Unsupported object '{object_name}'.", {}

    required_missing = [f for f in REQUIRED_FIELDS[object_name] if not fields.get(f)]
    if required_missing:
        return False, f"⚠️ Missing required fields for {object_name}: {', '.join(required_missing)}.", {}

    try:
        if object_name == "Lead":
            return _create_lead(user, fields)
        if object_name == "Account":
            return _create_account(user, fields)
        if object_name == "Contact":
            return _create_contact(user, fields)
        if object_name == "Opportunity":
            return _create_opportunity(user, fields)
    except Exception as exc:
        logger.exception("Failed to create %s", object_name)
        return False, f"⚠️ Failed to create {object_name}: {exc}", {}

    return False, f"⚠️ Unsupported object '{object_name}'.", {}


def _create_lead(user, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    status = fields.get("status")
    if status and status not in dict(Lead.STATUS_CHOICES):
        return False, f"⚠️ Invalid lead status '{status}'. Allowed: {', '.join(dict(Lead.STATUS_CHOICES))}.", {}

    lead = Lead.objects.create(
        first_name=str(fields.get("first_name")),
        last_name=str(fields.get("last_name")),
        email=fields.get("email") or "",
        phone=fields.get("phone") or "",
        source=fields.get("source") or "",
        status=status or Lead.STATUS_CHOICES[0][0],
        notes=fields.get("notes") or "",
        assigned_to=fields.get("assigned_to") or "",
        owner=_resolve_user(fields.get("owner")),
        created_by=user,
    )

    return True, "", _record_payload("Lead", lead)


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

    return True, "", _record_payload("Account", account)


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

    return True, "", _record_payload("Contact", contact)


def _create_opportunity(user, fields: Dict[str, object]) -> Tuple[bool, str, Dict[str, object]]:
    account_ref = _find_account(fields.get("account"))
    if not account_ref:
        return False, f"⚠️ Account '{fields.get('account')}' not found for Opportunity.", {}

    stage_value = fields.get("stage") or Opportunity.STAGE_CHOICES[0][0]
    valid_stages = [choice[0] for choice in Opportunity.STAGE_CHOICES]
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

    return True, "", _record_payload("Opportunity", opportunity)


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


def _find_account(value) -> Optional[Account]:
    if not value:
        return None

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
