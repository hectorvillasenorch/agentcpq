from cpq.models import CustomObject, CustomField, CustomRecord
import json
import logging

# Session Context Helpers
from ..orchestrator.context_handle_helpers import save_or_update_conversation_context

# Record Helpers
from .record_helpers import create_custom_record_and_values, update_custom_record_and_values, delete_custom_record

from .record_helpers import save_custom_object, update_custom_object, delete_custom_object, save_custom_field, update_custom_field, delete_custom_field

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
            response_message += f"{response.get('message')}<br><br>"
            objects_created.append(object_payload)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            agent_response = f"Something were wrong when trying to create custom object. Error: {error_msg}"
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, objects_created

def handle_custom_object_updates(user, extracted_custom_objects_updates, response_message, session_context):

    objects_updated = []

    for index, custom_object in enumerate(extracted_custom_objects_updates, start=1):
        label = custom_object.get("label", None)
        updates = custom_object.get("updates", None)

        name = label.lower().replace(" ", "_") + "__c" if label else None

        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = custom_object

        # ✅ Format response message
        response_message += f"<b>🔄 <u>Custom Object Update Request #{index}</u> 🔄</b><br><br>"

        if label is None:
            agent_response = "Label is not specify on user message."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Oops! It looks like you didn’t provide a label for the custom object to update. Could you tell me what you’d like to name this field?<br><br>"
            continue

        # Check if custom object exists
        try:
            custom_object = CustomObject.objects.get(name=name)
        except CustomObject.DoesNotExist:
            agent_response = f"A custom object with the label '{label}' does not exist."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ Heads up! A custom object named <strong>{label}</strong> does not exist. "
                "Please make sure you're referencing a valid custom object to update.<br><br>"
            )
            continue

        # ✅ Format response message
        response_message += f"<b>🧩 <u>{custom_object.label}</u> 🧩</b><br>"


        if updates is None:
            agent_response = "No label or description provided in the user message."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ It looks like you didn’t include a new <strong>label</strong> or <strong>description</strong> "
                f"to update <u>{custom_object.label}</u>. Please tell me what you’d like to change.<br><br>"
            )
            continue

        label_to_update = updates.get("label", None)
        description_to_update = updates.get("description", None)

        if label_to_update is None and description_to_update is None:
            agent_response = "No new values for label or description were provided."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ I see that you’re trying to update the custom object {custom_object.label}, but you didn’t specify a new "
                "<strong>label</strong> or <strong>description</strong>.<br>"
                "Please let me know which of these you’d like to update.<br><br>"
            )
            continue

        name_to_update = label_to_update.lower().replace(" ", "_") + "__c" if label_to_update else None

        if label_to_update:
            response_message += f"🧾 Name: {name_to_update}<br>"
            response_message += f"🏷️ Label: {label_to_update}<br>"
        if description_to_update:
            response_message += f"📝 Description: {description_to_update}<br>"

        object_payload = {
            "name": custom_object.name,
            "label_to_update": label_to_update if label_to_update else None,
            "name_to_update": name_to_update if name_to_update else None,
            "description_to_update": description_to_update if description_to_update else None
        }

        # Call the save function
        response = update_custom_object(json.dumps(object_payload), user=user)

        if response.get("success"):
            response_message += f"{response.get('message')}<br><br>"
            objects_updated.append(object_payload)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            agent_response = f"Something were wrong when trying to update custom object. Error: {error_msg}"
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, objects_updated

