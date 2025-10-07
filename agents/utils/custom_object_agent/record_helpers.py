from django.contrib.contenttypes.models import ContentType
from cpq.models import CustomRecord, CustomField, CustomFieldValue, CustomObject
from django.db import transaction
from django.utils.timezone import now
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

def update_custom_object(request, user=None):
    try:
        data = json.loads(request)

        name = data["name"]
        label_to_update = data["label_to_update"]
        name_to_update = data["name_to_update"]
        description_to_update = data["description_to_update"]

        with transaction.atomic():

            custom_object = CustomObject.objects.get(name=name)

            fields = custom_object.custom_fields.all()


            if label_to_update:
                custom_object.label = label_to_update
            if name_to_update:
                custom_object.name = name_to_update
            if description_to_update:
                custom_object.description = description_to_update

            custom_object.updated_by = user

            custom_object.save()

            for field in fields:
                field.custom_object = custom_object
                field.object_type = custom_object.name
                field.save()


        return {
            "message": f"✅ Custom object '{custom_object.label}' updated successfully. 🛠️",
            "success": True
        }

    except Exception as e:
        logging.warning(f"⚠️ Error updating custom object: {str(e)}")
        return {
            "message": f"❌ Error updating custom object: {str(e)}",
            "success": False
        }

def delete_custom_object(request):
    try:
        data = json.loads(request)

        name = data["name"]

        with transaction.atomic():

            custom_object = CustomObject.objects.get(name=name)

            custom_object.delete()


        return {
            "message": f"✅ Custom object '{custom_object.label}' was successfully deleted. 🗑️",
            "success": True
        }

    except Exception as e:
        logging.warning(f"⚠️ Error deleting custom object: {str(e)}")
        return {
            "message": f"❌ Error deleting custom object: {str(e)}",
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


def update_custom_field(request, user=None):
    try:
        data = json.loads(request)

        target_field_label = data["target_field_label"]
        target_custom_object = data["target_custom_object"]
        target_default_object = data["target_default_object"]
        updates = data["updates"]

        label_to_update = updates["label_to_update"]
        crm_to_update = updates["crm_to_update"]
        object_type_to_update = updates["object_type_to_update"]
        required_to_update = updates["required_to_update"]
        custom_object_to_update_name = updates["custom_object_to_update_name"]
        data_type_to_update = updates["data_type_to_update"]
        options_to_update = updates["options_to_update"]


        with transaction.atomic():
            if target_custom_object:
                custom_object = CustomObject.objects.get(name=target_custom_object)
                custom_field = CustomField.objects.get(name=target_field_label, custom_object=custom_object)
            else:
                custom_field = CustomField.objects.get(name=target_field_label, object_type=target_default_object)


            if label_to_update:
                custom_field.label = label_to_update

                name_to_update = label_to_update.lower().replace(" ", "_") + "__c"
                custom_field.name = name_to_update
            if crm_to_update:
                custom_field.crm = crm_to_update
            if object_type_to_update:
                custom_field.object_type = object_type_to_update
                custom_field.custom_object = None
            if required_to_update is True or required_to_update is False:
                custom_field.required = required_to_update
            if custom_object_to_update_name:
                custom_field.custom_object = CustomObject.objects.get(name=custom_object_to_update_name)
                custom_field.object_type = CustomObject.objects.get(name=custom_object_to_update_name).name
            if data_type_to_update:
                custom_field.data_type = data_type_to_update
            if options_to_update is not None:  # Por si la lista está vacía a propósito
                custom_field.options = options_to_update


            custom_field.updated_by = user

            custom_field.save()


        return {
            "message": f"✅ Custom field '{custom_field.label}' updated successfully. 🛠️",
            "success": True
        }

    except Exception as e:
        logging.warning(f"⚠️ Error updating custom field: {str(e)}")
        return {
            "message": f"❌ Error updating custom field: {str(e)}",
            "success": False
        }

def delete_custom_field(request):
    try:
        data = json.loads(request)

        name = data["name"]
        custom_object_name = data["custom_object_name"]
        default_object_name = data["default_object_name"]

        with transaction.atomic():

            if custom_object_name:
                custom_object = CustomObject.objects.get(name=custom_object_name)

                custom_field = CustomField.objects.get(name=name, custom_object=custom_object)
            elif default_object_name:
                custom_field = CustomField.objects.get(name=name, object_type=default_object_name)

            custom_field.delete()


        return {
            "message": f"✅ Custom object '{custom_field.label}' was successfully deleted. 🗑️",
            "success": True
        }

    except Exception as e:
        logging.warning(f"⚠️ Error deleting custom field: {str(e)}")
        return {
            "message": f"❌ Error deleting custom field: {str(e)}",
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

def update_custom_record_and_values(user, response_message, custom_record, values, session_context):
    """
    Update an existing CustomRecord and its CustomFieldValues.
    If some field name or value is missing, skip that field update.
    """
    updated_field_values = []

    # Normalizar values para que sea lista si viene dict
    if isinstance(values, dict):
        values = [values]

    # Mapeo de fields por nombre (lowercase)
    fields_by_name = {
        field.name.lower(): field for field in custom_record.object_type.custom_fields.all()
    }

    # Mapeo de valores extraídos por LLM
    value_lookup = {
        item.get("field", "").lower(): item.get("value") for item in values
    }

    # Iterar sobre cada valor para actualizar
    content_type = ContentType.objects.get_for_model(CustomRecord)

    for field_name, value in value_lookup.items():
        if field_name is None and value:
            agent_response = (
                "The field is null — LLM didn't extract the field or user didn't specify. Request omitted."
            )
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ It looks like the value <strong>{value}</strong> doesn’t have a matching field name. "
                "Could you clarify which field this value should be assigned to?<br>"
            )
            continue

        if value is None and field_name:
            agent_response = (
                "The value is null — LLM didn't extract the value or user didn't specify. Request omitted."
            )
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ I noticed the field <strong>{field_name}</strong> was mentioned, "
                "but no value was provided for it.<br>"
                "Could you let me know what value you'd like to assign?<br>"
            )
            continue

        if value is None and field_name is None:
            agent_response = (
                "The value and field are null — LLM didn't extract either. Request omitted."
            )
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                "⚠️ It seems you want to update a field, but I couldn’t identify which field or what value to use.<br>"
            )
            continue

        field = fields_by_name.get(field_name)

        if not field:
            agent_response = f"⚠️ I couldn't find a matching field for <strong>{field_name}</strong>. Request omitted."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ I couldn’t find a field named <strong>{field_name}</strong> in this object.<br>"
            continue

        # Validar tipo de dato
        is_valid, casted_value = validate_and_cast_value(field, value)

        if not is_valid:
            expected = f"(expected type: {field.data_type})"
            if field.data_type.lower() == "dropdown" and field.options:
                expected += f" and one of: {', '.join(field.options)}"
            agent_response = (
                f"⚠️ Invalid value for field <strong>{field.name}</strong> {expected}. Request omitted."
            )
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ The value <b>{value}</b> is not valid for the field <b>{field.label}</b>. "
                f"The value must be one of: {', '.join(field.options)}.<br>"
            )
            continue

        # Verificar si el valor actual es distinto para evitar update innecesario
        try:
            current_cfv = CustomFieldValue.objects.get(
                field=field,
                record=custom_record,
                content_type=content_type,
                object_id=custom_record.id,
            )
            current_value = current_cfv.value
        except CustomFieldValue.DoesNotExist:
            current_cfv = None
            current_value = None

        if current_value == str(casted_value):
            # No hay cambio real, omitir
            continue

        if field_name == "label" or field.label.lower() == "label":
            # Actualizar label y name del CustomField asociado
            new_label = str(casted_value).strip()
            if new_label:
                # Actualiza el label
                field.label = new_label
                # Construye el nuevo name: label en minúsculas, espacios reemplazados por _, y con __c
                new_name = new_label.lower().replace(" ", "_") + "__c"
                field.name = new_name
                field.save()


        cfv, created = CustomFieldValue.objects.update_or_create(
            field=field,
            record=custom_record,
            content_type=content_type,
            object_id=custom_record.id,
            defaults={"value": str(casted_value)},
        )

        updated_field_values.append(cfv)

    # Solo actualizar si hubo cambios reales
    if updated_field_values:
        custom_record.updated_by = user
        custom_record.save()
        return custom_record, updated_field_values, response_message, None
    else:
        # No hubo actualizaciones, retorna error_message para evitar éxito falso
        return custom_record, updated_field_values, response_message, (
            f"⚠️ No valid fields were updated for record <b>{custom_record.custom_identifier}</b>.<br><br>"
        )


def delete_custom_record(request):
    try:
        data = json.loads(request)

        record_identifier = data["record_identifier"]

        with transaction.atomic():

            custom_record = CustomRecord.objects.get(custom_identifier=record_identifier)

            custom_record.delete()


        return {
            "message": f"✅ Custom record '{record_identifier}' was successfully deleted. 🗑️",
            "success": True
        }

    except Exception as e:
        logging.warning(f"⚠️ Error deleting custom record: {str(e)}")
        return {
            "message": f"❌ Error deleting custom record: {str(e)}",
            "success": False
        }
