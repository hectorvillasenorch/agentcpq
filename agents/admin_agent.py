import os
import openai
import logging
import json
import re
from dotenv import load_dotenv
from cpq.models import Quote, BusinessRule, CustomObject, EmailAlert, Product
from decimal import Decimal
from django.db.models import Q
from django.forms.models import model_to_dict
from django.contrib.auth.models import User
from cpq.models import Product

# LLM helpers
from .utils.admin_agent.llm_helpers import extract_validation_rules, extract_rules_details_to_render, extract_rule_updates, extract_rule_deletes, extract_custom_object_updates, extract_email_alerts_deletes, extract_inclusion_rules
from .utils.admin_agent.llm_helpers import extract_exclusion_rules

# Rules helpers
from .utils.admin_agent.rules_helpers import handle_extracted_rules_details, handle_rules_updates, handle_rules_deletes

# General helpers
from .utils.admin_agent.general_helpers import get_rules_details

# Handle helpers
from .utils.admin_agent.handle_helpers import handle_create_inclusion_rule, handle_create_exclusion_rule

# Session Context Helpers
from .utils.session_context_helpers.session_context_helpers import get_session_context


# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)


def _is_valid_business_rule_target_type(target_type: str) -> bool:
    """
    Backwards compatible: keep original targets, but also allow any standard model key
    (e.g., 'contract', 'opportunity') and any custom object API name (e.g., 'proyecto__c').
    """
    if not target_type:
        return False

    normalized = str(target_type).strip().lower()
    if not normalized:
        return False

    base_targets = {"quote", "quote_line", "product", "multiple"}
    if normalized in base_targets:
        return True

    # Standard-model keys (future-proof: accept snake_case identifiers)
    if re.match(r"^[a-z][a-z0-9_]*$", normalized):
        return True

    # Custom objects are typically snake_case and end with __c
    if re.match(r"^[a-z][a-z0-9_]*__c$", normalized):
        return True

    return False

