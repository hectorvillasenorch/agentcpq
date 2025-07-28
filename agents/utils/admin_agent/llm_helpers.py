import json
import os
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