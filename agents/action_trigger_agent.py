import os
import openai
import logging
import json
from dotenv import load_dotenv
from cpq.models import CustomObject, CustomField, CustomRecord
from django.db.models import Q

# Session Context Helpers
from .utils.session_context_helpers.session_context_helpers import get_session_context

# LLM Helpers
from .utils.action_trigger.llm_helpers import extract_action_triggers_with_llm

from .utils.action_trigger.handle_helpers import handle_create_action_trigger

# General Helpers
from .utils.action_trigger.general_helpers import get_action_triggers_details, action_trigger_creation_type_with_llm, get_cpq_model_schema

def action_trigger_agent(user, action, user_message, session_data):

    action_map = {
        "CreateActionTrigger": create_action_trigger,
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user, user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request."}

def create_action_trigger(user, user_message, session_data):
    """Create action trigger"""

    logging.info("🔧 Creating action trigger...\n\n")

    current_state, previous_summary = get_session_context("create_action_trigger", session_data)

    first_llm_result = action_trigger_creation_type_with_llm(
        user_message=user_message
    )

    if first_llm_result["mode"] == "graphic":
        
        return {
            "message": "Opening graphic mode...",
            "openGraphicBuilder": True,
            "cpq_model_schema": get_cpq_model_schema()
        }
    

    # --- Initial call to LLM to extract action triggers ---
    llm_result = extract_action_triggers_with_llm(
        user=user,
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary,
        action = first_llm_result["action"]
    )

    print(f"\n\nLLM result: {llm_result}\n\n")

    # print(f"\n\nLLM result: {llm_result}\n\n")

    completed_action_triggers = []
    remaining_action_triggers = []

    for line_item in llm_result["create_action_trigger"]:
        if line_item.get("completed"):
            completed_action_triggers.append(line_item["data"])
        else:
            remaining_action_triggers.append(line_item)

    # Guardar solo los incompletos en session state
    session_data["state"]["create_action_trigger"] = remaining_action_triggers

    # Return if not any completed products
    if not completed_action_triggers:
        return {
            "message": llm_result["agent_message"],
            "session_summary": llm_result["summary"]
        }
    
    response_message = ""

    # ✅ Handle create inclusion rule
    response_message, action_triggers_created = handle_create_action_trigger(user, completed_action_triggers, response_message)

    #log_action_usage("CreateInclusionRule", user, "Quote", quote.name)
    # ✅ Update quote (subtotal, discounts fields and net amount)
    #quote.save()

    action_triggers_details = get_action_triggers_details(action_triggers_created)

    if action_triggers_created:

        return {
            "message": response_message,
            "action_triggers_details": action_triggers_details,
            "hiddenMessage": "True"
        }
    
    else:
        return {
            "message": response_message
        }