def admin_agent(user, action, user_message, session_data):

    action_map = {
        "CreateValidationRule": create_validation_rule,
        "CreateInclusionRule": create_inclusion_rule,
        "CreateExclusionRule": create_exclusion_rule,
        "ShowRules": show_rules,
        "UpdateRule": update_rule,
        "DeleteRule": delete_rule,
        "CreateEmailAlert": create_email_alert,
        "UpdateEmailAlert": update_email_alert,
        "DeleteEmailAlert": delete_email_alert
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user, user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request."}


def create_validation_rule(user, user_message, session_data):

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
            logging.warning(content_message["error"])

            response_message.append(content_message)
            continue
        if not isinstance(description, str):
            try:
                description = str(description)
                content_message["description"] = description
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for description: expected text (string), but got {type(description).__name__}."
                logging.warning(content_message["error"])

                response_message.append(content_message)
                continue

        # RULE_TYPE: must be a string and one of the allowed values
        valid_rule_types = {"validation", "inclusion", "exclusion"}
        if not rule_type:
            content_message["error"] = "⚠️ Missing rule type: Please specify whether this rule is validation, inclusion, or exclusion."
            logging.warning(content_message["error"])

            response_message.append(content_message)
            continue
        if not isinstance(rule_type, str):
            try:
                rule_type = str(rule_type)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for rule_type: expected text (string), but got {type(rule_type).__name__}."
                logging.warning(content_message["error"])

                response_message.append(content_message)
                continue
        rule_type_lower = rule_type.lower()
        if rule_type_lower not in valid_rule_types:
            content_message["error"] = f"⚠️ Invalid value for rule_type: expected one of {valid_rule_types}, but got '{rule_type}'."
            logging.warning(content_message["error"])

            response_message.append(content_message)
            continue
        rule_type = rule_type_lower
        content_message["rule_type"] = rule_type

        # TARGET_TYPE: must be a string and a recognized object key.
        if not target_type:
            content_message["error"] = (
                "⚠️ Missing target type: Please define which object this rule applies to "
                "(e.g., quote, quote_line, product, opportunity, contract, or a custom object like proyecto__c)."
            )
            logging.warning(content_message["error"])

            response_message.append(content_message)
            continue
        if not isinstance(target_type, str):
            try:
                target_type = str(target_type)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for target_type: expected text (string), but got {type(target_type).__name__}."
                logging.warning(content_message["error"])

                response_message.append(content_message)
                continue
        target_type_lower = target_type.lower()
        if not _is_valid_business_rule_target_type(target_type_lower):
            content_message["error"] = (
                "⚠️ Invalid value for target_type: please use a valid object key "
                "(e.g., quote, quote_line, product, opportunity, contract) or a custom object API name (e.g., proyecto__c)."
            )
            logging.warning(content_message["error"])

            response_message.append(content_message)
            continue
        target_type = target_type_lower
        content_message["target_type"] = target_type

        # PRIORITY: must be an integer
        if priority is None:
            content_message["error"] = "⚠️ Missing priority: No priority value was provided. Please assign a priority number."
            logging.warning(content_message["error"])

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
                logging.warning(content_message["error"])

                response_message.append(content_message)
                continue
        content_message["priority"] = priority

        # ERROR_MESSAGE: must be a string
        if not error_message:
            content_message["error"] = "⚠️ Missing error message: Please include a message that describes what should happen when the rule is triggered."
            logging.warning(content_message["error"])

            response_message.append(content_message)
            continue
        if not isinstance(error_message, str):
            try:
                error_message = str(error_message)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for error_message: expected text (string), but got {type(error_message).__name__}."
                logging.warning(content_message["error"])

                response_message.append(content_message)
                continue
        content_message["error_message"] = error_message

        # CONDITIONS: must be a dict (object)
        if not conditions:
            content_message["error"] = "⚠️ Missing conditions: Please provide the logic and fields that define when this rule is triggered."
            logging.warning(content_message["error"])

            response_message.append(content_message)
            continue
        if not isinstance(conditions, dict):
            content_message["error"] = f"⚠️ Invalid type for conditions: expected an object (dict), but got {type(conditions).__name__}."
            logging.warning(content_message["error"])

            response_message.append(content_message)
            continue

        # LOGICAL OPERATION
        logic = conditions.get("logic")

        if not isinstance(logic, str):
            content_message["error"] = f"⚠️ Invalid type for conditions -> logic: expected text (string), but got {type(logic).__name__}."
            logging.warning(content_message["error"])

            response_message.append(content_message)
            continue

        if logic not in {"AND", "OR"}:
            content_message["error"] = f"⚠️ Invalid value for conditions -> logic: expected 'AND' or 'OR', but got '{logic}'."
            logging.warning(content_message["error"])

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
                created_by=user
            )

            # Set rule's name
            rule.name = f"VR-{rule.id:05d}"
            content_message["name"] = rule.name
            rule.save()

            logging.info(f"✅ BusinessRule '{rule.name}' ('{rule.description}') saved successfully with ID {rule.id}.")
            content_message["success"] = True
            response_message.append(content_message)
        except Exception as e:
            content_message["error"] = f"❌ Error saving rule to database: {str(e)}"
            logging.error(content_message["error"])

            response_message.append(content_message)
            continue

    print(f"\n\nResponse Message (Validation Rules): {response_message}\n\n")

    return {
        "message": "Here are the rules details:",
        "validation_rules_details": response_message,
        "hiddenMessage": "True"
    }

def create_inclusion_rule(user, user_message, session_data):
    """Create validation rule"""

    logging.info("🔧 Creating Inclusion Rule...\n\n")

    # Get session context
    current_state, previous_summary = get_session_context("create_inclusion_rule", session_data)

    # --- 1️⃣ Initial call to the LLM to extract inclusion rule data ---
    llm_result = extract_inclusion_rules(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary
    )

    # --- 3️⃣ Separar productos completados vs incompletos ---
    completed_rules = []
    remaining_rules = []

    for rule in llm_result["create_inclusion_rule"]:
        if rule.get("completed"):
            completed_rules.append(rule["data"])
        else:
            remaining_rules.append(rule)

    # Guardar solo los incompletos en session state
    session_data["state"]["create_inclusion_rule"] = remaining_rules

    # Return if not any completed items
    if not completed_rules:
        return {
            "message": llm_result["agent_message"],
            "session_summary": llm_result["summary"]
        }

    ################################################

    response_message = ""

    # ✅ Handle create inclusion rule
    response_message, rules_created = handle_create_inclusion_rule(user, completed_rules, response_message)

    #log_action_usage("CreateInclusionRule", user, "Quote", quote.name)
    # ✅ Update quote (subtotal, discounts fields and net amount)
    #quote.save()

    rules_details = get_inclusion_rules_details(rules_created)

    #print(f"\n\nRules Details: {rules_details}\n\n")

    if rules_created:

        return {
            "message": response_message,
            "inclusion_rules_details": rules_details,
            "hiddenMessage": "True"
        }
    
    else:
        return {
            "message": response_message
        }

    # --- 5️⃣ Generar mensaje final dinámico usando función separada ---
    dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_create_inclusion_rule_message(
        completed_rules=completed_rules,
        db_results=response_message,
        remaining_rules=remaining_rules,
        previous_summary=llm_result["summary"]
    )

    return {
        "message": dynamic_message,
        "session_summary": updated_summary
    }

