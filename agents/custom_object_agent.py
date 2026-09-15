import os
import re
import openai
import logging
import json
from dotenv import load_dotenv
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from cpq.models import CustomObject, CustomField, CustomRecord, CustomFieldValue
from django.db.models import Q

#LLM helpers
from agents.utils.custom_object_agent.llm_helpers import extract_custom_object_data, extract_custom_objects, extract_custom_objects_updates, extract_custom_objects_deletes, extract_custom_fields, extract_custom_fields_updates, extract_custom_fields_deletes, extract_custom_records_updates, extract_custom_records_deletes

# Session Context Helpers
from .utils.orchestrator.context_handle_helpers import save_or_update_conversation_context, make_session_context

# Handle Helpers
from .utils.custom_object_agent.handle_helpers import handle_custom_object_creation, handle_custom_object_updates, handle_custom_object_deletes, handle_custom_fields_creation, handle_custom_fields_updates, handle_custom_field_deletes, handle_custom_object_records, handle_custom_records_updates, handle_custom_record_deletes

from .utils.session_context_helpers.session_context_helpers import get_session_context
from .utils.message_formatters import SUCCESS_ICON, ERROR_ICON, INFO_ICON, WARNING_ICON

from agents.llm import get_llm_client, get_model

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = get_model("structured")

client = get_llm_client()

