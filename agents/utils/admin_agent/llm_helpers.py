import json, os, re
import openai
import logging
from dotenv import load_dotenv

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"
#OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

def extract_validation_rules(user_message):
    """Uses GPT to extract description, rule type, target type, priority, error_message and conditions for Validations Rules."""

    prompt = f"""
    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**

    You are an expert assistant for a CPQ (Configure, Price, Quote) system. Your task is to extract structured business rule definitions from a natural language request written by a user.

    The output must be a single JSON array, where each object represents one rule. Each rule object must include the following keys:

    - description (string): The description of the rule. If the user specifies a description, use it. If not, generate a concise description that summarizes the rule purpose.
    - rule_type (string): Type of rule. Must be one of:
        - "validation"
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

    Allowed field names per level:

    Quote: net_amount, tax_amount, status, discount_percentage, discount_amount, discount_type, subtotal

    Quote Line: quantity, unit_price, special_price, total_price, discount_percentage, discount_type, discount_amount, billing_frequency, billing_end_date, billing_start_date, is_subscription, product_name, sku, term, subtotal

    Example #1:

    User:
    "Create a rule to prevent quote line items from having discounts greater than $100."

    Expected Output:
    [
    {{
        "description": "Max Quote Line Discount Greater Than $100",
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
        }}
    }}
    ]

    Example #2:

    User:
    "create a validation rule to prevent discount > 60% for ACPQ-002 line item."

    Expected Output:
    [
    {{
        "description": "Prevent discount greater than 60% for OK-TG-SHY-034 product.",
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
        }}
    }}
    ]

    Requirements:
    - Always include fieldName in full format: quote. or quote_line.
    - Always enclose string values in double quotes, and leave numeric values as raw numbers.
    - Do not return explanations or extra text — only the JSON array of rules.
    - If multiple rules are described in the message, return multiple objects in the array.
    + If ambiguous fields are used (e.g., discount_percentage without level), check for context clues:
    +   - If the user mentions "line item" or "quote line", infer `quote_line`.
    +   - If the user mentions "quote", infer `quote`.
    - If you cannot determine the correct value for any field (e.g., description, rule_type, target_type, priority, error_message, or conditions), set its value to null.
    - If no conditions are provided, set conditions to null (e.g. "conditions": null)

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
                "description" in rule and
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
    
def extract_rules_details_to_render(user_message):
    """Extracts name, rule_type, target_type, priority, and active fields from rules using GPT to display them to the user."""

    prompt = f"""
    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**

    You are an expert assistant for a CPQ (Configure, Price, Quote) system. Your task is to extract structured business rule definitions from a natural language request written by a user.

    The output must be a single JSON array, where each object represents one rule. Each rule object must include the following keys:

    - request_description (string): A short, human-readable description that summarizes what the user is asking. This must not be a copy of the user message. Instead, infer the intent and rephrase it as a concise summary.
    - name (string): The name of the rule. If the user specifies a name, use it. The naming format starts with 'VR' for validation rules, 'IR' for inclusion rules, and 'ER' for exclusion rules, followed by 5 digits.
    - rule_type (list): Type of rule. Must be one of:
        - "validation"
        - "inclusion"
        - "exclusion"
        If the user does not explicitly mention it, set rule_type as null.
    - target_type (list): The level where the rule applies. Must be one of:
        - "quote"
        - "quote_line"
        - "multiple"
        If the user does not explicitly mention it, set target_type as null.
    - priority (integer): The rule's priority. If the user does not explicitly mention it, set priority as null.
    - active (boolean): If the user does not explicitly mention it, set active as null.

    User:
    "show rules"

    Expected Output:
    [
    {{
        "request_description": null,
        "name": null,
        "rule_type": null,
        "target_type": null,
        "priority": null,
        "active": null
    }}
    ]

    Example #2:

    User:
    "show me the validation and inclusion rules"

    Expected Output:
    [
    {{
        "request_description": "Showing validation rules...",
        "name": null,
        "rule_type": ["validation"],
        "target_type": null,
        "priority": null,
        "active": null
    }},
    {{
        "request_description": "Showing inclusion rules...",
        "name": null,
        "rule_type": ["inclusion"],
        "target_type": null,
        "priority": null,
        "active": null
    }}
    ]

    Example #3:

    User:
    "Display only the rules that apply to quotes and have priority 7"

    Expected Output:
    [
    {{
        "request_description": "Showing rules with target type: quote and priority: 7...",
        "name": null,
        "rule_type": null,
        "target_type": ["quote"],
        "priority": 7,
        "active": True
    }}
    ]

    Example #4:

    User:
    "show IR-00675 rule"

    Expected Output:
    [
    {{
        "request_description": "Showing specific rule: IR-00675...",
        "name": "IR-00675",
        "rule_type": null,
        "target_type": null,
        "priority": null,
        "active": null
    }}
    ]

    Example #5:

    User:
    "show rules VR-05463 and ER-00053"

    Expected Output:
    [
    {{
        "request_description": "Showing specific rule: VR-05463...",
        "name": "VR-05463",
        "rule_type": null,
        "target_type": null,
        "priority": null,
        "active": null
    }},
    {{
        "request_description": "Showing specific rule: ER-00053...",
        "name": "ER-00053",
        "rule_type": null,
        "target_type": null,
        "priority": null,
        "active": null
    }}
    ]

    Example #6:

    User:
    "show all rules"

    If the user message is exactly "show all rules", respond only with the following JSON format (no additional text):

    [
        {{
            "request_description": "Showing all available rules...",
            "name": null,
            "rule_type": ["validation", "inclusion", "exclusion"],
            "target_type": ["quote", "quote_line", "multiple"],
            "priority": null,
            "active": null
        }}
    ]

    For any other user input, respond normally.

    Requirements:
    - Do not return explanations or extra text — only the JSON array of rules.
    - If multiple rules are described in the message, return multiple objects in the array.
    - If you cannot determine the correct value for any field (e.g., name, rule_type, target_type, priority, active), set its value to null.
    - If the user refers to a specific rule by name (e.g., starting with VR, IR, or ER for validation, inclusion, or exclusion rules respectively), set rule_type, target_type, priority, and active to null, as they are not needed for identifying a specific rule.

    **IMPORTANT:** 
    - Unless the user input is exactly "show all rules", do not include more than one value in the rule_type or target_type lists.
    - If the user asks for multiple rule types or target types (e.g., "show validation and inclusion rules"), return one dictionary per rule type or target type, each with a single item in the corresponding list.
    - Exception: If the user input is exactly "show all rules", then you may include multiple values in both rule_type and target_type lists inside a single dictionary.
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
                "active" in rule
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
    
