import os
import openai
import logging
import json
from dotenv import load_dotenv
from cpq.models import Quote, BusinessRule
from decimal import Decimal
from django.db.models import Q
from django.forms.models import model_to_dict

#LLM helpers
from .utils.admin_agent.llm_helpers import extract_validation_rules


# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
#OPENAI_MODEL = "gpt-3.5-turbo"
OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

def admin_agent(action, user_message, session_data):

    action_map = {
        "CreateValidationRule": create_validation_rule
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request."}


def create_validation_rule(user_message, session_data):
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
            name = item["name"]
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

        content_message = {
            "index": index,
            "name": name,
            "rule_type": rule_type,
            "target_type": target_type,
            "priority": priority,
            "error_message": error_message,
            "active": active,
            "conditions": conditions
        }

        #if conflicts:
        #    content_message["error"] = conflicts
        #    response_message.append(content_message)
        #    continue

        # NAME: must be a string
        if not name:
            content_message["error"] = "⚠️ Missing rule name: No name was provided for this rule. Please include a descriptive name to identify it clearly."
            logging.warning("⚠️ Missing rule name: No name was provided for this rule. Please include a descriptive name to identify it clearly.")
            response_message.append(content_message)
            continue
        if not isinstance(name, str):
            try:
                name = str(name)
                content_message["name"] = name
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for name: expected text (string), but got {type(name).__name__}."
                logging.warning(f"⚠️ Invalid type for name: expected text (string), but got {type(name).__name__}.")
                response_message.append(content_message)
                continue

        # RULE_TYPE: must be a string and one of the allowed values
        valid_rule_types = {"validation", "inclusion", "exclusion"}
        if not rule_type:
            content_message["error"] = "⚠️ Missing rule type: Please specify whether this rule is validation, inclusion, or exclusion."
            logging.warning("⚠️ Missing rule type: Please specify whether this rule is validation, inclusion, or exclusion.")
            response_message.append(content_message)
            continue
        if not isinstance(rule_type, str):
            try:
                rule_type = str(rule_type)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for rule_type: expected text (string), but got {type(rule_type).__name__}."
                logging.warning(f"⚠️ Invalid type for rule_type: expected text (string), but got {type(rule_type).__name__}.")
                response_message.append(content_message)
                continue
        rule_type_lower = rule_type.lower()
        if rule_type_lower not in valid_rule_types:
            content_message["error"] = f"⚠️ Invalid value for rule_type: expected one of {valid_rule_types}, but got '{rule_type}'."
            logging.warning(f"⚠️ Invalid value for rule_type: expected one of {valid_rule_types}, but got '{rule_type}'.")
            response_message.append(content_message)
            continue
        rule_type = rule_type_lower
        content_message["rule_type"] = rule_type

        # TARGET_TYPE: must be a string and one of the allowed values
        valid_target_types = {"quote", "quote_line", "product", "multiple"}
        if not target_type:
            content_message["error"] = "⚠️ Missing target type: Please define the level where this rule applies (quote, quote_line, product, or multiple)."
            logging.warning("⚠️ Missing target type: Please define the level where this rule applies (quote, quote_line, product, or multiple).")
            response_message.append(content_message)
            continue
        if not isinstance(target_type, str):
            try:
                target_type = str(target_type)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for target_type: expected text (string), but got {type(target_type).__name__}."
                logging.warning(f"⚠️ Invalid type for target_type: expected text (string), but got {type(target_type).__name__}.")
                response_message.append(content_message)
                continue
        target_type_lower = target_type.lower()
        if target_type_lower not in valid_target_types:
            content_message["error"] = f"⚠️ Invalid value for target_type: expected one of {valid_target_types}, but got '{target_type}'."
            logging.warning(f"⚠️ Invalid value for target_type: expected one of {valid_target_types}, but got '{target_type}'.")
            response_message.append(content_message)
            continue
        target_type = target_type_lower
        content_message["target_type"] = target_type

        # PRIORITY: must be an integer
        if priority is None:
            content_message["error"] = "⚠️ Missing priority: No priority value was provided. Please assign a priority number."
            logging.warning("⚠️ Missing priority: No priority value was provided. Please assign a priority number.")
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
                response_message.append(content_message)
                continue
        content_message["priority"] = priority

        # ERROR_MESSAGE: must be a string
        if not error_message:
            content_message["error"] = "⚠️ Missing error message: Please include a message that describes what should happen when the rule is triggered."
            logging.warning("⚠️ Missing error message: Please include a message that describes what should happen when the rule is triggered.")
            response_message.append(content_message)
            continue
        if not isinstance(error_message, str):
            try:
                error_message = str(error_message)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for error_message: expected text (string), but got {type(error_message).__name__}."
                logging.warning(f"⚠️ Invalid type for error_message: expected text (string), but got {type(error_message).__name__}.")
                response_message.append(content_message)
                continue
        content_message["error_message"] = error_message

        # CONDITIONS: must be a dict (object)
        if not conditions:
            content_message["error"] = "⚠️ Missing conditions: Please provide the logic and fields that define when this rule is triggered."
            logging.warning("⚠️ Missing conditions: Please provide the logic and fields that define when this rule is triggered.")
            response_message.append(content_message)
            continue
        if not isinstance(conditions, dict):
            content_message["error"] = f"⚠️ Invalid type for conditions: expected an object (dict), but got {type(conditions).__name__}."
            logging.warning(f"⚠️ Invalid type for conditions: expected an object (dict), but got {type(conditions).__name__}.")
            response_message.append(content_message)
            continue

        # LOGICAL OPERATION
        logic = conditions.get("logic")
    
        if not isinstance(logic, str):
            content_message["error"] = f"⚠️ Invalid type for conditions -> logic: expected text (string), but got {type(logic).__name__}."
            logging.warning(f"⚠️ Invalid type for conditions -> logic: expected text (string), but got {type(logic).__name__}.")
            response_message.append(content_message)
            continue

        if logic not in {"AND", "OR"}:
            content_message["error"] = f"⚠️ Invalid value for conditions -> logic: expected 'AND' or 'OR', but got '{logic}'."
            logging.warning(f"⚠️ Invalid value for conditions -> logic: expected 'AND' or 'OR', but got '{logic}'.")
            response_message.append(content_message)
            continue


        logging.info("\n✅ LLM returned a valid rule JSON. Ready to save the rule named {name} to the database.")
        try:
            rule = BusinessRule.objects.create(
                name=name,
                rule_type=rule_type,
                target_type=target_type,
                priority=priority,
                error_message=error_message,
                active=active,
                conditions=conditions,  # conditions JSON
            )
            logging.info(f"✅ BusinessRule '{rule.name}' saved successfully with ID {rule.id}.")
            content_message["success"] = True
            response_message.append(content_message)
        except Exception as e:
            logging.error(f"❌ Error saving Rule: {e}")
            content_message["error"] = f"❌ Error saving rule to database: {str(e)}"
            response_message.append(content_message)
            continue
        
        print(f"\n\nRule {response_message}\n")

    return {
        "message": "Here are the rules details:",
        "validation_rules_details": response_message,
        "hiddenMessage": "True"
    }