def custom_object_agent(user, action, user_message, session_data):

    action_map = {
        "CreateCustomObject": create_custom_object,
        "UpdateCustomObject": update_custom_object,
        "DeleteCustomObject": delete_custom_object,
        "CreateCustomField": create_custom_field,
        "UpdateCustomField": update_custom_field,
        "DeleteCustomField": delete_custom_field,
        "CreateCustomRecord": create_custom_record,
        "UpdateCustomRecord": update_custom_record,
        "DeleteCustomRecord": delete_custom_record
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user, user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request."}

def create_custom_object(user, user_message, session_data):
    """Create custom object"""
    # 🧠 Make the session context
    session_context = make_session_context(user, "CreateCustomObject", "custom_object_agent", session_data, user_message)

    logging.info("🔧 Creating custom object...\n\n")

    current_state, previous_summary = get_session_context("create_custom_object", session_data)


    # ✅ Extract custom object details with LLM
    extracted_custom_objects = extract_custom_objects(user_message, previous_summary)

    if not extracted_custom_objects:
        session_context["item_index"] = 1
        session_context["extracted"] = "Something went wrong when LLM trying to extract custom objects data."
        agent_response = f"An error occurred while extracting your custom objects data. Please try again."
        save_or_update_conversation_context(session_context, agent_response)
        return {
        "message": f"{WARNING_ICON} AgentCPQ: An error occurred while extracting your custom objects data. Please try again."
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, custom_objects_created = handle_custom_object_creation(user, extracted_custom_objects, response_message, session_context)

    # ✅ Return
    if not custom_objects_created:
        return {
            "message": f"{WARNING_ICON} No custom objects were created.<br><br>{response_message}",
            "temporaryMessage": True
        }

    return {
        "message": response_message,
        "temporaryMessage": True
        }

def update_custom_object(user, user_message, session_data):
    """Edit custom object"""
    # 🧠 Make the session context
    session_context = make_session_context(user, "EditCustomObject", "custom_object_agent", session_data, user_message)

    logging.info("🔧 Editing custom object...\n\n")

    # ✅ Get all the custom objects
    custom_objects = CustomObject.objects.values_list("name", flat=True)

    # ✅ Extract custom object details with LLM
    extracted_custom_objects_updates = extract_custom_objects_updates(user_message, custom_objects)

    if not extracted_custom_objects_updates:
        session_context["item_index"] = 1
        session_context["extracted"] = "Something went wrong when LLM trying to extract custom objects data."
        agent_response = f"An error occurred while extracting your custom objects data. Please try again."
        save_or_update_conversation_context(session_context, agent_response)
        return {
        "message": f"{WARNING_ICON} AgentCPQ: An error occurred while extracting your custom objects data to update. Please try again."
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, custom_objects_updated = handle_custom_object_updates(user, extracted_custom_objects_updates, response_message, session_context)

    # ✅ Return
    if not custom_objects_updated:
        return {
            "message": f"{WARNING_ICON} No custom objects were updated.<br><br>{response_message}",
            "temporaryMessage": True
        }

    return {
        "message": response_message,
        "temporaryMessage": True
        }

def delete_custom_object(user, user_message, session_data):
    """Delete custom object"""
    # 🧠 Make the session context
    session_context = make_session_context(user, "EditCustomObject", "custom_object_agent", session_data, user_message)

    logging.info("🔧 Deleting custom object...\n\n")

    # ✅ Get all the custom objects
    custom_objects = CustomObject.objects.values_list("name", flat=True)

    # ✅ Extract custom object details with LLM
    extracted_custom_objects_deletes = extract_custom_objects_deletes(user_message, custom_objects)

    if not extracted_custom_objects_deletes:
        session_context["item_index"] = 1
        session_context["extracted"] = "Something went wrong when LLM trying to extract custom objects data."
        agent_response = f"An error occurred while extracting your custom objects data. Please try again."
        save_or_update_conversation_context(session_context, agent_response)
        return {
        "message": f"{WARNING_ICON} AgentCPQ: An error occurred while extracting your custom objects data to delete. Please try again."
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, custom_objects_deleted = handle_custom_object_deletes(user, extracted_custom_objects_deletes, response_message, session_context)

    # ✅ Return
    if not custom_objects_deleted:
        return {
            "message": f"{WARNING_ICON} No custom objects were deleted.<br><br>{response_message}",
            "temporaryMessage": True
        }

    return {
        "message": response_message,
        "temporaryMessage": True
        }

_PICKLIST_TYPES = {"picklist", "select", "dropdown", "dropdownlist", "choice", "choices", "multipicklist"}


def _parse_custom_field_request(text: str):
    """Deterministic parse of "create custom field ... Name: X, Type: Picklist {a, b}".

    Used as a fallback when the LLM extraction fails, so simple field requests
    always work. Returns a dict shaped like the LLM output, or None.
    """
    import re as _re

    if not text or "custom field" not in text.lower():
        return None

    # object: "... in the Account object" / "... on the custom object Foo"
    object_type = None
    custom_object = None
    m_obj = _re.search(
        r"\b(?:in|on|for|to)\s+(?:the\s+)?(?:custom\s+object\s+)?([A-Za-z][\w ]*?)\s+(?:custom\s+object|object)\b",
        text,
        _re.IGNORECASE,
    )
    if m_obj:
        value = m_obj.group(1).strip()
        if value.lower() not in {"custom", "standard", "new", "a", "an"}:
            if value.endswith("__c"):
                custom_object = value
            else:
                object_type = value
    m_co = _re.search(r"\bcustom\s+object\s+([A-Za-z][\w]*)(__c)?\b", text, _re.IGNORECASE)
    if m_co and not object_type:
        custom_object = m_co.group(1) + ("__c" if not m_co.group(1).endswith("__c") else "")

    # label: "Name: Customer Type"
    label = None
    for pattern in (r"\bname\s*[:\-]\s*([^,;\n]+)", r"\b(?:field\s+)?(?:called|named)\s+([^,;\n]+)"):
        m = _re.search(pattern, text, _re.IGNORECASE)
        if m:
            candidate = m.group(1).strip().strip('"\'')
            candidate = _re.sub(r"\s*\(.*$", "", candidate).strip()
            if candidate:
                label = candidate
                break
    if not label:
        return None

    # data type: "Type: Picklist"
    data_type = "text"
    m_type = _re.search(r"\btype\s*[:\-]\s*([A-Za-z ]+)", text, _re.IGNORECASE)
    if m_type:
        raw_type = m_type.group(1).strip().split()[0].lower()
        data_type = "dropdown" if raw_type in _PICKLIST_TYPES else raw_type
    if data_type in _PICKLIST_TYPES:
        data_type = "dropdown"

    # options: "{ Customer, Prospect, ... }" or "[...]" or "(...)"
    options = None
    m_opts = _re.search(r"[{(\[]([^})\]]+)[})\]]", text)
    if m_opts:
        options = [opt.strip().strip('"\'') for opt in m_opts.group(1).split(",") if opt.strip()]
    if data_type == "dropdown" and not options:
        return None

    return {
        "label": label,
        "data_type": data_type,
        "object_type": object_type,
        "custom_object": custom_object,
        "options": options,
        "required": False,
    }


def create_custom_field(user, user_message, session_data):
    """Create custom object"""
    # 🧠 Make the session context
    session_context = make_session_context(user, "CreateCustomField", "custom_object_agent", session_data, user_message)

    logging.info("🔧 Creating custom field...\n\n")

    # ✅ Get all the custom objects
    custom_objects = CustomObject.objects.values_list("name", flat=True)

    # ✅ Extract custom object details with LLM
    extracted_custom_fields = extract_custom_fields(user_message, custom_objects)

    if not extracted_custom_fields:
        # Deterministic fallback: many simple requests beat the LLM's JSON parsing
        # ("Name: X, Type: Picklist {a, b}") — never fail them.
        fallback = _parse_custom_field_request(user_message)
        if fallback:
            logging.info("🔧 Using deterministic custom-field parse fallback: %s", fallback)
            extracted_custom_fields = [fallback]

    if not extracted_custom_fields:
        return {
        "message": f"{WARNING_ICON} AgentCPQ: An error occurred while extracting your custom fields data. Please try again."
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, custom_fields_created = handle_custom_fields_creation(user, extracted_custom_fields, response_message, session_context)

    # ✅ Return
    if not custom_fields_created:
        return {
            "message": f"No custom fields were created. <br><br>{response_message}",
            "temporaryMessage": True
        }

    return {
        "message": response_message,
        "temporaryMessage": True
        }

def update_custom_field(user, user_message, session_data):
    """Edit custom field"""
    # 🧠 Make the session context
    current_state, previous_summary = get_session_context("update_custom_field", session_data)

    logging.info("🔧 Editing custom field...\n\n")

    # ✅ Get all the custom objects
    custom_objects = CustomObject.objects.values_list("name", flat=True)
    custom_fields = CustomField.objects.values_list("name", flat=True)

    extracted_custom_fields_updates = extract_custom_fields_updates(user_message, custom_objects, custom_fields, previous_summary)

    if not extracted_custom_fields_updates:
        return {
        "message": f"{WARNING_ICON} AgentCPQ: An error occurred while extracting your custom fields data to update. Please try again."
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, custom_fields_updated = handle_custom_fields_updates(user, extracted_custom_fields_updates, response_message)

    # ✅ Return
    if not custom_fields_updated:
        return {
            "message": f"No custom fields were updated. <br><br>{response_message}",
            "temporaryMessage": True
        }

    return {
        "message": response_message,
        "temporaryMessage": True
        }

def delete_custom_field(user, user_message, session_data):
    """Delete custom field"""
    # 🧠 Make the session context
    session_context = make_session_context(user, "DeleteCustomField", "custom_object_agent", session_data, user_message)

    logging.info("🔧 Deleting custom field...\n\n")

    # ✅ Get all the custom objects
    custom_objects = CustomObject.objects.values_list("name", flat=True)
    custom_fields = CustomField.objects.values_list("name", flat=True)

    # ✅ Extract custom object details with LLM
    extracted_custom_fields_deletes = extract_custom_fields_deletes(user_message, custom_objects, custom_fields)

    if not extracted_custom_fields_deletes:
        session_context["item_index"] = 1
        session_context["extracted"] = "Something went wrong when LLM trying to extract custom fields data."
        agent_response = f"An error occurred while extracting your custom fields data. Please try again."
        save_or_update_conversation_context(session_context, agent_response)
        return {
        "message": f"{WARNING_ICON} AgentCPQ: An error occurred while extracting your custom fields data to delete. Please try again."
        }

    response_message = ""

    # ✅ Handle custom fields deletes
    response_message, custom_fields_deleted = handle_custom_field_deletes(user, extracted_custom_fields_deletes, response_message, session_context)

    # ✅ Return
    if not custom_fields_deleted:
        return {
            "message": f"No custom fields were deleted. <br><br>{response_message}",
            "temporaryMessage": True
        }

    return {
        "message": response_message,
        "temporaryMessage": True
        }


_NAME_ISH_TOKENS = ("name", "title", "subject", "label")


def _custom_object_tokens(custom_object):
    """Return singular/plural search tokens for a custom object's name/label."""
    tokens = []
    seen = set()
    for raw in (getattr(custom_object, "name", "") or "", getattr(custom_object, "label", "") or ""):
        base = str(raw).strip().lower()
        base = re.sub(r"__c$", "", base)
        base = base.replace("_", " ").strip()
        if not base or base in seen:
            continue
        seen.add(base)
        tokens.append(base)
        if base.endswith("s"):
            singular = base[:-1]
            if singular and singular not in seen:
                seen.add(singular)
                tokens.append(singular)
        else:
            plural = base + "s"
            if plural not in seen:
                seen.add(plural)
                tokens.append(plural)
    return tokens


def _match_bare_custom_record_create(user_message):
    """Return the custom object for a bare "create new <object>" request.

    Only matches when the message contains no field values, e.g.
    "create new project", "add a new invoice", or "new work order".
    Returns ``None`` when the message isn't this pattern.
    """
    text = str(user_message or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if not re.search(r"\b(create|add|register|new)\b", lowered):
        return None

    for custom_object in CustomObject.objects.all():
        for token in _custom_object_tokens(custom_object):
            create_pattern = (
                r"^(?:please\s+)?(?:can\s+you\s+)?(?:create|add|register)\s+"
                r"(?:a\s+|an\s+)?(?:new\s+)?(?:the\s+)?"
                + re.escape(token)
                + r"\s*[.!?]*(?:\s+please)?$"
            )
            if re.match(create_pattern, text, re.IGNORECASE):
                return custom_object

            new_pattern = (
                r"^(?:a\s+|an\s+)?new\s+(?:the\s+)?"
                + re.escape(token)
                + r"\s*[.!?]*$"
            )
            if re.match(new_pattern, text, re.IGNORECASE):
                return custom_object
    return None


def _pick_default_custom_field(custom_object):
    """Choose the field that receives the record's single default value."""
    fields = list(custom_object.custom_fields.all().order_by("id"))
    if not fields:
        return None
    for field in fields:
        key = str(field.name or "").lower().removesuffix("__c").replace("_", " ")
        if any(token in key for token in _NAME_ISH_TOKENS):
            return field
    return fields[0]


def _default_value_for_custom_field(field, object_label):
    """Build a sensible default value for a custom field's data type."""
    data_type = str(field.data_type or "").strip().lower()
    if data_type in ("dropdown", "picklist", "select", "multipicklist"):
        options = field.options or []
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except Exception:
                options = []
        if isinstance(options, list) and options:
            return str(options[0])
        return ""
    if data_type in ("number", "currency", "percent"):
        return "0"
    if data_type in ("boolean", "checkbox"):
        return "false"
    if data_type in ("date",):
        return timezone.now().strftime("%Y-%m-%d")
    if data_type in ("datetime", "date_time"):
        return timezone.now().strftime("%Y-%m-%d %H:%M")
    return f"New {object_label or 'Record'}"


def _create_blank_custom_record_from_message(user, user_message):
    """Handle "create new <custom object>" without LLM.

    Creates one record with a single default value and returns the
    ``single_record`` payload so the frontend opens the editable form.
    Returns ``None`` when the message doesn't match the bare-create pattern.
    """
    custom_object = _match_bare_custom_record_create(user_message)
    if custom_object is None:
        return None

    object_label = custom_object.label or custom_object.name
    try:
        with transaction.atomic():
            record = CustomRecord.objects.create(
                object_type=custom_object,
                created_by=user,
                updated_by=user,
            )

            default_field = _pick_default_custom_field(custom_object)
            if default_field is not None:
                default_value = _default_value_for_custom_field(default_field, object_label)
                content_type = ContentType.objects.get_for_model(CustomRecord)
                CustomFieldValue.objects.create(
                    field=default_field,
                    value=str(default_value),
                    record=record,
                    content_type=content_type,
                    object_id=record.id,
                )
    except Exception as exc:
        logging.exception("Failed to create blank custom record for %s: %s", object_label, exc)
        return {
            "message": f"{WARNING_ICON} Hmm, something went wrong while creating the {object_label} record. Mind trying again?",
            "temporaryMessage": True,
        }

    message = (
        f"{SUCCESS_ICON} Created a new <b>{object_label}</b> record and opened its form. "
        "Fill in the details and save when ready."
    )

    try:
        from agents.utils.record_agent.handle_helpers import get_single_record_payload

        _, payload = get_single_record_payload(
            user,
            {"object": custom_object.name, "record_id": record.id},
        )
    except Exception as exc:
        logging.exception("Failed to build single_record payload for blank custom record: %s", exc)
        payload = None

    if payload is None:
        return {
            "message": message + "<br><br>⚠️ The record was created, but I couldn't open its form right now.",
            "temporaryMessage": True,
        }

    return {
        "message": message,
        "single_record": payload,
    }


def create_custom_record(user, user_message, session_data):
    """Create custom object record"""
    # 🧠 Deterministic fast path: "create new <custom object>" with no field
    # values should create a fresh record with one default value and open the
    # editable form — without an LLM extraction round-trip.
    blank_form_response = _create_blank_custom_record_from_message(user, user_message)
    if blank_form_response is not None:
        return blank_form_response

    # 🧠 Make the session context
    session_context = make_session_context(user, "CreateCustomObjectRecord", "custom_object_agent", session_data, user_message)

    logging.info("🔧 Creating custom object record...\n\n")

    # ✅ Extract custom object details with LLM
    custom_objects = CustomObject.objects.all()
    custom_objects_names = []
    custom_objects_data = []

    for co in custom_objects:
        custom_objects_names.append(co.name)
        fields = [
            {
                "name": field.name
            }
            for field in co.custom_fields.all()
        ]

        fields_payload = {
            "custom_object_name": co.name,
            "fields": fields
        }

        custom_objects_data.append(fields_payload)

    print(f"Custom Object Data: {custom_objects_data}\n\n")
    # ✅ Extract custom object details with LLM
    extracted_custom_objects = extract_custom_object_data(user_message, custom_objects_data, custom_objects_names)

    if not extracted_custom_objects:
        session_context["item_index"] = 1
        session_context["extracted"] = "Something went wrong when LLM trying to extract custom objects data."
        agent_response = f"An error occurred while extracting your custom objects data. Please try again."
        save_or_update_conversation_context(session_context, agent_response)
        return {
            "message": f"{WARNING_ICON} Hmm, something went wrong while processing your request. Mind trying again?"
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, custom_records_created = handle_custom_object_records(user, extracted_custom_objects, response_message, session_context)

    # ✅ Return
    if not custom_records_created:
        return {
            "message": f"No custom records were created. <br><br>{response_message}",
            "temporaryMessage": True
        }

    return {
        "message": response_message,
        "temporaryMessage": True
        }

def update_custom_record(user, user_message, session_data):
    """Update custom record"""
    # 🧠 Make the session context
    session_context = make_session_context(user, "UpdateCustomRecord", "custom_object_agent", session_data, user_message)

    logging.info("🔧 Updating custom record...\n\n")

    # ✅ Extract custom object details with LLM
    custom_objects = CustomObject.objects.all()
    custom_objects_names = []
    custom_objects_data = []

    for co in custom_objects:
        custom_objects_names.append(co.name)
        fields = [
            {
                "name": field.name
            }
            for field in co.custom_fields.all()
        ]

        fields_payload = {
            "custom_object_name": co.name,
            "fields": fields
        }

        custom_objects_data.append(fields_payload)

    # ✅ Get all the custom objects
    record_identifiers = list(CustomRecord.objects.all().values_list('custom_identifier', flat=True))

    # ✅ Extract custom records details with LLM
    extracted_custom_records_updates = extract_custom_records_updates(user_message, record_identifiers, custom_objects_data, custom_objects_names)

    if not extracted_custom_records_updates:
        session_context["item_index"] = 1
        session_context["extracted"] = "Something went wrong when LLM trying to extract custom records data."
        agent_response = f"An error occurred while extracting your custom records data. Please try again."
        save_or_update_conversation_context(session_context, agent_response)
        return {
            "message": f"{WARNING_ICON} Hmm, something went wrong while processing your request. Mind trying again?"
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, custom_records_updated = handle_custom_records_updates(user, extracted_custom_records_updates, response_message, session_context)

    # ✅ Return
    if not custom_records_updated:
        return {
            "message": f"No custom records were updated. <br><br>{response_message}",
            "temporaryMessage": True
        }

    return {
        "message": response_message,
        "temporaryMessage": True
        }

def delete_custom_record(user, user_message, session_data):
    """Delete custom record"""
    # 🧠 Make the session context
    session_context = make_session_context(user, "DeleteCustomRecord", "custom_object_agent", session_data, user_message)

    logging.info("🔧 Deleting custom record...\n\n")

    # ✅ Get all the custom objects
    record_identifiers = list(CustomRecord.objects.all().values_list('custom_identifier', flat=True))

    # ✅ Extract custom records details with LLM
    extracted_custom_records_deletes = extract_custom_records_deletes(user_message, record_identifiers)

    if not extracted_custom_records_deletes:
        session_context["item_index"] = 1
        session_context["extracted"] = "Something went wrong when LLM trying to extract custom records data."
        agent_response = f"An error occurred while extracting your custom records data. Please try again."
        save_or_update_conversation_context(session_context, agent_response)
        return {
        "message": f"{WARNING_ICON} AgentCPQ: An error occurred while extracting your custom records data to delete. Please try again."
        }

    response_message = ""

    # ✅ Handle custom records deletes
    response_message, custom_records_deleted = handle_custom_record_deletes(user, extracted_custom_records_deletes, response_message, session_context)

    # ✅ Return
    if not custom_records_deleted:
        return {
            "message": f"No custom records were deleted. <br><br>{response_message}",
            "temporaryMessage": True
        }

    return {
        "message": response_message,
        "temporaryMessage": True
        }