#< ----------------- CREATE EXCLUSION RULE -------------------- >

def create_exclusion_rule(user, user_message, session_data):
    """Create exclusion rule"""

    logging.info("🔧 Creating Exclusion Rule...\n\n")

    # Get session context
    current_state, previous_summary = get_session_context("create_exclusion_rule", session_data)

    # --- 1️⃣ Initial call to the LLM to extract extract rule data ---

    llm_result = extract_exclusion_rules(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary
    )

    # --- 3️⃣ Separar productos completados vs incompletos ---
    completed_rules = []
    remaining_rules = []

    for rule in llm_result["create_exclusion_rule"]:
        if rule.get("completed"):
            completed_rules.append(rule["data"])
        else:
            remaining_rules.append(rule)

    # Guardar solo los incompletos en session state
    session_data["state"]["create_exclusion_rule"] = remaining_rules

    # Return if not any completed items
    if not completed_rules:
        return {
            "message": llm_result["agent_message"],
            "session_summary": llm_result["summary"]
        }

    ################################################

    response_message = ""

    # ✅ Handle create inclusion rule
    response_message, rules_created = handle_create_exclusion_rule(user, completed_rules, response_message)

    #log_action_usage("CreateInclusionRule", user, "Quote", quote.name)
    # ✅ Update quote (subtotal, discounts fields and net amount)
    #quote.save()

    rules_details = get_exclusion_rules_details(rules_created)

    #print(f"\n\nRules Details: {rules_details}\n\n")

    if rules_created:

        return {
            "message": response_message,
            "exclusion_rules_details": rules_details,
            "hiddenMessage": "True"
        }
    
    else:
        return {
            "message": response_message
        }

    # --- 5️⃣ Generar mensaje final dinámico usando función separada ---
    dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_create_inclusion_rule_message(
        completed_rules=completed_rules,
        db_results=response_message,
        remaining_rules=remaining_rules,
        previous_summary=llm_result["summary"]
    )

    return {
        "message": dynamic_message,
        "session_summary": updated_summary
    }


#< ----------------- SHOW VALIDATION RULES -------------------- >

def show_rules(user, user_message, session_data):
    """Fetches and formats quote details, including quote lines, based on user input or session data."""


    try:
        logging.info("🔄 Showing rules...")

        current_state, previous_summary = get_session_context("show_rules", session_data)

        # Extract rules details to render
        extracted_rules_details = extract_rules_details_to_render(
            user_message=user_message,
            current_state=current_state,
            previous_summary=previous_summary
        )

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

        return {
            "message": f"❌ An unexpected error occurred while retrieving the rules: {str(e)}"
        }

