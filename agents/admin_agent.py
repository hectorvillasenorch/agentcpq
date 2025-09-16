import os
import openai
import logging
import json
from dotenv import load_dotenv
from cpq.models import Quote, BusinessRule, CustomObject, EmailAlert
from decimal import Decimal
from django.db.models import Q
from django.forms.models import model_to_dict
from django.contrib.auth.models import User

#LLM helpers
from .utils.admin_agent.llm_helpers import extract_validation_rules, extract_rules_details_to_render, extract_rule_updates, extract_rule_deletes, extract_custom_object_updates

#Rules helpers
from .utils.admin_agent.rules_helpers import handle_extracted_rules_details, handle_rules_updates, handle_rules_deletes

#General helpers
from .utils.admin_agent.general_helpers import get_rules_details

# Session Context Helpers
from .utils.orchestrator.context_handle_helpers import save_or_update_conversation_context, make_session_context


# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

def admin_agent(user, action, user_message, session_data):

    action_map = {
        "UpdateCustomObject": update_custom_object,
        "CreateValidationRule": create_validation_rule,
        "ShowRules": show_rules,
        "UpdateRule": update_rule,
        "DeleteRule": delete_rule,
        "CreateEmailAlert": create_email_alert,
        "UpdateEmailAlert": update_email_alert,
        #"DeleteEmailAlert": delete_email_alert
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user, user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request."}

def update_custom_object(user, user_message, session_data):
    logging.info("🔧 Updating Custom Object...\n\n")

    # Extract update with LLM
    extraced_updates = extract_custom_object_updates(user_message)


def create_validation_rule(user, user_message, session_data):
    # 🧠 Make the session context
    session_context = make_session_context(user, "CreateValidationRule", "admin_agent", session_data, user_message)

    logging.info("🔧 Creating Validation Rule...\n\n")

    # Extract rule with LLM        
    extracted_rules = extract_validation_rules(user_message)

    if not extracted_rules:
        return {
            "message": "⚠️ The AgentCPQ assistant could not correctly extract your rules. Please try again."
        }
    
    response_message = []
    
    for index, item in enumerate(extracted_rules, start=1):
        try:
            description = item["description"]
            rule_type = item["rule_type"]
            target_type = item["target_type"]
            priority = item["priority"]
            error_message = item["error_message"]
            active = item["active"]
            conditions = item["conditions"]
            #conflicts = item["conflicts"]
        except Exception as e:
            return {
                "message": f"🚫 Error: {e}"
            }
        
        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = item

        content_message = {
            "index": index,
            "description": description,
            "rule_type": rule_type,
            "target_type": target_type,
            "priority": priority,
            "error_message": error_message,
            "active": active,
            "conditions": conditions
        }

        # DESCRIPTION: must be a string
        if not description:
            content_message["error"] = "⚠️ Missing rule description: No description was provided for this rule. Please include a descriptive description to identify it clearly."
            logging.warning("⚠️ Missing rule description: No description was provided for this rule. Please include a descriptive description to identify it clearly.")
            agent_response = f"Missing rule description: No description was provided for this rule. Please include a descriptive description to identify it clearly."
            save_or_update_conversation_context(session_context, agent_response)
            response_message.append(content_message)
            continue
        if not isinstance(description, str):
            try:
                description = str(description)
                content_message["description"] = description
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for description: expected text (string), but got {type(description).__name__}."
                logging.warning(f"⚠️ Invalid type for description: expected text (string), but got {type(description).__name__}.")
                agent_response = f"Invalid type for description: expected text (string), but got {type(description).__name__}."
                save_or_update_conversation_context(session_context, agent_response)
                response_message.append(content_message)
                continue

        # RULE_TYPE: must be a string and one of the allowed values
        valid_rule_types = {"validation", "inclusion", "exclusion"}
        if not rule_type:
            content_message["error"] = "⚠️ Missing rule type: Please specify whether this rule is validation, inclusion, or exclusion."
            logging.warning("⚠️ Missing rule type: Please specify whether this rule is validation, inclusion, or exclusion.")
            agent_response = f"Missing rule type: Please specify whether this rule is validation, inclusion, or exclusion."
            save_or_update_conversation_context(session_context, agent_response)
            response_message.append(content_message)
            continue
        if not isinstance(rule_type, str):
            try:
                rule_type = str(rule_type)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for rule_type: expected text (string), but got {type(rule_type).__name__}."
                logging.warning(f"⚠️ Invalid type for rule_type: expected text (string), but got {type(rule_type).__name__}.")
                agent_response = f"Invalid type for rule_type: expected text (string), but got {type(rule_type).__name__}."
                save_or_update_conversation_context(session_context, agent_response)
                response_message.append(content_message)
                continue
        rule_type_lower = rule_type.lower()
        if rule_type_lower not in valid_rule_types:
            content_message["error"] = f"⚠️ Invalid value for rule_type: expected one of {valid_rule_types}, but got '{rule_type}'."
            logging.warning(f"⚠️ Invalid value for rule_type: expected one of {valid_rule_types}, but got '{rule_type}'.")
            agent_response = f"Invalid value for rule_type: expected one of {valid_rule_types}, but got '{rule_type}'."
            save_or_update_conversation_context(session_context, agent_response)
            response_message.append(content_message)
            continue
        rule_type = rule_type_lower
        content_message["rule_type"] = rule_type

        # TARGET_TYPE: must be a string and one of the allowed values
        valid_target_types = {"quote", "quote_line", "product", "multiple"}
        if not target_type:
            content_message["error"] = "⚠️ Missing target type: Please define the level where this rule applies (quote, quote_line, product, or multiple)."
            logging.warning("⚠️ Missing target type: Please define the level where this rule applies (quote, quote_line, product, or multiple).")
            agent_response = f"Missing target type: Please define the level where this rule applies (quote, quote_line, product, or multiple)."
            save_or_update_conversation_context(session_context, agent_response)
            response_message.append(content_message)
            continue
        if not isinstance(target_type, str):
            try:
                target_type = str(target_type)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for target_type: expected text (string), but got {type(target_type).__name__}."
                logging.warning(f"⚠️ Invalid type for target_type: expected text (string), but got {type(target_type).__name__}.")
                agent_response = f"Invalid type for target_type: expected text (string), but got {type(target_type).__name__}."
                save_or_update_conversation_context(session_context, agent_response)
                response_message.append(content_message)
                continue
        target_type_lower = target_type.lower()
        if target_type_lower not in valid_target_types:
            content_message["error"] = f"⚠️ Invalid value for target_type: expected one of {valid_target_types}, but got '{target_type}'."
            logging.warning(f"⚠️ Invalid value for target_type: expected one of {valid_target_types}, but got '{target_type}'.")
            agent_response = f"Invalid value for target_type: expected one of {valid_target_types}, but got '{target_type}'."
            save_or_update_conversation_context(session_context, agent_response)
            response_message.append(content_message)
            continue
        target_type = target_type_lower
        content_message["target_type"] = target_type

        # PRIORITY: must be an integer
        if priority is None:
            content_message["error"] = "⚠️ Missing priority: No priority value was provided. Please assign a priority number."
            logging.warning("⚠️ Missing priority: No priority value was provided. Please assign a priority number.")
            agent_response = f"Missing priority: No priority value was provided. Please assign a priority number."
            save_or_update_conversation_context(session_context, agent_response)
            response_message.append(content_message)
            continue
        if not isinstance(priority, int):
            try:
                # Try converting numeric strings to int, e.g. "11"
                if isinstance(priority, str):
                    priority = int(priority)
                else:
                    priority = int(priority)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for priority: expected integer, but got {type(priority).__name__}."
                logging.warning(f"⚠️ Invalid type for priority: expected integer, but got {type(priority).__name__}.")
                agent_response = f"Invalid type for priority: expected integer, but got {type(priority).__name__}."
                save_or_update_conversation_context(session_context, agent_response)
                response_message.append(content_message)
                continue
        content_message["priority"] = priority

        # ERROR_MESSAGE: must be a string
        if not error_message:
            content_message["error"] = "⚠️ Missing error message: Please include a message that describes what should happen when the rule is triggered."
            logging.warning("⚠️ Missing error message: Please include a message that describes what should happen when the rule is triggered.")
            agent_response = f"Missing error message: Please include a message that describes what should happen when the rule is triggered."
            save_or_update_conversation_context(session_context, agent_response)
            response_message.append(content_message)
            continue
        if not isinstance(error_message, str):
            try:
                error_message = str(error_message)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for error_message: expected text (string), but got {type(error_message).__name__}."
                logging.warning(f"⚠️ Invalid type for error_message: expected text (string), but got {type(error_message).__name__}.")
                agent_response = f"Invalid type for error_message: expected text (string), but got {type(error_message).__name__}."
                save_or_update_conversation_context(session_context, agent_response)
                response_message.append(content_message)
                continue
        content_message["error_message"] = error_message

        # CONDITIONS: must be a dict (object)
        if not conditions:
            content_message["error"] = "⚠️ Missing conditions: Please provide the logic and fields that define when this rule is triggered."
            logging.warning("⚠️ Missing conditions: Please provide the logic and fields that define when this rule is triggered.")
            agent_response = f"Missing conditions: Please provide the logic and fields that define when this rule is triggered."
            save_or_update_conversation_context(session_context, agent_response)
            response_message.append(content_message)
            continue
        if not isinstance(conditions, dict):
            content_message["error"] = f"⚠️ Invalid type for conditions: expected an object (dict), but got {type(conditions).__name__}."
            logging.warning(f"⚠️ Invalid type for conditions: expected an object (dict), but got {type(conditions).__name__}.")
            agent_response = f"Invalid type for conditions: expected an object (dict), but got {type(conditions).__name__}."
            save_or_update_conversation_context(session_context, agent_response)
            response_message.append(content_message)
            continue

        # LOGICAL OPERATION
        logic = conditions.get("logic")
    
        if not isinstance(logic, str):
            content_message["error"] = f"⚠️ Invalid type for conditions -> logic: expected text (string), but got {type(logic).__name__}."
            logging.warning(f"⚠️ Invalid type for conditions -> logic: expected text (string), but got {type(logic).__name__}.")
            agent_response = f"Invalid type for conditions -> logic: expected text (string), but got {type(logic).__name__}."
            save_or_update_conversation_context(session_context, agent_response)
            response_message.append(content_message)
            continue

        if logic not in {"AND", "OR"}:
            content_message["error"] = f"⚠️ Invalid value for conditions -> logic: expected 'AND' or 'OR', but got '{logic}'."
            logging.warning(f"⚠️ Invalid value for conditions -> logic: expected 'AND' or 'OR', but got '{logic}'.")
            response_message.append(content_message)
            continue


        logging.info(f"\n✅ LLM returned a valid rule JSON. Ready to save the rule {description} to the database.")
        try:
            rule = BusinessRule.objects.create(
                description=description,
                rule_type=rule_type,
                target_type=target_type,
                priority=priority,
                error_message=error_message,
                active=active,
                conditions=conditions,  # conditions JSON
            )

            # Set rule's name
            rule.name = f"VR-{rule.id:05d}"
            content_message["name"] = rule.name
            rule.save()

            logging.info(f"✅ BusinessRule '{rule.name}' ('{rule.description}') saved successfully with ID {rule.id}.")
            content_message["success"] = True
            response_message.append(content_message)
        except Exception as e:
            logging.error(f"❌ Error saving Rule: {e}")
            content_message["error"] = f"❌ Error saving rule to database: {str(e)}"
            agent_response = f"Error saving rule to database: {str(e)}"
            save_or_update_conversation_context(session_context, agent_response)
            response_message.append(content_message)
            continue
        
        print(f"\n\nRule: {response_message}\n")

    return {
        "message": "Here are the rules details:",
        "validation_rules_details": response_message,
        "hiddenMessage": "True"
    }


#< ----------------- SHOW VALIDATION RULES -------------------- >

def show_rules(user, user_message, session_data):
    """Fetches and formats quote details, including quote lines, based on user input or session data."""

    # 🧠 Make the session context
    session_context = make_session_context(user, "ShowRules", "admin_agent", session_data, user_message)

    try:
        logging.info("🔄 Showing rules...")

        # Extract rules details to render
        extracted_rules_details = extract_rules_details_to_render(user_message)

        # ✅ Format the response
        handle_rules = handle_extracted_rules_details(extracted_rules_details)

        if isinstance(handle_rules, dict) and "message" in handle_rules and len(handle_rules) == 1:
            return {
                "message": handle_rules["message"]
            }
        #print(f"{handle_rules}")
        formatted_rules = get_rules_details(handle_rules)

        logging.info(f"✅ Showing rules: {formatted_rules}")

        return {
            "message": "Here are the rules details to render:",
            "rules": formatted_rules,
            "hiddenMessage": "True",
            "read_only": True
        }
    except Exception as e:
        logging.error(f"❌ Error fetching rules: {e}")
        session_context["item_index"] = 1
        session_context["extracted"] = extracted_rules_details
        agent_response = f"An unexpected error occurred while retrieving the rules: {str(e)}"
        save_or_update_conversation_context(session_context, agent_response)
        return {
            "message": f"❌ An unexpected error occurred while retrieving the rules: {str(e)}"
        }
    
def update_rule(user, user_message, session_data):
    """Updates only the modified fields in rules."""
    # 🧠 Make the session context
    session_context = make_session_context(user, "UpdateRule", "admin_agent", session_data, user_message)

    logging.info("🔧 Updating rules...\n\n")
    
        
    # ✅ Extract quote line updates with LLM
    extracted_updates = extract_rule_updates(user_message)

    if not extracted_updates:
        session_context["item_index"] = 1
        session_context["extracted"] = extracted_updates
        agent_response = f"AgentCPQ: An error occurred while extracting your updates. Please try again."
        save_or_update_conversation_context(session_context, agent_response)
        return {
        "message": "⚠️ AgentCPQ: An error occurred while extracting your updates. Please try again."
        }
    
    response_message = ""

    # ✅ Handle rules updates
    response_message, updated_rules = handle_rules_updates(extracted_updates, response_message, session_context)


    # ✅ Return
    if not updated_rules:
        return {
            "message": f"No rules were updated. <br><br>{response_message}",
            "temporaryMessage": True
        } 
    
    return {
        "message": response_message,
        "temporaryMessage": True
        }

def delete_rule(user, user_message, session_data):
    """Updates only the modified fields in rules."""
    # 🧠 Make the session context
    session_context = make_session_context(user, "DeleteRule", "admin_agent", session_data, user_message)

    logging.info("🔧 Deleting rules...\n\n")
    # ✅ Looking for active quote
    
        
    # ✅ Extract quote line updates with LLM
    extracted_updates = extract_rule_deletes(user_message)

    if not extracted_updates:
        session_context["item_index"] = 1
        session_context["extracted"] = "No data, user just wants to delete any rule."
        agent_response = f"An error occurred while extracting your updates. Please try again."
        save_or_update_conversation_context(session_context, agent_response)
        return {
        "message": "⚠️ AgentCPQ: An error occurred while extracting your updates. Please try again."
        }
    
    response_message = ""

    # ✅ Handle rules deletes
    response_message, updated_rules = handle_rules_deletes(extracted_updates, response_message, session_context)

    # ✅ Return
    if not updated_rules:
        return {
            "message": f"No rules were deleted. <br><br>{response_message}",
            "temporaryMessage": True
        } 
    
    return {
        "message": response_message,
        "temporaryMessage": True
        }

from agents.utils.admin_agent.llm_helpers import extract_email_alert_details, extract_email_alert_updates
from agents.utils.admin_agent.handle_helpers import handle_email_alerts_creation, handle_email_alerts_updates

def create_email_alert(user, user_message, session_data):
    """Create email alert"""

    # 🧠 Make the session context
    session_context = make_session_context(user, "CreateEmailAlert", "admin_agent", session_data, user_message)

    logging.info("🔧 Creating email alert...\n\n")

    # ✅ Get all the custom objects and users
    custom_objects = CustomObject.objects.values_list("name", flat=True)

    users = User.objects.values_list("username", flat=True)

    # ✅ Extract email alerts details with LLM
    extracted_email_alerts = extract_email_alert_details(user, user_message, custom_objects, users)

    if not extracted_email_alerts:
        session_context["item_index"] = 1
        session_context["extracted"] = "Something went wrong when the LLM tried to extract email alert data."
        agent_response = (
            "⚠️ An error occurred while extracting the details of your email alerts. "
            "Please make sure your message clearly specifies the alert information and try again."
        )
        save_or_update_conversation_context(session_context, agent_response)
        return {
            "message": agent_response
        }

    response_message = ""

    # ✅ Handle email alerts
    response_message, email_alerts_created = handle_email_alerts_creation(user, extracted_email_alerts, response_message, session_context)

    # ✅ Return
    if not email_alerts_created:
        return {
            "message": f"No email alerts were created. <br><br>{response_message}",
            "temporaryMessage": True
        } 
    
    return {
        "message": response_message,
        "temporaryMessage": True
        }

def update_email_alert(user, user_message, session_data):
    """Edit email alert"""
    # 🧠 Make the session context
    session_context = make_session_context(user, "UpdateEmailAlert", "admin_agent", session_data, user_message)

    logging.info("🔧 Editing email alert...\n\n")

    # ✅ Get all the custom objects and users
    custom_objects = CustomObject.objects.values_list("name", flat=True)

    users = User.objects.values_list("username", flat=True)

    email_alerts = EmailAlert.objects.filter().all()
    
    extracted_email_alerts_updates = extract_email_alert_updates(user, user_message, custom_objects, users)

    if not extracted_email_alerts_updates:
        session_context["item_index"] = 1
        session_context["extracted"] = "Something went wrong when LLM trying to extract email alert update data."
        agent_response = f"An error occurred while extracting your email alert update data. Please try again."
        save_or_update_conversation_context(session_context, agent_response)
        return {
            "message": "⚠️ AgentCPQ: An error occurred while extracting your email alert update data. Please try again."
        }


    response_message = ""

    # ✅ Handle email alerts updates
    response_message, email_alerts_updated = handle_email_alerts_updates(user, extracted_email_alerts_updates, response_message, session_context)

    # ✅ Return
    if not email_alerts_updated:
        return {
            "message": f"No email alerts were updated. <br><br>{response_message}",
            "temporaryMessage": True
        } 
    
    return {
        "message": response_message,
        "temporaryMessage": True
        }