# FUNCTION TO EXTRACT RULE UPDATES (UPDATE_RULES)    
def extract_rule_updates(user_message):
    """Uses GPT to extract rule name, field, and new value for rules updates."""

    prompt = f"""
    Extract structured update details from the following request.
    Return a JSON array of objects, where each object must include:

    - "name" (string, required): The name of the rule being updated.
    - "field" (string, required): The field to be updated. Valid fields are: rule_type, target_type, priority, error_message, active, description, conditions.
    - "value" (number, string, or object, required): The new value to assign to the specified field.

    Value expectations by field:
    - rule_type: "validation", "inclusion", or "exclusion"
    - target_type: "quote_line", "quote", or "multiple"
    - priority: any number
    - error_message: any string
    - active: true or false
    - description: any string
    - conditions: a structured JSON object representing the logical conditions used to evaluate the rule

    **Example Input & Output:**

    User: "Update rule IR-08763 type to inclusion and priority to 7."
    Response:
    [
        {{
            "name": "IR-08763",
            "field": "rule_type",
            "value": "inclusion"
        }},
        {{
            "name": "IR-08763",
            "field": "priority",
            "value": 7
        }}
    ]

    User: "Update rule target to quote"
    Response:
    [
        {{
            "name": null,
            "field": "target_type",
            "value": "quote"
        }}
    ]

    User: "Update rule ER-00065 error message to 'You can't add the product UHTY-876 and ACPQ-001 at the same time' and set disabled"
    Response:
    [
        {{
            "name": "ER-00065",
            "field": "error_message",
            "value": "You can't add the product UHTY-876 and ACPQ-001 at the same time."
        }},
        {{
            "name": "ER-00065",
            "field": "active",
            "value": false
        }}
    ]

    User: "Update VR-00032 rule description to 'No discounts > 45%'"
    Response:
    [
        {{
            "name": "VR-00032",
            "field": "description",
            "value": "No discounts > 45%"
        }}
    ]

    User: "Update the conditions of rule VR-00012. The new rule should prevent adding a discount greater than or equal to 15% to products with SKU QTGY-HY-009."
    Response:
    [
        {{
            "name": "VR-00012",
            "field": "conditions",
            "value": {{
                "logic": "AND",
                "items": [
                    {{
                        "fieldName": "quote_line.discount_percentage",
                        "operator": ">=",
                        "value": 15
                    }},
                    {{
                        "fieldName": "quote_line.sku",
                        "operator": "==",
                        "value": "QTGY-HY-009"
                    }}
                ]
            }}
        }},
        {{
            "name": "VR-00012",
            "field": "error_message",
            "value": "Discount cannot exceed 15% for product with SKU QTGY-HY-009"
        }},
        {{
            "name": "VR-00012",
            "field": "description",
            "value": "Prevent discounts ≥ 15% for product QTGY-HY-009"
        }}
    ]

    If the user asks to update only the conditions of a rule but does not mention updating the error_message or description, then automatically infer and include appropriate values for those fields based on the intent or logic of the new rule. Add them as separate update objects using the same rule name.

    **Requirements:**
    - If no name are found in the message, return null as name
    - The `"name"` must always follow the format: one of `VR`, `IR`, or `ER` followed by a hyphen (`-`) and exactly 5 digits (e.g., `"VR-00012"`).
    - If no field are found in the message, return null as field
    - If no value are found in the message, return null as value
    - Only return a structured JSON object in `"value"` when the `"field"` is equal to `"conditions"`.

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured updates details for rules."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all("name" in p and "field" in p and "value" in p for p in extracted_updates):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting discount details: {str(e)}")
        return None
    
# FUNCTION TO DELETE RULE (DELETE_RULE)    
def extract_rule_deletes(user_message):
    """Uses GPT to extract rule name for rules delete."""

    prompt = f"""
    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**
    
    Extract structured name of rules from the following request.
    Return a JSON array of objects, where each object must include:

    - "name" (string, required): The name of the rule being deleted.

    **Example Input & Output:**

    User: "delete rules VR-00065, IR-06528 and ER-76549"
    Response:
    [
        {{
            "name": "VR-00065"
        }},
        {{
            "name": "IR-06528"
        }},
        {{
            "name": "ER-76549"
        }}
    ]

    **Requirements:**
    - If no name are found in the message, return null as name
    - The `"name"` must always follow the format: one of `VR`, `IR`, or `ER` followed by a hyphen (`-`) and exactly 5 digits (e.g., `"VR-00012"`).

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured names details for delete rules."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_deletes = json.loads(raw_response)
            if isinstance(extracted_deletes, list) and all("name" in p for p in extracted_deletes):
                return extracted_deletes
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting discount details: {str(e)}")
        return None
        
