from django.contrib.contenttypes.models import ContentType
from cpq.models import CustomRecord, CustomField, CustomFieldValue, CustomObject
from django.db import transaction
import json
import logging

# Session Context Helpers
from ..orchestrator.context_handle_helpers import save_or_update_conversation_context

# General Helpers
from .general_helpers import validate_and_cast_value

def save_custom_object(request, user=None):
    try:
        data = json.loads(request)

        label = data["label"]
        name = data["name"]
        description = data.get("description", "")

        with transaction.atomic():
            custom_object = CustomObject.objects.create(
                name=name,
                label=label,
                description=description,
                created_by=user,
                updated_by=user
            )

        return {
            "message": f"✅ Custom object '{label}' created successfully. Would you like to add fields to it now? Just let me know the field names and details! 🛠️",
            "success": True
        }

    except Exception as e:
        logging.warning(f"⚠️ Error creating custom object: {str(e)}")
        return {
            "message": f"❌ Error creating custom object: {str(e)}",
            "success": False
        }
    
def save_custom_field(request, user=None):
    try:
        data = json.loads(request)

        label = data["label"]
        name = data["name"]
        crm = data["crm"]
        data_type = data["data_type"]
        object_type = data["object_type"]
        required = data["required"]
        custom_object_name = data["custom_object_name"]
        lookup_model = data["lookup_model"]
        options = data["options"]

        print(f"Data type dentro del save: {data_type}")

        try:
            custom_object = CustomObject.objects.get(name=custom_object_name)
        except CustomObject.DoesNotExist:
            custom_object = None

        with transaction.atomic():
            custom_field = CustomField.objects.create(
                label=label,
                name=name,
                crm=crm,
                data_type=data_type,
                object_type=object_type,
                required=required,
                custom_object=custom_object,
                lookup_model=lookup_model,
                options=options,
                created_by=user,
                updated_by=user
            )

        return {
            "message": f"✅ Custom field '{label}' created successfully for the {custom_object.label if custom_object else object_type} object. Would you like to create another field for it? 🛠️",
            "success": True
        }

    except Exception as e:
        logging.warning(f"⚠️ Error creating custom field: {str(e)}")
        return {
            "message": f"❌ Error creating custom field: {str(e)}",
            "success": False
        }

def create_custom_record_and_values(user, response_message, custom_object, values, session_context):
    """
    Create a CustomRecord and its CustomFieldValues.
    If some field is missing, do not create the record.
    """
    missing_required_fields = []
    created_field_values = []


    fields_by_name = {
        field.name.lower(): field for field in custom_object.custom_fields.all()
    }

    # Map values extracted by LLM
    value_lookup = {
        item.get("field", "").lower(): item.get("value") for item in values
    }

    # Verify required fields
    for field_name, field in fields_by_name.items():
        if field.required and (field_name not in value_lookup or value_lookup[field_name] in [None, ""]):
            missing_required_fields.append(field.label or field.name)

    if missing_required_fields:
        message = f"⚠️ Missing required fields: {', '.join(missing_required_fields)}. The record wasn’t created.<br><br>"
        response_message += f"⚠️ Missing required fields: {', '.join(missing_required_fields)}. The record wasn’t created.<br><br>"
        return None, None, response_message, message

    # Create CustomRecord
    custom_record = CustomRecord.objects.create(
        object_type=custom_object,
        created_by=user,
        updated_by=user
    )

    # Create the associated CustomFieldValues.
    content_type = ContentType.objects.get_for_model(CustomRecord)

    for field_name, value in value_lookup.items():
        if field_name is None and value:
            agent_response = f"The field is null, LLM didn't extract the field or user didn't specify. Request omitted."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ It looks like the value <strong>{value}</strong> doesn’t have a matching field name. "
                "Could you clarify which field this value should be assigned to?<br>"
            )
            continue

        if value is None and field_name:
            agent_response = f"The value is null, LLM didn't extract the value or user didn't specify. Request omitted."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ I noticed the field <strong>{field_name}</strong> was mentioned, but no value was provided for it. "
                "Could you let me know what value you'd like to assign to this field?<br>"
            )
            continue

        if value is None and field_name is None:
            agent_response = f"The value and field is null, LLM didn't extract the value and field or user didn't specify. Request omitted."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                "⚠️ It seems you want to update a field, but I couldn’t identify which field or what value to use. "
                "Could you clarify what field you’d like to update and the value you want to set?<br>"
            )
            continue

        field = fields_by_name.get(field_name)

        print(f"Field data type: {field.data_type} and {field.data_type.lower()} and options {field.options}")

        if not field:
            agent_response = f"⚠️ I couldn't find a matching field for <strong>{field_name}</strong>. Request omitted."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ I couldn’t find a field named <strong>{field_name}</strong> in the object.<br>"
            continue

        # ✅ Validate data type
        is_valid, casted_value = validate_and_cast_value(field, value)

        if not is_valid:
            expected = f"(expected type: {field.data_type})"
            if field.data_type.lower() == "dropdown" and field.options:
                expected += f" and one of: {', '.join(field.options)}"
                print(f"\n\nExpected: {expected}")
            agent_response = f"⚠️ Invalid value for field <strong>{field.name}</strong> {expected}. Request omitted."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ The value <b>{value}</b> is not valid for the field <b>{field.label}</b>. "
                f"The value must be one of: {', '.join(field.options)}.<br>"
            )
            continue

        cfv = CustomFieldValue.objects.create(
            field=field,
            value=str(casted_value),
            record=custom_record,
            content_type=content_type,
            object_id=custom_record.id,
        )
        created_field_values.append(cfv)

    return custom_record, created_field_values, response_message, None