def handle_custom_object_deletes(user, extracted_custom_objects_deletes, response_message, session_context):

    objects_deleted = []

    for index, custom_object in enumerate(extracted_custom_objects_deletes, start=1):
        label = custom_object.get("label", None)

        name = label.lower().replace(" ", "_") + "__c" if label else None

        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = custom_object

        # ✅ Format response message
        response_message += f"<b>🔄 <u>Custom Object Delete Request #{index}</u> 🔄</b><br>"

        if label is None:
            agent_response = "Label is not specify on user message."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Oops! It looks like you didn’t provide a label for the custom object to delete. Could you tell me what you’d like to name this field?<br><br>"
            continue

        # Check if custom object exists
        try:
            custom_object = CustomObject.objects.get(name=name)
        except CustomObject.DoesNotExist:
            agent_response = f"A custom object with the label '{label}' does not exist."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ Heads up! A custom object named <strong>{label}</strong> does not exist. "
                "Please make sure you're referencing a valid custom object to delete.<br><br>"
            )
            continue

        # ✅ Format response message
        response_message += f"<b>🧩 <u>{custom_object.label}</u> 🧩</b><br>"

        object_payload = {
            "name": custom_object.name
        }

        # Call the save function
        response = delete_custom_object(json.dumps(object_payload))

        if response.get("success"):
            response_message += f"{response.get('message')}<br><br>"
            objects_deleted.append(object_payload)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            agent_response = f"Something were wrong when trying to delete custom object. Error: {error_msg}"
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, objects_deleted

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

        label = label.title()

        if not custom_object_name and not object_type:
            response_message += f"<b>🔄 Custom Field Request #{index} 🔄</b><br>"
            response_message += (
                "⚠️ Oops! It looks like you didn’t specify which custom or standard object this field belongs to. "
                "Could you please let me know the name of the object so I can proceed?<br><br>"
            )
            continue

        response_message += f"<b>🔄 Custom Field Request #{index} 🔄</b><br>"

        if custom_object_name:

            if not custom_object_name.endswith('__c'):
                custom_object_name.lower().replace(" ", "_") + "__c" if custom_object_name else None


            # Validate if user specify an custom object name
            try:
                co_obj = CustomObject.objects.get(name=custom_object_name)
            except CustomObject.DoesNotExist:
                response_message += f"⚠️ Oops! It looks like you didn’t specify a custom object for this custom field(s). Could you tell me which object it should belong to?<br><br>"
                continue

            # ✅ Format response message
            if index == 1 and custom_object_name:
                response_message += f"<b>🧩 <u>Fields for {co_obj.label}</u>🧩</b><br><br>"

            if custom_object_name and not CustomObject.objects.filter(name=custom_object_name).exists():
                response_message += (
                    f"⚠️ Oops! The custom object <strong>{custom_object_name}</strong> doesn't exist yet. "
                    "Please create it first or check for typos before adding fields to it.<br><br>"
                )
                continue

            # Check if custom field exists for this specific custom object
            if CustomField.objects.filter(name=name, custom_object=co_obj).exists():
                response_message += (
                    f"⚠️ Heads up! A custom field named <strong>{name}</strong> already exists for {co_obj.label} custom object. "
                    "Please choose a different name for this new field.<br><br>"
                )
                continue

        elif object_type:
            valid_object_types = [
                "Activity", "Lead", "Contact", "Account",
                "Opportunity", "Product", "Quote", "QuoteLine"
            ]

            if object_type not in valid_object_types:
                response_message += (
                    "⚠️ The object type must be one of: "
                    "<strong>Activity</strong>, <strong>Lead</strong>, "
                    "<strong>Contact</strong>, <strong>Account</strong>, "
                    "<strong>Opportunity</strong>, <strong>Product</strong>, "
                    "<strong>Quote</strong>, or <strong>QuoteLine</strong>."
                )

             # Check if custom field exists for this specific custom object
            if CustomField.objects.filter(name=name, object_type=object_type).exists():
                response_message += (
                    f"⚠️ Heads up! A custom field named <strong>{name}</strong> already exists for {object_type} standard object. "
                    "Please choose a different name for this new field.<br><br>"
                )
                continue


        if label is None:
            response_message += f"⚠️ Oops! It looks like you didn’t provide a label for the custom field. Could you tell me what you’d like to name this field?<br><br>"
            continue

        if not crm:
            crm = "AgentCPQ"

        if crm and crm not in ["AgentCPQ", "HubSpot", "Salesforce"]:
            response_message += (
                "⚠️ The CRM must be <strong>AgentCPQ</strong>, "
                "<strong>HubSpot</strong>, or <strong>Salesforce</strong>."
            )
            continue


        if data_type == "dropdown" and options is None:
            response_message += (
                f"⚠️ The dropdown field <strong>{label}</strong> doesn't include any options. "
                "Please specify the choices you'd like to include.<br><br>"
            )
            continue

        if not required:
            required = False

        field_payload = {
            "label": label,
            "name": name,
            "crm": crm if crm else "AgentCPQ",
            "data_type": data_type if data_type else "text",
            "object_type": object_type if custom_object_name is None else custom_object_name,
            "required": required if required else False,
            "custom_object_name": custom_object_name if custom_object_name else None,
            "lookup_model": lookup_model if lookup_model else "admin.Logentry",
            "options": options if options else None
        }

        # Call the save function
        response = save_custom_field(json.dumps(field_payload), user=user)

        if response.get("success"):
            response_message += f"{response.get('message')}<br><br>"
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

