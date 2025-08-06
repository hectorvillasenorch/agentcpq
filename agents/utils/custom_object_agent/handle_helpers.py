from cpq.models import CustomObject, CustomField
import json
import logging

# Session Context Helpers
from ..orchestrator.context_handle_helpers import save_or_update_conversation_context

# Record Helpers
from .record_helpers import create_custom_record_and_values

from .record_helpers import save_custom_object, save_custom_field

def handle_custom_object_creation(user, extracted_custom_objects, response_message, session_context):

    objects_created = []

    for index, custom_object in enumerate(extracted_custom_objects, start=1):
        label = custom_object.get("label", None)
        description = custom_object.get("description", "")

        name = label.lower().replace(" ", "_") + "__c" if label else None

        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = custom_object

        # ✅ Format response message
        response_message += f"<b>🔄 <u>Custom Object Request #{index}</u> 🔄</b><br>"

        if label is None:
            agent_response = "Label is not specify on user message."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Oops! It looks like you didn’t provide a label for the custom object. Could you tell me what you’d like to name this field?<br><br>"
            continue

        # Check if custom object exists
        if CustomObject.objects.filter(name=name).exists():
            agent_response = f"A custom object with the label '{label}' already exists."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ Heads up! A custom object named <strong>{label}</strong> already exists. "
                "Please choose a different name for this new field.<br><br>"
            )
            continue

        object_payload = {
            "label": label,
            "name": name,
            "description": description
        }

        # Call the save function
        response = save_custom_object(json.dumps(object_payload), user=user)

        if response.get("success"):
            response_message += f"{response.get("message")}<br><br>"
            objects_created.append(object_payload)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            agent_response = f"Something were wrong when trying to create custom object. Error: {error_msg}"
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, objects_created

def handle_custom_fields_creation(user, extracted_custom_fields, response_message, session_context):

    objects_created = []

    for index, custom_field in enumerate(extracted_custom_fields, start=1):
        label = custom_field.get("label", None)
        crm = custom_field.get("crm", None)
        object_type = custom_field.get("object_type", None)
        data_type = custom_field.get("data_type", None)
        required = custom_field.get("required", None)
        custom_object_name = custom_field.get("custom_object", None)
        lookup_model = custom_field.get("lookup_model", None)
        options = custom_field.get("options", None)

        name = label.lower().replace(" ", "_") + "__c" if label else None

        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = custom_field


        # Validate if user specify an custom object name
        try:
            co_obj = CustomObject.objects.get(name=custom_object_name)
        except CustomObject.DoesNotExist:
            agent_response = "Since the user didn't specify the custom object, reprocess the previously extracted data as new, including the custom object mentioned in the latest message."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"<b>🔄 Custom Field Request #{index} 🔄</b><br>"
            response_message += f"⚠️ Oops! It looks like you didn’t specify a custom object for this custom field(s). Could you tell me which object it should belong to?<br><br>"
            continue

        # ✅ Format response message
        if index == 1 and custom_object_name:
            response_message += f"<b>🧩 <u>Fields for {co_obj.label}</u>🧩</b><br>"

        response_message += f"<b>🔄 Custom Field Request #{index} 🔄</b><br>"

        if label is None:
            agent_response = "Label is not specify on user message."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Oops! It looks like you didn’t provide a label for the custom field. Could you tell me what you’d like to name this field?<br><br>"
            continue

        # Check if custom field exists
        if CustomField.objects.filter(name=name).exists():
            response_message += (
                f"⚠️ Heads up! A custom field named <strong>{name}</strong> already exists. "
                "Please choose a different name for this new field.<br><br>"
            )
            continue


        if custom_object_name and not CustomObject.objects.filter(name=custom_object_name).exists():
            agent_response = f"There's no custom object named '{custom_object_name}' in the system."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ Oops! The custom object <strong>{custom_object_name}</strong> doesn't exist yet. "
                "Please create it first or check for typos before adding fields to it.<br><br>"
            )
            continue

        if data_type == "dropdown" and options is None:
            agent_response = f"The dropdown field '{label}' is missing its options. Extract the previous data and add to options key the options that user mentionated on his message."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ The dropdown field <strong>{label}</strong> doesn't include any options. "
                "Please specify the choices you'd like to include.<br><br>"
            )
            continue

        print(f"Este es el valor de data type: {data_type}\n\n")

        field_payload = {
            "label": label,
            "name": name,
            "crm": crm if crm else "AgentCPQ",
            "data_type": data_type if data_type else "text",
            "object_type": object_type if custom_object_name is None else custom_object_name,
            "required": required if required else False,
            "custom_object_name": custom_object_name if object_type is None else None,
            "lookup_model": lookup_model if lookup_model else "admin.Logentry",
            "options": options if options else None
        }

        # Call the save function
        response = save_custom_field(json.dumps(field_payload), user=user)

        if response.get("success"):
            response_message += f"{response.get("message")}<br><br>"
            objects_created.append(field_payload)
            agent_response = f"The custom field was or were created successfully, but the user wants to create a new one. You can see the custom object on previous extracted data."
            session_context["extracted"] = {"custom_object_name": custom_object_name}
            save_or_update_conversation_context(session_context, agent_response)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            agent_response = f"Something were wrong when trying to create custom field. Error: {error_msg}"
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, objects_created

def handle_custom_object_records(user, extracted_custom_objects_records, response_message, session_context):

    records_created = []

    for index, custom_object_data in enumerate(extracted_custom_objects_records):
        custom_object_name = custom_object_data.get("custom_object_name", None)
        values = custom_object_data.get("values", None)

        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = custom_object_data

        # ✅ Format response message
        response_message += f"<b>🔄 <u>Custom Record Request #{index}</u> 🔄</b><br>"

        # ✅ General validations

        if custom_object_name is None:
            agent_response = "Custom Object label is not specify on user message. Request omitted."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                "⚠️ Oops! It looks like you didn’t specify which custom object you'd like to create a record for.<br>"
                "Could you please let me know the name of the object you're referring to?<br><br>"
            )
            continue

        if values is None:
            agent_response = f"Values for custom object {custom_object_name} is not specify on user message. Request omitted."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ Got it — you’d like to create a record for <strong>{custom_object_name.replace("__c", "")}</strong>, "
                "but I didn’t see any details to include in the record. <br>"
                "Could you share the fields and values you'd like to set?<br><br>"
            )
            continue

        # ✅ Validate if Custom Object exists
        try:
            custom_object = CustomObject.objects.get(name__iexact=custom_object_name)
        except CustomObject.DoesNotExist:
            agent_response = f"The custom object {custom_object_name} was not found on the database. Request omitted."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ I understood you want to create a record for <strong>{custom_object_name.replace('__c', '')}</strong>, "
                "but I couldn’t find that custom object in the system.<br>"
                "Could you double-check the name or let me know which object you'd like to use?<br><br>"
            )
            continue

        # ✅ Validate and create record
        record, created_field_values, response_message, error_message = create_custom_record_and_values(user, response_message, custom_object, values, session_context)

        if error_message:
            save_or_update_conversation_context(session_context, error_message)
            continue

        if created_field_values:
            for item in created_field_values:
                response_message += f"🏷️ {item.field.label}: {item.value}<br>"
            
            response_message += "<br>"
        
        records_created.append(record)
        response_message += (
            f"✅ Successfully created a new record for <strong>{custom_object.label or custom_object.name}</strong>.<br><br>"
        )

    return response_message, records_created