# FUNCTION TO EXTRACT CUSTOM OBJECT UPDATES (UPDATE_CUSTOM_OBJECT)    
def extract_custom_object_updates(user_message):
    """Uses GPT to extract custom object name, label, and new values for custom object updates."""

    prompt = f"""
    Extract structured update details from the following request.
    Return a JSON array of objects, where each object must include:

    - "label" (string): The label of the Custom Object
    - "name" (string): The name of the Custom Object
    - "updates" (list): A list of fields to update
        - "label" (string): If user wants to update the label
        - "name" (string): If user wants to update the name
        - "description" (string): If user wants to update the description

    **Example Input & Output:**

    User: "Update rule IR-08763 type to inclusion and priority to 7."
    User: "update payment custom object"
    Response:
    [
        {{
            "label": null
            "name": "payment",
            "updates": {{
                "label": null,
                "name": null,
                "description": null
            }}
            
        }}
    ]

    User: "Update rule target to quote"
    Response:
    [
        {{
            "name": null,
            "field": "target_type",
            "value": "quote"
        }}
    ]

    User: "Update rule ER-00065 error message to 'You can't add the product UHTY-876 and ACPQ-001 at the same time' and set disabled"
    Response:
    [
        {{
            "name": "ER-00065",
            "field": "error_message",
            "value": "You can't add the product UHTY-876 and ACPQ-001 at the same time."
        }},
        {{
            "name": "ER-00065",
            "field": "active",
            "value": false
        }}
    ]

    User: "Update VR-00032 rule description to 'No discounts > 45%'"
    Response:
    [
        {{
            "name": "VR-00032",
            "field": "description",
            "value": "No discounts > 45%"
        }}
    ]

    User: "Update the conditions of rule VR-00012. The new rule should prevent adding a discount greater than or equal to 15% to products with SKU QTGY-HY-009."
    Response:
    [
        {{
            "name": "VR-00012",
            "field": "conditions",
            "value": {{
                "logic": "AND",
                "items": [
                    {{
                        "fieldName": "quote_line.discount_percentage",
                        "operator": ">=",
                        "value": 15
                    }},
                    {{
                        "fieldName": "quote_line.sku",
                        "operator": "==",
                        "value": "QTGY-HY-009"
                    }}
                ]
            }}
        }},
        {{
            "name": "VR-00012",
            "field": "error_message",
            "value": "Discount cannot exceed 15% for product with SKU QTGY-HY-009"
        }},
        {{
            "name": "VR-00012",
            "field": "description",
            "value": "Prevent discounts ≥ 15% for product QTGY-HY-009"
        }}
    ]

    If the user asks to update only the conditions of a rule but does not mention updating the error_message or description, then automatically infer and include appropriate values for those fields based on the intent or logic of the new rule. Add them as separate update objects using the same rule name.

    **Requirements:**
    - If no name are found in the message, return null as name
    - The `"name"` must always follow the format: one of `VR`, `IR`, or `ER` followed by a hyphen (`-`) and exactly 5 digits (e.g., `"VR-00012"`).
    - If no field are found in the message, return null as field
    - If no value are found in the message, return null as value
    - Only return a structured JSON object in `"value"` when the `"field"` is equal to `"conditions"`.

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured updates details for rules."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all("name" in p and "field" in p and "value" in p for p in extracted_updates):
                return extracted_updates
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting discount details: {str(e)}")
        return None
    
# FUNCTION TO EXTRACT MAIL ALERT DETAILS (CREATE_EMAIL_ALERT)
def extract_email_alert_details(user, user_message, custom_objects, users):
    """Use GPT to extract the details of email alerts from the user’s message"""

    prompt = f"""
    Extract the structured data needed to configure one or multiple email alerts with the following structure:
    Return a JSON array of objects, where each object must include:

    - "description" (string): A short description of the email alert. If the user does not specify a description, infer one.
    - "trigger" (string): The trigger that fires the alert. It can be any of the following: lead_created, account_created, opportunity_created, opportunity_closed_won, opportunity_closed_lost, quote_sent_for_approval, quote_approved, quote_rejected, quote_expiring, subscription_renewal.
    - "native_object" (string): If the email alert is directed to a native object from the following list: Lead, Account, Opportunity, Quote, Subscription.
    - "custom_object": If the email alert is directed to a custom object. The list of custom objects is: {custom_objects}.
    - "recipients_users" (list): List of user recipients for the email alert. The list of users is: {users}. If the user explicitly specifies that the alert should be sent to themselves (for example by saying "send me", "notify me", "alert me"), then automatically include the username of the requesting user: {user.username}. In this field, only usernames are allowed—no emails, no roles.
    - "recipients_roles" (list): List of role recipients for the email alert. The possible roles are: all_superusers, all_admins, all_staff, creator.
        The field "recipients_roles" expects one or more of the following values:
        - all_superusers
        - all_admins
        - all_staff
        - creator

        When the user mentions:
        - "superusers", it should be interpreted as "all_superusers"
        - "admins", it should be interpreted as "all_admins"
        - "staff", it should be interpreted as "all_staff"

        Always convert these user terms to the corresponding role keys before saving to the database.

    - "recipients_external" (list): List of external email recipients. The user must specify these in the message.
    - "offset_days" (int): Integer that indicates the days before or after the trigger when the alert should be sent. If the number is positive, it indicates days before; if the number is negative, it indicates days after.
    - "scheduled_cron" (string): Cron format for sending the alert.

    **Example Input & Output:**

    User: "Create an email alert when a quote is sent for approval. The recipients should be superusers and admins."
    Response:
    [
        {{
            "description": "Quote sent for approval",
            "trigger": "quote_sent_for_approval",
            "native_object": "Quote",
            "custom_object": null,
            "recipients_users": [],
            "recipients_roles": ["all_superusers", "all_admins"],
            "recipients_external": [],
            "offset_days": null,
            "scheduled_cron": null
        }}
    ]

    User: "Send me an alert when a lead is closed as won or lost, and also notify all superusers."
    Response:
    [
        {{
            "description": "Lead closed as won",
            "trigger": "lead_closed_won",
            "native_object": "Lead",
            "custom_object": null,
            "recipients_users": ["{user.username}"],
            "recipients_roles": ["all_superusers"],
            "recipients_external": [],
            "offset_days": null,
            "scheduled_cron": null
        }},
        {{
            "description": "Lead closed as lost",
            "trigger": "lead_closed_lost",
            "native_object": "Lead",
            "custom_object": null,
            "recipients_users": ["{user.username}"],
            "recipients_roles": ["all_superusers"],
            "recipients_external": [],
            "offset_days": null,
            "scheduled_cron": null
        }}
    ]

    **Requirements:**
    - If "description" is not specified by the user, infer a short description.
    - If "trigger" is not specified, set it as null.
    - If "native_object" is not specified, set it as null.
    - If "custom_object" is not specified, set it as null.
    - If "recipients_users", "recipients_roles", or "recipients_external" are not specified, set them as empty lists [].
    - If the user does not specify the usernames exactly as in the users list, then leave recipients_users empty.
    - "native_object" and "custom_object" cannot both exist at the same time.
    - "offset_days" and "scheduled_cron" cannot both exist at the same time.
    - If "scheduled_cron" is provided, it must follow a valid cron format.
    - Ensure the JSON array contains valid objects with all fields normalized as described.

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured email alert details from user message."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Clean response (quita ```json ... ```)
        cleaned_response = clean_llm_response(raw_response)
        logging.info(f"\n\n🧹 Cleaned GPT Response: {cleaned_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_alerts = json.loads(cleaned_response)
            normalized_alerts = []

            for alert in extracted_alerts:
                normalized_alert = {
                    "description": alert.get("description") or "No description provided",
                    "trigger": alert.get("trigger") or None,
                    "native_object": alert.get("native_object") or None,
                    "custom_object": alert.get("custom_object") or None,
                    "recipients_users": alert.get("recipients_users") or [],
                    "recipients_roles": alert.get("recipients_roles") or [],
                    "recipients_external": alert.get("recipients_external") or [],
                    "offset_days": alert.get("offset_days") if alert.get("offset_days") is not None else None,
                    "scheduled_cron": alert.get("scheduled_cron") or None
                }

                # ✅ Validate native vs custom object
                if normalized_alert["native_object"] and normalized_alert["custom_object"]:
                    normalized_alert["native_object"] = None  # prefer custom_object

                # ✅ Validate offset_days vs scheduled_cron
                if normalized_alert["offset_days"] is not None and normalized_alert["scheduled_cron"] is not None:
                    normalized_alert["scheduled_cron"] = None  # Prioritize offset_days

                normalized_alerts.append(normalized_alert)

            return normalized_alerts

        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {cleaned_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting email alert details: {str(e)}")
        return None
    


# FUNCTION TO EXTRACT EMAIL ALERT UPDATES (UPDATE_EMAIL_ALERT)
def extract_email_alert_updates(user, user_message, custom_objects, users):
    """Use GPT to extract the details of email alerts updates from the user’s message"""

    prompt = f"""
    Extract structured data from the user’s message to update one or multiple email alerts.
    Return a JSON array of objects, where each object must include:

    If the user wants to update the description, native_object, custom_object, offset_days, scheduled_cron or active then use the following JSON structure to extract the data:
    - "alert_name" (string): The name of the email alert to be updated
    - "description" (string): A short description of the email alert. If the user does not specify a description, infer one.
    - "trigger" (string): The trigger that fires the alert. It can be any of the following: lead_created, account_created, opportunity_created, opportunity_closed_won, opportunity_closed_lost, quote_sent_for_approval, quote_approved, quote_rejected, quote_expiring, subscription_renewal.
    - "native_object" (string): If the email alert is directed to a native object from the following list: Lead, Account, Opportunity, Quote, Subscription.
    - "custom_object": If the email alert is directed to a custom object. The list of custom objects is: {custom_objects}.
    - "offset_days" (int): Integer that indicates the days before or after the trigger when the alert should be sent. If the number is positive, it indicates days before; if the number is negative, it indicates days after.
    - "scheduled_cron" (string): Cron format for sending the alert.

    If the user wants to add, remove, or replace any recipient in their request, then extend the base JSON structure with the following:

    - "recipients":
        Inside recipients we will have a list of actions
        - "action" (string): The action to perform on the recipients, it can be add, remove or replace.
        - "remove" (List): 
            - "users" (List): List of user recipients for the email alert. The list of users is: {users}. If the user explicitly specifies that the alert should be sent to themselves (for example by saying "send me", "notify me", "alert me", "me"), then automatically include the username of the requesting user: {user.username}. In this field, only usernames are allowed—no emails, no roles.
            - "roles" (List): List of role recipients for the email alert. The possible roles are: all_superusers, all_admins, all_staff, creator.
                The field "recipients_roles" expects one or more of the following values:
                - all_superusers
                - all_admins
                - all_staff
                - creator

                When the user mentions:
                - "superusers", it should be interpreted as "all_superusers"
                - "admins", it should be interpreted as "all_admins"
                - "staff", it should be interpreted as "all_staff"

                Always convert these user terms to the corresponding role keys before saving to the database.

            - "externals" (List): List of external email recipients. The user must specify these in the message.
        - "add" (List):
            - "users" (List): List of user recipients for the email alert. The list of users is: {users}. If the user explicitly specifies that the alert should be sent to themselves (for example by saying "send me", "notify me", "alert me", "me"), then automatically include the username of the requesting user: {user.username}. In this field, only usernames are allowed—no emails, no roles.
            - "roles" (List): List of role recipients for the email alert. The possible roles are: all_superusers, all_admins, all_staff, creator.
                The field "recipients_roles" expects one or more of the following values:
                - all_superusers
                - all_admins
                - all_staff
                - creator

                When the user mentions:
                - "superusers", it should be interpreted as "all_superusers"
                - "admins", it should be interpreted as "all_admins"
                - "staff", it should be interpreted as "all_staff"

                Always convert these user terms to the corresponding role keys before saving to the database.

            - "externals" (List): List of external email recipients. The user must specify these in the message.


    **Example Input & Output:**

    User: "I would like to update the email alert account_created__045. I want to replace the recipient users user_alpha, user_beta, user_gamma with user_delta, user_epsilon."
    Response:
    [
        {{
            "alert_name": "account_created__045",
            "description": null,
            "trigger": null,
            "native_object": null,
            "custom_object": null,
            "offset_days": null,
            "scheduled_cron": null,
            "active": null
            "recipients": {{
                "action": "replace",
                "remove": {{
                    "users": ["user_alpha", "user_beta", "user_gamma"],
                    "roles": [],
                    "externals": []
                }},
                "add": {{
                    "users": ["user_delta", "user_epsilon"],
                    "roles": [],
                    "externals": []
                }}
            }}
        }}
    ]

    User: "I want to update the alert account_created__023. Set the description to “Account creation alert”, set the trigger to account_created, set the native object to Accoun, make it inactive. Replace recipients: remove users (user1, user2, user3) and roles (admins); add users (user4, user5), roles (staff), and externals (partner@domain.com)."
    Response:
    [
        {{
            "alert_name": "account_created__023",
            "description": "Account creation alert",
            "trigger": "account_created",
            "native_object": "Account",
            "custom_object": null,
            "offset_days": null,
            "scheduled_cron": null,
            "active": false,
            "recipients": {{
                "action": "replace",
                "remove": {{
                    "users": ["user1", "user2", "user3"],
                    "roles": ["admins"],
                    "externals": []
                }},
                "add": {{
                    "users": ["user4", "user5"],
                    "roles": ["staff"],
                    "externals": ["partner@domain.com"]
                }}
            }}
        }}
    ]


    **Requirements:**
    - If "alert_name" is not specified, set it as null.
    - If "description" is not specified, set it as null.
    - If "trigger" is not specified, set it as null.
    - If "native_object" is not specified, set it as null.
    - If "custom_object" is not specified, set it as null.
    - If "action" is not specified, set it as null.
    - If "recipients" is not specified, set it as null.
    - If "users", "roles", or "externals" are not specified, set them as empty lists [].
    - If the user does not specify the usernames exactly as in the users list, then leave users empty.
    - If the user specifies words like 'superadmins', 'superusers', 'admins', 'staff', or 'creator', then those should go into roles, whether for remove or for add.
    - If the user specifies an external email that is not a user or a role, then it must go inside the externals list, whether the user wants to remove it or add it.
    - "native_object" and "custom_object" cannot both exist at the same time.
    - "offset_days" and "scheduled_cron" cannot both exist at the same time.
    - If "scheduled_cron" is provided, it must follow a valid cron format.
    - Ensure the JSON array contains valid objects with all fields normalized as described.

    **IMPORTANT:** **Return a valid JSON array only of objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured email alert details from user message."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Clean response (quita ```json ... ```)
        cleaned_response = clean_llm_response(raw_response)
        logging.info(f"\n\n🧹 Cleaned GPT Response: {cleaned_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_alerts = json.loads(cleaned_response)
            normalized_alerts = []

            for alert in extracted_alerts:
                normalized_alert = {
                    "alert_name": alert.get("alert_name") or None,
                    "description": alert.get("description") or None,
                    "trigger": alert.get("trigger") or None,
                    "native_object": alert.get("native_object") or None,
                    "custom_object": alert.get("custom_object") or None,
                    "offset_days": alert.get("offset_days") if alert.get("offset_days") is not None else None,
                    "scheduled_cron": alert.get("scheduled_cron") or None,
                    "active": alert.get("active") if alert.get("active") is not None else None,
                    "recipients": {
                        "action": None,
                        "remove": {"users": [], "roles": [], "externals": []},
                        "add": {"users": [], "roles": [], "externals": []}
                    }
                }


                recipients = alert.get("recipients")
                if recipients:
                    normalized_alert["recipients"]["action"] = recipients.get("action") or None

                    remove_block = recipients.get("remove", {})
                    normalized_alert["recipients"]["remove"]["users"] = remove_block.get("users", [])
                    normalized_alert["recipients"]["remove"]["roles"] = remove_block.get("roles", [])
                    normalized_alert["recipients"]["remove"]["externals"] = remove_block.get("externals", [])

                    add_block = recipients.get("add", {})
                    normalized_alert["recipients"]["add"]["users"] = add_block.get("users", [])
                    normalized_alert["recipients"]["add"]["roles"] = add_block.get("roles", [])
                    normalized_alert["recipients"]["add"]["externals"] = add_block.get("externals", [])

                if normalized_alert["native_object"] and normalized_alert["custom_object"]:
                    normalized_alert["native_object"] = None  # Prefer custom_object

                if normalized_alert["offset_days"] is not None and normalized_alert["scheduled_cron"] is not None:
                    normalized_alert["scheduled_cron"] = None  # Priorizar offset_days

                normalized_alerts.append(normalized_alert)

            return normalized_alerts


        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {cleaned_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting email alert updates: {str(e)}")
        return None


# FUNCTION TO EXTRACT EMAIL ALERT DELETES (DELETE_EMAIL_ALERT)
def extract_email_alerts_deletes(user_message):
    """Use GPT to extract the details for email alerts to delete from the user message"""

    prompt = f"""
    Extract structured data from the user’s message to delete one or multiple email alerts.
    Return a JSON array of objects, where each object must include:

    - "alert_name" (string): The name of the email alert to be deleted.

    **Example Input & Output:**

    User: "I’d like to delete the alert with the name account_created__054"
    Response:
    [
        {{
            "alert_name": "account_created__054"
        }}
    ]

    User: "Delete the notification lead_created__009"
    Response:
    [
        {{
            "alert_name": "lead_created__009"
        }}
    ]

    User: "Delete opportunity_created__065 and account_created__065"
    Response:
    [
        {{
            "alert_name": "opportunity_created__065"
        }},
        {{
            "alert_name": "account_created__065"
        }}
    ]


    **Requirements:**
    - If "alert_name" is not specified, set it as null.

    **IMPORTANT:** **Return a valid JSON array only of objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured email alert deletions from user message."},
                {"role": "user", "content": prompt}
            ]
        )

        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # Quita ```json ... ```
        cleaned_response = clean_llm_response(raw_response)
        logging.info(f"\n\n🧹 Cleaned GPT Response: {cleaned_response}\n\n")

        try:
            extracted_alerts = json.loads(cleaned_response)

            # 🔑 Solo devolvemos lista de {alert_name}
            normalized_alerts = []
            for alert in extracted_alerts:
                normalized_alerts.append({
                    "alert_name": alert.get("alert_name") or None
                })

            return normalized_alerts

        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {cleaned_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting email alert deletions: {str(e)}")
        return None


def clean_llm_response(raw_response: str) -> str:
    # Clean triple backticks and text json if are present
    pattern = r"```(?:json)?\s*(.*?)\s*```"
    match = re.search(pattern, raw_response, re.DOTALL)
    if match:
        return match.group(1).strip()
    else:
        return raw_response.strip()