def handle_custom_fields_updates(user, extracted_custom_fields_updates, response_message, session_context):

    objects_updated = []

    for index, custom_field in enumerate(extracted_custom_fields_updates, start=1):

        target_field_label = custom_field.get("target_field_label", None)
        target_custom_object = custom_field.get("target_custom_object", None)
        target_default_object = custom_field.get("target_default_object", None)
        updates = custom_field.get("updates", None)

        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = target_custom_object

        # ✅ Format response message
        response_message += f"<b>🔄 <u>Custom Field Update Request #{index}</u> 🔄</b><br>"

        target_field_name = target_field_label.lower().replace(" ", "_") + "__c" if target_field_label else None

        if target_field_label is None:
            agent_response = "Target field label was not specified in the user message."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                "⚠️ Oops! It looks like you didn’t provide the name of the field you want to update. "
                "Could you tell me which field you'd like to modify?<br><br>"
            )
            continue

        if target_custom_object is None and target_default_object is None:
            agent_response = "Target object was not specified in the user message."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                "⚠️ Oops! It looks like you didn’t specify which object this field belongs to. "
                "Could you let me know the name of the object?<br><br>"
            )
            continue


        if target_custom_object:
            if not target_custom_object.endswith('__c'):
                target_custom_object = target_custom_object.lower().replace(" ", "_") + "__c" if target_custom_object else None

            try:
                custom_object = CustomObject.objects.get(name=target_custom_object)
            except CustomObject.DoesNotExist:
                agent_response = f"A custom object with the label '{target_custom_object}' does not exist."
                save_or_update_conversation_context(session_context, agent_response)
                response_message += (
                    f"⚠️ Heads up! A custom object named <b>{target_custom_object}</b> does not exist. "
                    "Please make sure you're referencing a valid custom object to update the field.<br><br>"
                )
                continue

            # Check if custom field exists in the custom object
            try:
                custom_field = CustomField.objects.get(name=target_field_name, custom_object=custom_object)
            except CustomField.DoesNotExist:
                agent_response = f"A custom field with the label '{target_field_label}' does not exist."
                save_or_update_conversation_context(session_context, agent_response)
                response_message += (
                    f"⚠️ Heads up! A custom field named <b>{target_field_label}</b> does not exist in custom object {custom_object.label}. "
                    "Please make sure you're referencing a valid custom field to update.<br><br>"
                )
                continue

        allowed_object_types = [
            "activity", "lead", "contact", "account",
            "opportunity", "product", "quote", "quoteline"
        ]

        if target_default_object:

            if target_default_object not in allowed_object_types:
                agent_response = f"A default object with the label '{target_default_object}' does not exist."
                save_or_update_conversation_context(session_context, agent_response)
                allowed_list_str = ", ".join([obj.capitalize() for obj in allowed_object_types])
                response_message += (
                    f"⚠️ Heads up! A default object named <strong>{target_default_object}</strong> does not exist. "
                    f"Please make sure you're referencing a valid default object to update the field. "
                    f"Allowed default objects are: <em>{allowed_list_str}</em>.<br><br>"
                )
                continue

            # Check if custom field exists in the default object
            try:
                custom_field = CustomField.objects.get(name=target_field_name, object_type=target_default_object)
            except CustomField.DoesNotExist:
                agent_response = f"A custom field with the label '{target_field_label}' does not exist."
                save_or_update_conversation_context(session_context, agent_response)
                response_message += (
                    f"⚠️ Heads up! A custom field named <b>{target_field_label}</b> does not exist in default object <b>{target_default_object}</b>. "
                    "Please make sure you're referencing a valid custom field to update.<br><br>"
                )
                continue


        # ✅ Format response message
        response_message += f"<b>🧩 <b>{custom_field.label}</b> in <b>{custom_object.label if custom_object else target_default_object}</b> object. 🧩</b><br>"

        if updates is None:
            agent_response = f"No update data provided for field '{custom_field.label}' in object '{custom_object.label if custom_object else target_default_object}'."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ It looks like you didn’t include any data to update the field <b>{custom_field.label}</b>. "
                f"Please tell me what values you'd like to change (e.g., label, crm, object type, required.).<br><br>"
            )
            continue

        label_to_update = updates.get("label", None)
        crm_to_update = updates.get("crm", None)
        object_type_to_update = updates.get("object_type", None)
        required_to_update = updates.get("required", None)
        custom_object_to_update = updates.get("custom_object", None)
        data_type_to_update = updates.get("data_type", None)
        options_to_update = updates.get("options", None)

        allowed_crm_values = ["AgentCPQ", "HubSpot", "Salesforce"]


        if crm_to_update and crm_to_update not in allowed_crm_values:
            agent_response = (
                f"Invalid CRM value: '{crm_to_update}'. Must be one of: {', '.join(allowed_crm_values)}."
            )
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ The value <b>{crm_to_update}</b> is not valid for the field <b>CRM</b>. "
                f"Please choose one of the following: <b>{', '.join(allowed_crm_values)}</b>.<br><br>"
            )
            crm_to_update = None


        if object_type_to_update:
            object_type_normalized = object_type_to_update.lower()
            if object_type_normalized not in allowed_object_types:
                agent_response = (
                    f"Invalid object type: '{object_type_to_update}'. "
                    f"Must be one of: {', '.join(ot.title() for ot in allowed_object_types)}."
                )
                save_or_update_conversation_context(session_context, agent_response)
                response_message += (
                    f"⚠️ The value <b>{object_type_to_update}</b> is not valid for the field <b>Object Type</b>. "
                    f"Please choose one of the following: "
                    f"<b>{', '.join(ot.title() for ot in allowed_object_types)}</b>.<br><br>"
                )
                object_type_to_update = None

        if required_to_update is not None:
            if isinstance(required_to_update, str):
                normalized_required = required_to_update.strip().lower()
                if normalized_required == "true":
                    required_to_update = True
                elif normalized_required == "false":
                    required_to_update = False
                else:
                    agent_response = (
                        f"Invalid value for 'required': '{required_to_update}'. Must be either 'true' or 'false'."
                    )
                    save_or_update_conversation_context(session_context, agent_response)
                    response_message += (
                        f"⚠️ The value <b>{required_to_update}</b> is not valid for the field <b>Required</b>. "
                        f"Please use either <b>true</b> or <b>false</b>.<br><br>"
                    )
                    continue
            elif not isinstance(required_to_update, bool):
                agent_response = (
                    f"Invalid type for 'required': {required_to_update}. Must be a boolean value."
                )
                save_or_update_conversation_context(session_context, agent_response)
                response_message += (
                    f"⚠️ The value for <b>Required</b> must be either <b>true</b> or <b>false</b>.<br><br>"
                )
                continue

        if custom_object_to_update:
            if not custom_object_to_update.endswith('__c'):
                custom_object_to_update = custom_object_to_update.lower().replace(" ", "_") + "__c" if custom_object_to_update else None

            # Check if custom object to update exists
            try:
                custom_object_to_update_validation = CustomObject.objects.get(name=custom_object_to_update)
            except CustomObject.DoesNotExist:
                available_objects = CustomObject.objects.values_list("label", flat=True)
                available_objects_display = ", ".join(available_objects)

                agent_response = (
                    f"The destination custom object '{custom_object_to_update}' does not exist. "
                    f"Available objects: {available_objects_display}."
                )
                save_or_update_conversation_context(session_context, agent_response)

                response_message += (
                    f"⚠️ The custom object <b>{custom_object_to_update}</b> does not exist. "
                    f"If you're trying to move this field from <b>{custom_object.label}</b> to another object, "
                    f"please make sure the destination exists.<br>"
                    f"➔ Available custom objects: <b>{available_objects_display}</b><br><br>"
                )
                custom_object_to_update = None
        else:
            custom_object_to_update = None

        allowed_data_types = ["Text", "Number", "Date", "Boolean", "Dropdown", "Text Area", "Look Up"]

        if data_type_to_update and data_type_to_update not in allowed_data_types:
            valid_types_display = ", ".join(allowed_data_types)

            agent_response = (
                f"The data type '{data_type_to_update}' is not valid. "
                f"It must be one of: {valid_types_display}."
            )
            save_or_update_conversation_context(session_context, agent_response)

            response_message += (
                f"⚠️ The value <b>{data_type_to_update}</b> is not valid for the field type. "
                f"Valid data types are: <b>{valid_types_display}</b>.<br><br>"
            )
            data_type_to_update = None

        if data_type_to_update and data_type_to_update in ["Dropdown", "Look Up"]:
            if not isinstance(options_to_update, list):
                agent_response = (
                    f"When the data type is '{data_type_to_update}', the <strong>options</strong> field must be a list "
                    "containing the allowed values for the field."
                )
                save_or_update_conversation_context(session_context, agent_response)

                response_message += (
                    f"⚠️ Since the data type is <b>{data_type_to_update}</b>, you must provide a valid list of options. "
                    f"For example: <code>[\"Option 1\", \"Option 2\"]</code>.<br><br>"
                )
                data_type_to_update = None
                options_to_update = None


        if all(
            value is None for value in [
                label_to_update,
                crm_to_update,
                object_type_to_update,
                required_to_update,
                custom_object_to_update,
                data_type_to_update,
                options_to_update,
            ]
        ):
            agent_response = f"No update data provided for field '{custom_field.label}' in object '{custom_object.label}'."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ There are no data to update for the custom field <b>{custom_field.label}</b>.<br><br>"
            )
            continue


        name_to_update = label_to_update.lower().replace(" ", "_") + "__c" if label_to_update else None

        if label_to_update:
            response_message += f"🧾 Name: {name_to_update}<br>"
            response_message += f"🏷️ Label: {label_to_update}<br>"
        if crm_to_update:
            response_message += f"🗃️ CRM: {crm_to_update}<br>"
        if object_type_to_update:
            response_message += f"🧩 Object Type: {object_type_to_update}<br>"
        if required_to_update:
            response_message += f"❗ Required: {required_to_update}<br>"
        if custom_object_to_update:
            response_message += f"🧱 Custom Object: {custom_object_to_update}<br>"
        if data_type_to_update:
            response_message += f"🔣 Data Type: {data_type_to_update}<br>"
        if options_to_update:
            response_message += f"🧾 Options: {options_to_update}<br>"

        response_message += "<br>"

        field_payload = {
            "target_field_label": custom_field.name,
            "target_custom_object": custom_object.name if custom_object else None,
            "target_default_object": target_default_object if target_default_object else None,
            "updates": {
                "label_to_update": label_to_update,
                "crm_to_update": crm_to_update,
                "object_type_to_update": object_type_to_update,
                "required_to_update": required_to_update,
                "custom_object_to_update_name": custom_object_to_update,
                "data_type_to_update": data_type_to_update,
                "options_to_update": options_to_update,
            }
        }

        # Call the save function
        response = update_custom_field(json.dumps(field_payload), user=user)

        if response.get("success"):
            response_message += f"{response.get('message')}<br><br>"
            objects_updated.append(field_payload)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            agent_response = f"Something were wrong when trying to update custom field. Error: {error_msg}"
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, objects_updated

