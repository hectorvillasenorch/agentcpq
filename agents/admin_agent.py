import os
import openai
import logging
import json
from dotenv import load_dotenv
from cpq.models import Quote, BusinessRule
from decimal import Decimal
from django.db.models import Q
from django.forms.models import model_to_dict


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
            response_message.append(content_message)
            continue
        if not isinstance(name, str):
            try:
                name = str(name)
                content_message["name"] = name
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for name: expected text (string), but got {type(name).__name__}."
                response_message.append(content_message)
                continue

        # RULE_TYPE: must be a string and one of the allowed values
        valid_rule_types = {"validation", "inclusion", "exclusion"}
        if not rule_type:
            content_message["error"] = "⚠️ Missing rule type: Please specify whether this rule is validation, inclusion, or exclusion."
            response_message.append(content_message)
            continue
        if not isinstance(rule_type, str):
            try:
                rule_type = str(rule_type)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for rule_type: expected text (string), but got {type(rule_type).__name__}."
                response_message.append(content_message)
                continue
        rule_type_lower = rule_type.lower()
        if rule_type_lower not in valid_rule_types:
            content_message["error"] = f"⚠️ Invalid value for rule_type: expected one of {valid_rule_types}, but got '{rule_type}'."
            response_message.append(content_message)
            continue
        rule_type = rule_type_lower
        content_message["rule_type"] = rule_type

        # TARGET_TYPE: must be a string and one of the allowed values
        valid_target_types = {"quote", "quote_line", "product", "multiple"}
        if not target_type:
            content_message["error"] = "⚠️ Missing target type: Please define the level where this rule applies (quote, quote_line, product, or multiple)."
            response_message.append(content_message)
            continue
        if not isinstance(target_type, str):
            try:
                target_type = str(target_type)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for target_type: expected text (string), but got {type(target_type).__name__}."
                response_message.append(content_message)
                continue
        target_type_lower = target_type.lower()
        if target_type_lower not in valid_target_types:
            content_message["error"] = f"⚠️ Invalid value for target_type: expected one of {valid_target_types}, but got '{target_type}'."
            response_message.append(content_message)
            continue
        target_type = target_type_lower
        content_message["target_type"] = target_type

        # PRIORITY: must be an integer
        if priority is None:
            content_message["error"] = "⚠️ Missing priority: No priority value was provided. Please assign a priority number."
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
                response_message.append(content_message)
                continue
        content_message["priority"] = priority

        # ERROR_MESSAGE: must be a string
        if not error_message:
            content_message["error"] = "⚠️ Missing error message: Please include a message that describes what should happen when the rule is triggered."
            response_message.append(content_message)
            continue
        if not isinstance(error_message, str):
            try:
                error_message = str(error_message)
            except Exception:
                content_message["error"] = f"⚠️ Invalid type for error_message: expected text (string), but got {type(error_message).__name__}."
                response_message.append(content_message)
                continue
        content_message["error_message"] = error_message

        # CONDITIONS: must be a dict (object)
        if not conditions:
            content_message["error"] = "⚠️ Missing conditions: Please provide the logic and fields that define when this rule is triggered."
            response_message.append(content_message)
            continue
        if not isinstance(conditions, dict):
            content_message["error"] = f"⚠️ Invalid type for conditions: expected an object (dict), but got {type(conditions).__name__}."
            response_message.append(content_message)
            continue

        # LOGICAL OPERATION
        logic = conditions.get("logic")
    
        if not isinstance(logic, str):
            content_message["error"] = f"⚠️ Invalid type for conditions -> logic: expected text (string), but got {type(logic).__name__}."
            response_message.append(content_message)
            continue

        if logic not in {"AND", "OR"}:
            content_message["error"] = f"⚠️ Invalid value for conditions -> logic: expected 'AND' or 'OR', but got '{logic}'."
            response_message.append(content_message)
            continue

        error_found = False

        for item in conditions.get("items", []):
            field = item.get("fieldName")
            operator = item.get("operator")
            value = item.get("value")

            if not field or not operator or not value:
                continue

            valid_fields = {
                "quote": {"net_amount", "tax_amount", "status", "discount_percentage", "expiration_date", "discount_amount", "discount_type", "subtotal"},
                "quote_line": {"quantity", "unit_price", "special_price", "total_price", "discount_percentage", "discount_type", "discount_amount", "billing_frequency", "billing_end_date", "billing_start_date", "is_subscription", "product_name", "sku", "term", "subtotal"},
                "product": {"name", "sku", "price", "is_subscription", "term", "is_bundle", "family"}
            }

            valid_operators = {">=", "<=", "==", ">", "<", "!="}

            # Validate fieldName is string
            if not isinstance(field, str):
                content_message["error"] = f"⚠️ Invalid type for fieldName: expected text (string), but got {type(field).__name__} for field: {field}."
                response_message.append(content_message)
                error_found = True
                break

            # Validate fieldName prefix and field
            if "." not in field:
                content_message["error"] = f"⚠️ Invalid fieldName format: missing level prefix in '{field}'."
                response_message.append(content_message)
                error_found = True
                break

            prefix, field_name = field.split(".", 1)
            if prefix not in valid_fields:
                content_message["error"] = f"⚠️ Invalid field level prefix in fieldName: '{prefix}'. Expected one of {list(valid_fields.keys())}."
                response_message.append(content_message)
                error_found = True
                break

            if field_name not in valid_fields[prefix]:
                content_message["error"] = f"⚠️ Invalid field '{field_name}' for level '{prefix}'. Valid fields are {sorted(valid_fields[prefix])}."
                response_message.append(content_message)
                error_found = True
                break

            # Validate operator is string and valid
            if not isinstance(operator, str):
                content_message["error"] = f"⚠️ Invalid type for operator: expected text (string), but got {type(operator).__name__}."
                response_message.append(content_message)
                error_found = True
                break

            if operator not in valid_operators:
                content_message["error"] = f"⚠️ Invalid operator '{operator}'. Valid operators are {sorted(valid_operators)}."
                response_message.append(content_message)
                error_found = True
                break

            # Validate value type depending on field type (string or numeric)
            string_fields = {"status", "discount_type", "billing_frequency", "product_name", "sku", "term", "name", "is_subscription", "is_bundle", "family", "expiration_date"}
            expects_string = field_name in string_fields

            if expects_string:
                if not isinstance(value, str):
                    content_message["error"] = f"⚠️ Invalid type for value of field '{field}': expected string, but got {type(value).__name__}."
                    response_message.append(content_message)
                    error_found = True
                    break
            else:
                if not (isinstance(value, int) or isinstance(value, float)):
                    content_message["error"] = f"⚠️ Invalid type for value of field '{field}': expected numeric, but got {type(value).__name__}."
                    response_message.append(content_message)
                    error_found = True
                    break
        
        if error_found:
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


