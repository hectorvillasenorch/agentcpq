import json
import os
import openai
import logging
from dotenv import load_dotenv

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
#OPENAI_MODEL = "gpt-3.5-turbo"
OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

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
        }}
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
    - If you cannot determine the correct value for any field (e.g., name, rule_type, target_type, priority, error_message, or conditions), set its value to null.
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