def handle_custom_field_deletes(user, extracted_custom_fields_deletes, response_message, session_context):

    fields_deleted = []

    for index, custom_field in enumerate(extracted_custom_fields_deletes, start=1):

        field_label = custom_field.get("field_label", None)
        custom_object_label = custom_field.get("custom_object_label", None)
        default_object_label = custom_field.get("default_object_label", None)

        field_name = field_label.lower().replace(" ", "_") + "__c" if field_label else None

        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = custom_field

        # ✅ Format response message
        response_message += f"<b>🔄 <u>Custom Field Delete Request #{index}</u> 🔄</b><br>"

        if field_label is None:
            agent_response = "Label is not specify on user message."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Oops! It looks like you didn’t provide the label for the custom field to delete. Could you tell me what you’d like to name this field?<br><br>"
            continue

        # If object is custom
        if custom_object_label and default_object_label is None:
            # Check if custom object exists
            try:
                target_custom_object_name = custom_object_label.lower().replace(" ", "_") + "__c" if custom_object_label else None
                custom_object = CustomObject.objects.get(name=target_custom_object_name)
            except CustomObject.DoesNotExist:
                agent_response = f"A custom object with the label '{custom_object_label}' does not exist."
                save_or_update_conversation_context(session_context, agent_response)
                response_message += (
                    f"⚠️ Heads up! A custom object named <b>{custom_object_label}</b> does not exist. "
                    "Please make sure you're referencing a valid custom object to delete.<br><br>"
                )
                continue

            try:
                custom_field = CustomField.objects.get(name=field_name, custom_object=custom_object)
            except CustomField.DoesNotExist:
                agent_response = f"A custom field with the label '{field_label}' does not exist."
                save_or_update_conversation_context(session_context, agent_response)
                response_message += (
                    f"⚠️ Heads up! A custom field named <b>{field_label}</b> does not exist or is not part of the custom object <b>{custom_object.label}</b>."
                    "Please make sure you're referencing a valid custom field to delete.<br><br>"
                )
                continue
        elif default_object_label:
            if custom_object_label:
                custom_object_label = None

            allowed_default_objects = [
                "Activity",
                "Lead",
                "Contact",
                "Account",
                "Opportunity",
                "Product",
                "Quote",
                "QuoteLine"
            ]

            allowed_default_objects_normalized = [obj.lower().strip() for obj in allowed_default_objects]

            if default_object_label and default_object_label.lower().strip() not in allowed_default_objects_normalized:
                agent_response = (
                    f"Invalid default object: '{default_object_label}'. "
                    f"It must be one of the following: {', '.join(allowed_default_objects)}."
                )
                save_or_update_conversation_context(session_context, agent_response)
                response_message += (
                    f"⚠️ The provided default object <b>{default_object_label}</b> "
                    f"is not valid. Please choose one of the following: {', '.join(allowed_default_objects)}.<br><br>"
                )
                continue

            try:
                custom_field = CustomField.objects.get(name=field_name, object_type=default_object_label)
                custom_object = None
            except CustomField.DoesNotExist:
                agent_response = f"A custom field with the label '{field_label}' does not exist."
                save_or_update_conversation_context(session_context, agent_response)
                response_message += (
                    f"⚠️ Heads up! A custom field named <b>{field_label}</b> does not exist or is not part of the default object."
                    f" Please make sure you're referencing a valid custom field to delete. "
                    f"The default object must be one of the following: {', '.join(allowed_default_objects)}.<br><br>"
                )
                continue


        # ✅ Format response message
        response_message += f"<b>🧩 <u>{custom_field.label}</u> 🧩</b><br>"

        field_payload = {
            "name": custom_field.name,
            "custom_object_name": custom_object.name if custom_object else None,
            "default_object_name": default_object_label if default_object_label else None
        }

        # Call the delete function
        response = delete_custom_field(json.dumps(field_payload))

        if response.get("success"):
            response_message += f"{response.get('message')}<br><br>"
            fields_deleted.append(field_payload)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            agent_response = f"Something were wrong when trying to delete custom field. Error: {error_msg}"
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, fields_deleted