def update_rule(user, user_message, session_data):
    """Updates only the modified fields in rules."""

    logging.info("🔧 Updating rules...\n\n")

    current_state, previous_summary = get_session_context("update_rule", session_data)

    # ✅ Extract quote line updates with LLM
    extracted_updates = extract_rule_updates(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary
    )


    if not extracted_updates:

        return {
        "message": "⚠️ AgentCPQ: An error occurred while extracting your updates. Please try again."
        }

    response_message = ""

    # ✅ Handle rules updates
    response_message, updated_rules = handle_rules_updates(extracted_updates, response_message)


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

    logging.info("🔧 Deleting rules...\n\n")
    # ✅ Looking for active quote


    # ✅ Extract quote line updates with LLM
    extracted_updates = extract_rule_deletes(user_message)

    if not extracted_updates:

        return {
        "message": "⚠️ AgentCPQ: An error occurred while extracting your updates. Please try again."
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, updated_rules = handle_rules_deletes(extracted_updates, response_message)

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
from agents.utils.admin_agent.handle_helpers import handle_email_alerts_creation, handle_email_alerts_updates, handle_email_alerts_deletes

def create_email_alert(user, user_message, session_data):
    """Create email alert"""

    logging.info("🔧 Creating email alert...\n\n")

    # ✅ Get all the custom objects and users
    custom_objects = CustomObject.objects.values_list("name", flat=True)

    users = User.objects.values_list("username", flat=True)

    # ✅ Extract email alerts details with LLM
    extracted_email_alerts = extract_email_alert_details(user, user_message, custom_objects, users)

    if not extracted_email_alerts:

        return {
            "message": "⚠️ AgentCPQ: An error occurred while extracting your email alert update data. Please try again."
        }

    response_message = ""

    print(f"Entrando a la function para crear email alerts")

    # ✅ Handle email alerts
    response_message, email_alerts_created = handle_email_alerts_creation(user, extracted_email_alerts, response_message)

    # ✅ Return
    if not email_alerts_created:
        return {
            "message": f"No email alerts were created. <br><br>{response_message}",
            "temporaryMessage": True
        }



    return {
        "message": response_message,
        "email_alerts_details": email_alerts_created,
        "hiddenMessage": "True"
        }

def update_email_alert(user, user_message, session_data):
    """Edit email alert"""

    logging.info("🔧 Editing email alert...\n\n")

    # ✅ Get all the custom objects and users
    custom_objects = CustomObject.objects.values_list("name", flat=True)

    users = User.objects.values_list("username", flat=True)

    email_alerts = EmailAlert.objects.filter().all()

    extracted_email_alerts_updates = extract_email_alert_updates(user, user_message, custom_objects, users)

    if not extracted_email_alerts_updates:

        return {
            "message": "⚠️ AgentCPQ: An error occurred while extracting your email alert update data. Please try again."
        }


    response_message = ""

    # ✅ Handle email alerts updates
    response_message, email_alerts_updated = handle_email_alerts_updates(user, extracted_email_alerts_updates, response_message)

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

def delete_email_alert(user, user_message, session_data):
    """Delete email alerts"""
    # 🧠 Make the session context

    logging.info("🔧 Deleting email alert...\n\n")
    # ✅ Looking for active quote


    # ✅ Extract quote line updates with LLM
    extracted_email_alerts_deletes = extract_email_alerts_deletes(user_message)

    if not extracted_email_alerts_deletes:

        return {
        "message": "⚠️ AgentCPQ: An error occurred while extracting your updates. Please try again."
        }

    response_message = ""

    # ✅ Handle rules deletes
    response_message, deleted_email_alerts = handle_email_alerts_deletes(extracted_email_alerts_deletes, response_message)

    # ✅ Return
    if not deleted_email_alerts:
        return {
            "message": f"No email alerts were deleted. <br><br>{response_message}",
            "temporaryMessage": True
        }

    return {
        "message": response_message,
        "temporaryMessage": True
        }


def get_inclusion_rules_details(inclusion_rules):

    rule_ids = [rule.id for rule in inclusion_rules]
    rules_qs = BusinessRule.objects.filter(id__in=rule_ids)

    rules_details = []
    for rule in rules_qs:
        conditions = rule.conditions or {}

        # 🔎 Procesar trigger_product si existe
        tp = conditions.get("trigger_product")
        if tp:
            query = Q()
            if tp.get("name"):  # puede ser sku disfrazado
                query |= Q(name=tp["name"]) | Q(sku=tp["name"])
            if tp.get("sku"):  # puede ser name disfrazado
                query |= Q(name=tp["sku"]) | Q(sku=tp["sku"])

            product = Product.objects.filter(query).first()
            if product:
                conditions["trigger_product"] = {
                    "name": product.name,
                    "sku": product.sku
                }
            else:
                # fallback: se deja lo que vino del LLM
                conditions["trigger_product"] = {
                    "name": tp.get("name"),
                    "sku": tp.get("sku")
                }

        rules_details.append({
            "name": rule.name,
            "description": rule.description,
            "rule_type": rule.rule_type,
            "target_type": rule.target_type,
            "priority": rule.priority,
            "error_message": rule.error_message,
            "active": rule.active,
            "conditions": conditions,  # ya limpio
        })

    return rules_details

def get_exclusion_rules_details(rules):
    """
    Returns exclusion rules details for the frontend,
    keeping the structure of trigger_product and excluded_products
    as saved in the database.
    """

    rule_ids = [rule.id for rule in rules]
    rules_qs = BusinessRule.objects.filter(id__in=rule_ids)

    rules_details = []

    for rule in rules_qs:
        conditions = rule.conditions or {}

        # Solo usamos los datos ya validados del DB
        rules_details.append({
            "name": rule.name,
            "description": rule.description,
            "rule_type": rule.rule_type,
            "target_type": rule.target_type,
            "priority": rule.priority,
            "error_message": rule.error_message,
            "active": rule.active,
            "conditions": conditions,
        })

    return rules_details
