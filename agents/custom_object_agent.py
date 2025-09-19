import os
import openai
import logging
import json
from dotenv import load_dotenv
from cpq.models import CustomObject, CustomField, CustomRecord
from decimal import Decimal
from django.db.models import Q
from django.forms.models import model_to_dict

#LLM helpers
from agents.utils.custom_object_agent.llm_helpers import extract_custom_object_data, extract_custom_objects, extract_custom_objects_updates, extract_custom_objects_deletes, extract_custom_fields, extract_custom_fields_updates, extract_custom_fields_deletes, extract_custom_records_updates, extract_custom_records_deletes

# Session Context Helpers
from .utils.orchestrator.context_handle_helpers import save_or_update_conversation_context, make_session_context

# Handle Helpers
from .utils.custom_object_agent.handle_helpers import handle_custom_object_creation, handle_custom_object_updates, handle_custom_object_deletes, handle_custom_fields_creation, handle_custom_fields_updates, handle_custom_field_deletes, handle_custom_object_records, handle_custom_records_updates, handle_custom_record_deletes


# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

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


    # ✅ Extract custom object details with LLM
    extracted_custom_objects = extract_custom_objects(user_message)

    if not extracted_custom_objects:
        session_context["item_index"] = 1
        session_context["extracted"] = "Something went wrong when LLM trying to extract custom objects data."
        agent_response = f"An error occurred while extracting your custom objects data. Please try again."
        save_or_update_conversation_context(session_context, agent_response)
        return {
        "message": "⚠️ AgentCPQ: An error occurred while extracting your custom objects data. Please try again."
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, custom_objects_created = handle_custom_object_creation(user, extracted_custom_objects, response_message, session_context)

    # ✅ Return
    if not custom_objects_created:
        return {
            "message": f"No custom objects were created. <br><br>{response_message}",
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
        "message": "⚠️ AgentCPQ: An error occurred while extracting your custom objects data to update. Please try again."
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, custom_objects_updated = handle_custom_object_updates(user, extracted_custom_objects_updates, response_message, session_context)

    # ✅ Return
    if not custom_objects_updated:
        return {
            "message": f"No custom objects were updated. <br><br>{response_message}",
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
        "message": "⚠️ AgentCPQ: An error occurred while extracting your custom objects data to delete. Please try again."
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, custom_objects_deleted = handle_custom_object_deletes(user, extracted_custom_objects_deletes, response_message, session_context)

    # ✅ Return
    if not custom_objects_deleted:
        return {
            "message": f"No custom objects were deleted. <br><br>{response_message}",
            "temporaryMessage": True
        } 
    
    return {
        "message": response_message,
        "temporaryMessage": True
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
        return {
        "message": "⚠️ AgentCPQ: An error occurred while extracting your custom fields data. Please try again."
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
    session_context = make_session_context(user, "EditCustomField", "custom_object_agent", session_data, user_message)

    logging.info("🔧 Editing custom field...\n\n")

    # ✅ Get all the custom objects
    custom_objects = CustomObject.objects.values_list("name", flat=True)
    custom_fields = CustomField.objects.values_list("name", flat=True)

    extracted_custom_fields_updates = extract_custom_fields_updates(user_message, custom_objects, custom_fields)

    if not extracted_custom_fields_updates:
        session_context["item_index"] = 1
        session_context["extracted"] = "Something went wrong when LLM trying to extract custom fields data."
        agent_response = f"An error occurred while extracting your custom fields data. Please try again."
        save_or_update_conversation_context(session_context, agent_response)
        return {
        "message": "⚠️ AgentCPQ: An error occurred while extracting your custom fields data to update. Please try again."
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, custom_fields_updated = handle_custom_fields_updates(user, extracted_custom_fields_updates, response_message, session_context)

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
        "message": "⚠️ AgentCPQ: An error occurred while extracting your custom fields data to delete. Please try again."
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

def create_custom_record(user, user_message, session_data):
    """Create custom object record"""
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
            "message": "⚠️ Hmm, something went wrong while processing your request. Mind trying again?"
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
            "message": "⚠️ Hmm, something went wrong while processing your request. Mind trying again?"
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
        "message": "⚠️ AgentCPQ: An error occurred while extracting your custom records data to delete. Please try again."
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