def handle_custom_object_records(user, extracted_custom_objects_records, response_message, session_context):

    records_created = []

    for index, custom_object_data in enumerate(extracted_custom_objects_records, start=1):
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
                f"⚠️ Got it — you’d like to create a record for <strong>{custom_object_name.replace('__c', '')}</strong>, "
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

        # Safety: ensure modified_by is stamped on the parent record
        try:
            record.modified_by = user
            record.save(update_fields=["modified_by", "updated_at"])
        except Exception:
            logging.warning("Failed to update modified_by on record %s: %s", record.id, str(e))
            pass

        records_created.append(record)
        response_message += (
            f"✅ Successfully created a new record for <strong>{custom_object.label or custom_object.name}</strong>.<br><br>"
        )

    return response_message, records_created

def handle_custom_records_updates(user, extracted_custom_records_updates, response_message, session_context):

    records_updated = []

    for index, custom_record in enumerate(extracted_custom_records_updates, start=1):
        record_identifier = custom_record.get("record_identifier", None)
        values = custom_record.get("values", None)

        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = custom_record

        # ✅ Format response message
        response_message += f"<b>🔄 <u>Custom Record Update Request #{index}</u> 🔄</b><br>"

        # ✅ General validations

        if record_identifier is None:
            agent_response = "Record identifier is not specified in the user message. Request omitted."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                "⚠️ Oops! It looks like you didn’t specify the record identifier for this request.<br>"
                "Could you please provide the exact identifier of the record you’re referring to?<br><br>"
            )
            continue

        if values is None:
            agent_response = f"Values for updating custom record {record_identifier} are not specified in the user message. Request omitted."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ Got it — you’d like to update the record with identifier <b>{record_identifier}</b>, "
                "but I didn’t see any field values to update.<br>"
                "Could you share the fields and the new values you’d like to set?<br><br>"
            )
            continue


        # ✅ Validate if Custom Record exists
        try:
            custom_record = CustomRecord.objects.get(custom_identifier=record_identifier)
        except CustomRecord.DoesNotExist:
            agent_response = f"The record with identifier {record_identifier} was not found in the database. Request omitted."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += (
                f"⚠️ I understood you want to update the record with identifier <b>{record_identifier}</b>, "
                "but I couldn’t find it in the system.<br>"
                "Could you double-check the identifier or provide the correct one?<br><br>"
            )
            continue

        # Update the existing record
        record, updated_field_values, response_message, error_message = update_custom_record_and_values(
            user, response_message, custom_record, values, session_context
        )

        # Si hay error, lo guardamos y omitimos la actualización de éxito
        if error_message:
            save_or_update_conversation_context(session_context, error_message)
            response_message += error_message
            continue

        # Si no se actualizó ningún campo, no actualizar updated_at ni updated_by, y mostrar advertencia
        if not updated_field_values:
            warning_msg = (
                f"⚠️ No fields were updated for record <b>{record_identifier}</b> because no valid changes were detected.<br><br>"
            )
            save_or_update_conversation_context(session_context, warning_msg)
            response_message += warning_msg
            continue

        # Mostrar campos actualizados
        for item in updated_field_values:
            response_message += f"🏷️ {item.field.label}: {item.value}<br>"
        response_message += "<br>"

        records_updated.append(record)
        response_message += (
            f"✅ Successfully updated the record with identifier <b>{record_identifier}</b>.<br><br>"
        )

    return response_message, records_updated

