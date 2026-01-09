import json
import logging
from typing import Any, Dict, List, Optional

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
from .utils.quote_agent.general_helpers import set_active_quote_to_session_data
from .utils.session_context_helpers.session_context_helpers import get_session_context

logger = logging.getLogger(__name__)

_ACTIVE_RECORD_OBJECTS = {"account", "opportunity", "lead"}


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
    }

    handler = action_map.get(action)
    if handler:
        return handler(user, user_message, session_data)

    logger.warning("record_agent received unsupported action '%s'", action)
    return {"message": "🤖 Sorry, I couldn’t understand your request."}


def show_single_record(user, user_message, session_data):
    """Displays a single record detail card for any supported object."""

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
    if messages_error:
        combined_messages.append("<br>".join(messages_error))
    if messages_success and messages_error:
        combined_messages.insert(0, "<br>".join(messages_success))

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