def extract_validation_rules(user_message):
    """Uses GPT to extract rule type, target type, priority, error_message and conditions for Validations Rules."""

    prompt = f"""
    You are an expert assistant for a CPQ (Configure, Price, Quote) system. Your task is to extract structured business rule definitions from a natural language request written by a user.

    The output must be a single JSON array, where each object represents one rule. Each rule object must include the following keys:

    - name (string): The name of the rule. If the user specifies a name, use it. If not, generate a concise name that summarizes the rule purpose.
    - rule_type (string): Type of rule. Must be one of:
        - "validation"
        - "inclusion"
        - "exclusion"
        If the user does not explicitly mention it, infer it based on the intent.
    - target_type (string): The level where the rule applies. Must be one of:
        - "quote"
        - "quote_line"
        - "multiple"
        If the user specifies a target but the rule clearly involves fields from more than one level, set this to "multiple", even if the user suggested otherwise.
    - priority (integer): The rule's priority. If specified, use it. If not, default to 10.
    - error_message (string): The message to display when the rule is triggered. Use the user-provided message if available; otherwise, create a clear, professional message based on the intent of the rule.
    - active (boolean): If user doesn't explicitly specify active (true or false), set active as true. If the user uses indirect language like "do not activate", "leave inactive", "but not active", "shouldn't be active", etc., set active as false. Use only lowercase true or false.
    - conditions (object): The condition logic that triggers the rule. Must follow this strict JSON structure:

    Response:
    [
    {{
        "conditions": {{
        "logic": "AND" | "OR",
        "items": [
            {{
            "fieldName": "quote.subtotal",
            "operator": "==",
            "value": 1000
            }},
            {{
            "logic": "AND",
            "items": [ ... ]
            }}
        ]
        }}
    }}
    ]

    If only one condition is present, use "logic": "AND" by default.

    - conflicts (string, optional): If the user refers to a field like discount_percentage without specifying the level (quote vs quote_line), and the field exists in multiple models, add a conflict message here explaining that clarification is needed. For example: "Conflict in 'discount_percentage': this field exists in both quote and quote_line. Please specify which level the rule should apply to."

    Allowed field names per level:

    Quote: net_amount, tax_amount, status, discount_percentage, discount_amount, discount_type, subtotal

    Quote Line: quantity, unit_price, special_price, total_price, discount_percentage, discount_type, discount_amount, billing_frequency, billing_end_date, billing_start_date, is_subscription, product_name, sku, term, subtotal

    Example #1:

    User:
    "Create a rule to prevent quote line items from having discounts greater than $100."

    Expected Output:
    [
    {{
        "name": "Max Quote Line Discount Greater Than $100",
        "rule_type": "validation",
        "target_type": "quote_line",
        "priority": 10,
        "error_message": "Discount amount cannot exceed $100 for any quote line item.",
        "active": true,
        "conditions": {{
            "logic": "AND",
            "items": [
                {{
                    "fieldName": "quote_line.discount_amount",
                    "operator": ">",
                    "value": 100
                }}
            ]
        }},
        "conflicts": null
    }}
    ]

    Example #2:

    User:
    "create a validation rule to prevent discount > 60% for ACPQ-002 line item."

    Expected Output:
    [
    {{
        "name": "Prevent discount greater than 60% for OK-TG-SHY-034 product.",
        "rule_type": "validation",
        "target_type": "quote_line",
        "priority": 10,
        "error_message": "Discount percentage cannot exceed 60% for line item OK-TG-SHY-034.",
        "active": true,
        "conditions": {{
            "logic": "AND",
            "items": [
                {{
                    "fieldName": "quote_line.discount_percentage",
                    "operator": ">",
                    "value": 60
                }},
                {{
                    "fieldName": "quote_line.sku",
                    "operator": "==",
                    "value": "OK-TG-SHY-034"
                }}
            ]
        }},
        "conflicts": null
    }}
    ]

    Requirements:
    - Always include fieldName in full format: quote. or quote_line.
    - Always enclose string values in double quotes, and leave numeric values as raw numbers.
    - Do not return explanations or extra text — only the JSON array of rules.
    - If multiple rules are described in the message, return multiple objects in the array.
    + If ambiguous fields are used (e.g., discount_percentage without level), check for context clues:
    +   - If the user mentions "line item", infer `quote_line`.
    +   - If the user mentions "quote", infer `quote`.
    + If no clear context is present, include a "conflicts" key explaining the ambiguity, including fieldName, operator, and value.
    - Always include "conflicts" key, if you cannot determine the value, set as null
    - If you cannot determine the correct value for any field (e.g., name, rule_type, target_type, priority, error_message, or conditions), set its value to null.
    - If no conditions are provided, set conditions to null (e.g. "conditions": null)
    - If any field is not in "Allowed field names per level", create a conflict message indicating that a rule cannot be created with that field

    **IMPORTANT:** 
    Rules for output:
    - DO return only a raw JSON array of rule objects.
    - DO NOT include triple backticks (```), `json`, or any Markdown formatting.
    - DO NOT explain anything.

    Begin extraction.
    
    User message: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a CPQ assistant. Extract structured business rules from the user message."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_rules = json.loads(raw_response)
            if isinstance(extracted_rules, list) and all(
                isinstance(rule, dict) and
                "name" in rule and
                "rule_type" in rule and
                "target_type" in rule and
                "priority" in rule and
                "error_message" in rule and
                "conditions" in rule
                for rule in extracted_rules
            ):
                return extracted_rules
            else:
                logging.warning("⚠️ GPT response is not in expected business rule format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting business rules: {str(e)}")
        return None
















########################################################################



def check_for_rules(target_type, quote, product, quote_line):

    rules = BusinessRule.objects.filter(active=True, rule_type="validation").filter(
        Q(target_type=target_type) | Q(target_type="multiple")
    ).order_by('-priority')


    validations = []

    #data = model_to_dict(quote_line)
    #formatted = json.dumps(data, indent=4, default=str)
    #print(f"\n🧾 Formatted QuoteLine:\n{formatted}")

    for rule in rules:
        try:
            conditions = rule.conditions
        except Exception as e:
            logging.warning(f"Error: {e}")
            continue # Skip the rules with conditions bad formed

        print(f"\n📜 Evaluating rule: {rule.name}")
        if check_validation_conditions(conditions, quote, product, quote_line):
            logging.warning(f"🚫 Violation: {rule.error_message}")
            validations.append(rule.error_message)
        else:
            logging.info(f"✅ No problems with rule {rule.name}\n\n")

    return validations

def check_validation_conditions(data, quote, product, quote_line, depth=1):
    indent = "  " * depth  # For console indentation

    if isinstance(data, dict):
        if "logic" in data and "items" in data:
            logic = data["logic"]

            results = []
            for item in data["items"]:
                result = check_validation_conditions(item, quote, product, quote_line, depth + 1)
                results.append(result)

            if logic == "AND":
                return all(results)
            elif logic == "OR":
                return any(results)
            else:
                logging.warning(f"{indent}❌ Unknown logical operator: {logic}")
                return False

        elif all(key in data for key in ["fieldName", "operator", "value"]):
            field = data["fieldName"]
            operator = data["operator"]
            value = data["value"]

            model_name, attr = field.split(".", 1)
            obj = {"quote": quote, "quote_line": quote_line, "product": product}.get(model_name)

            logging.warning(f"OBJECT {obj.discount_amount}❌❌❌ Object")

            if not obj:
                logging.warning(f"{indent}❌ Object not found for: {model_name}")
                return False

            actual_value = getattr(obj, attr, None)

            if actual_value is None:
                logging.warning(f"{indent}❌ Attribute '{attr}' not found in {model_name}")
                return False

            logging.info(f"{indent}🔍 Comparing: {obj.discount_amount} {operator} {value}")

            try:
                if operator == "==":
                    result = actual_value == value
                    logging.info(f"Result: {result}\n\n")
                    return result
                elif operator == "!=":
                    result = actual_value != value
                    logging.info(f"Result: {result}\n\n")
                    return result
                elif operator == ">":
                    result = actual_value > value
                    logging.info(f"Result: {result}\n\n")
                    return result
                elif operator == ">=":
                    result = actual_value >= value
                    logging.info(f"Result: {result}\n\n")
                    return result
                elif operator == "<":
                    result = actual_value < value
                    logging.info(f"Result: {result}\n\n")
                    return result
                elif operator == "<=":
                    result = actual_value <= value
                    logging.info(f"Result: {result}\n\n")
                    return result
                else:
                    logging.warning(f"{indent}❌ Unsupported operator: {operator}")
                    return False
            except Exception as e:
                logging.warning(f"{indent}❌ Error during comparison: {e}")
                return False
        else:
            logging.warning(f"{indent}⚠️ Unknown dictionary structure: {data}")
            return False

    elif isinstance(data, list):
        results = [check_validation_conditions(item, quote, product, quote_line, depth) for item in data]
        return all(results)

    else:
        logging.warning(f"{indent}❌ Unexpected data type: {type(data).__name__}")
        return False