def handle_custom_record_deletes(user, extracted_custom_records_deletes, response_message, session_context):

    records_deleted = []

    for index, custom_record in enumerate(extracted_custom_records_deletes, start=1):

        record_identifier = custom_record.get("record_identifier", None)

        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = custom_record

        # ✅ Format response message
        response_message += f"<b>🔄 <u>Custom Record Delete Request #{index}</u> 🔄</b><br>"

        if record_identifier is None:
            agent_response = "Record identifier is not specify on user message."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Oops! It looks like you didn’t provide the record identifier to delete.<br><br>"
            continue

        try:
            custom_record = CustomRecord.objects.get(custom_identifier=record_identifier)
        except CustomRecord.DoesNotExist:
            agent_response = f"No record found with the identifier '{record_identifier}'. Please check the identifier and try again."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Sorry, no record was found with the identifier <b>{record_identifier}</b>.<br>Please verify the identifier and try again.<br><br>"
            continue

        # ✅ Format response message
        response_message += f"<b>🧩 <u>{custom_record.custom_identifier}</u> 🧩</b><br>"

        field_payload = {
            "record_identifier": custom_record.custom_identifier
        }

        # Call the delete function
        response = delete_custom_record(json.dumps(field_payload))

        if response.get("success"):
            response_message += f"{response.get('message')}<br><br>"
            records_deleted.append(field_payload)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            agent_response = f"Something were wrong when trying to delete custom record. Error: {error_msg}"
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"{error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, records_deleted
