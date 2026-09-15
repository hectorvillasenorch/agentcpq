import json, os, re
import openai
import logging
from dotenv import load_dotenv
from agents.models import AgentPrompt

# System Prompt Helpers
from ..prompts_helpers.system_prompt_helpers import make_system_prompt

from agents.llm import chat_json, get_llm_client, get_model

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = get_llm_client()

def extract_validation_rules(user_message):
    """Uses GPT to extract description, rule type, target type, priority, error_message and conditions for Validations Rules."""

    prompt = f"""

    You are an expert assistant for a CPQ (Configure, Price, Quote) system. Your task is to extract structured business rule definitions from a natural language request written by a user.

    Always use the real Django model field paths, following these definitions:

    - Quote:
        - name (string)
        - account (FK → Account)
        - opportunity (FK → Opportunity)
        - discount_percentage (decimal)
        - discount_amount (decimal)
        - subtotal (decimal)
        - net_amount (decimal)
        - tax_percentage (decimal)
        - tax_amount (decimal)
        - status (string)
        - owner (FK → User)

    - QuoteLine:
        - quote (FK → Quote)
        - product (FK → Product)
        - quantity (int)
        - unit_price (decimal)
        - discount_percentage (decimal)
        - discount_amount (decimal)
        - total_price (decimal)

    - Account:
        - name (string)
        - industry (string)
        - city (string)
        - state (string)

    - Opportunity:
        - name (string)
        - account (FK → Account)
        - amount (decimal)
        - stage (string)

    Rules:
    - When referring to a foreign key field, always traverse it with dot notation.
    Correct example:
        quote.account.name
    
    Incorrect example:
        quote.account_name

    - Always use model field names exactly as defined above.
    - When comparing values for an Account name, use:
        "fieldName": "quote.account.name"
    - When comparing values for an Opportunity stage, use:
        "fieldName": "quote.opportunity.stage"
    - When comparing Quote numeric fields, use:
        "fieldName": "quote.discount_percentage", etc.

    Output format must remain the same.

    The output must be a single JSON array, where each object represents one rule. Each rule object must include the following keys:

    - description (string): The description of the rule. If the user specifies a description, use it. If not, generate a concise description that summarizes the rule purpose.
    - rule_type (string): Type of rule. Must be one of:
        - "validation"
        If the user does not explicitly mention it, infer it based on the intent.
	    - target_type (string): The primary object this rule applies to.
	        - For CPQ rules, prefer: "quote", "quote_line", "product", or "multiple".
	        - To extend beyond CPQ, you may also use any standard object key (snake_case), e.g.:
	          "account", "contact", "lead", "opportunity", "activity", "contract", "subscription", "option", "tenant", "knowledge".
	        - For custom objects, use the custom object API name ending with "__c", e.g. "proyecto__c".
	        If the rule uses fields from more than one object root, set this to "multiple".
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
	    - Always include fieldName in full dotted format: <root>.<field_path>.
	      Examples:
	        - quote.account.name
	        - quote.opportunity.stage
	        - opportunity.stage
	        - contract.contract_status
	        - custom_record.rendimiento__c
	      For custom object rules (target_type ending in __c), use root "custom_record" and custom field API names (e.g. rendimiento__c).
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
    user_prompt = user_message

    try:
        response = chat_json(client,
            model=get_model("structured"),
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






def extract_inclusion_rules(user_message, current_state, previous_summary=None):
    """
    Uses LLM to extract structured data for creating inclusion rules.
    Returns JSON and agent message.
    """

    system_prompt, temperature = make_system_prompt("admin_agent", "create", "extract_inclusion_rules", previous_summary)

    user_prompt = user_message

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    response = chat_json(client,
        model=get_model("structured"),
        messages=messages,
        temperature=temperature
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

    try:
        result_json = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
        return None

    # Normalize structure
    normalized_rules = []
    for item in result_json.get("create_inclusion_rule", []):
        data = item.get("data", {})

        # --- Defaults for top-level fields ---
        data["rule_type"] = "inclusion"
        data["target_type"] = data.get("target_type") or "quote_line"
        data["priority"] = data.get("priority", 10)
        data["active"] = data.get("active", True)

        # --- Handle trigger_product ---
        trigger_product = data.get("conditions", {}).get("trigger_product", {})
        trigger_product = {
            "sku": trigger_product.get("sku"),
            "name": trigger_product.get("name")
        }

        # --- Handle included_products ---
        included_products = data.get("conditions", {}).get("included_products", [])
        normalized_included = []
        for p in included_products:
            normalized_included.append({
                "sku": p.get("sku"),
                "name": p.get("name"),
                "quantity": p.get("quantity", 1)
            })

        # --- Build normalized conditions ---
        conditions = {
            "trigger_product": trigger_product,
            "included_products": normalized_included,
            "options": data.get("conditions", {}).get("options", []),
            "applies_to": data.get("conditions", {}).get("applies_to")
        }

        normalized_rules.append({
            "data": {
                "description": data.get("description"),
                "rule_type": "inclusion",
                "target_type": data.get("target_type"),
                "priority": data.get("priority"),
                "message": data.get("message"),
                "active": data.get("active"),
                "conditions": conditions
            },
            "completed": item.get("completed", False)
        })

    result_json["create_inclusion_rule"] = normalized_rules

    return result_json


def extract_exclusion_rules(user_message, current_state, previous_summary=None):
    """
    Uses LLM to extract structured data for creating exclusion rules.
    Returns JSON and agent message.
    """

    system_prompt = """
    You are a helpful AI assistant that create exclusion rules from user message.
    An exclusion rule prevents two products from coexisting in a quotation; these products are called excluded_products.
    Always return JSON with structure:
    {
        "create_exclusion_rule": [
            {
                "data": {
                    "description": null,
                    "rule_type": "exclusion",
                    "target_type": null,
                    "priority": 10,
                    "error_message": null,
                    "active": true,
                    "conditions": {
                        "excluded_products": []
                    }
                },
                "completed": False
            }
        ],
        "agent_message": "string",
        "summary": "string"
    }

    The excluded products must have this structure inside the "excluded_products" key: 
    {
        ["product1", "product2", "product3"]
    }

    Rules:
    1. If the user does not specify a description, then create a short description for the rule.  
    2. The `rule_type` must ALWAYS be `"exclusion"`.
    3. The `target_type` must ALWAYS be `"quote_line"`.
    4. If the user does not specify a priority value, set it to `10`.
    5. If the user does not specify an error_message, then create a short error_message to indicate to the user what is happening with the exclusion rule.
    6. If the user does not specify `active`, then set it to `true`.

    ---

    Rules for conditions:
    1. There must be at least two products in "excluded_products" within "conditions" for a rule to be considered completed (True).

    Agent message:
    - Interpret this as an attempt, therefore do not say things like "created successfully".
    - If a trigger_product is not mentioned, respond naturally by asking the user which product should be the trigger. Use language that a regular user can understand, without emphasizing technical or internal terms. You may mention "trigger product" if it helps with clarity, but keep the message intuitive.
    - Generate a natural response for the user explaining what happened: updates, errors, missing information, questions for the user, data requests, etc.
    - Be brief, professional, and natural.
    - Do not be technical.
    - Continue naturally (DO NOT start with "Hello").
    - Use <br> for line breaks.
    - Include information if the user attempted to create an inclusion rule.

    Summary:
    - Create a short summary combining previous summary + this iteration.
    """

    user_prompt = f"""
    User message: "{user_message}"

    Current state:
    {json.dumps(current_state, indent=2)}

    Previous summary:
    {previous_summary if previous_summary else "None"}

    Return JSON as described above.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    response = chat_json(client,
        model=get_model("structured"),
        messages=messages,
        temperature=1
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

    try:
        result_json = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
        return None

    # ✅ Normalize structure for exclusion rules (nuevo esquema)
    normalized_rules = []

    for rule in result_json.get("create_exclusion_rule", []):
        data = rule.get("data", {})

        normalized_data = {
            "description": data.get("description") or "Auto-generated exclusion rule",
            "rule_type": "exclusion",
            "target_type": data.get("target_type") or "quote_line",
            "priority": data.get("priority", 10),
            "error_message": data.get("error_message") or "This product cannot be added because another conflicting product is present in the quote.",
            "active": data.get("active", True),
            "conditions": {
                "excluded_products": data.get("conditions", {}).get("excluded_products", [])
            }
        }

        # --- Determine completion ---
        has_excluded = len(normalized_data["conditions"]["excluded_products"]) > 0
        completed = has_excluded  # Solo revisamos si hay productos excluidos

        normalized_rules.append({
            "data": normalized_data,
            "completed": completed
        })

    result_json["create_exclusion_rule"] = normalized_rules

    return result_json



def extract_rules_details_to_render(user_message, current_state, previous_summary=None):
    """Extracts name, rule_type, target_type, priority, and active fields from rules using GPT to display them to the user."""

    system_prompt, temperature = make_system_prompt("admin_agent", "create", "extract_rules_details_to_render", previous_summary)

    user_prompt = user_message

    try:
        response = chat_json(client,
            model=get_model("structured"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
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
def extract_rule_updates(user_message, current_state, previous_summary=None):
    """Uses GPT to extract rule name, field, and new value for rules updates."""

    system_prompt, temperature = make_system_prompt("admin_agent", "update", "extract_rule_updates", previous_summary)

    user_prompt = user_message

    try:
        response = chat_json(client,
            model=get_model("structured"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
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

    system_prompt, temperature = make_system_prompt("admin_agent", "delete", "extract_rule_deletes")

    user_prompt = user_message

    try:
        response = chat_json(client,
            model=get_model("structured"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
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


    system_prompt, temperature = make_system_prompt("admin_agent", "update", "extract_custom_object_updates")

    user_prompt = user_message

    try:
        response = chat_json(client,
            model=get_model("structured"),
            messages=[
                {"role": "system", "content": "Extract structured updates details for rules."},
                {"role": "user", "content": user_prompt}
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
        response = chat_json(client,
            model=get_model("structured"),
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

    system_prompt, temperature = make_system_prompt("admin_agent", "update", "extract_email_alert_updates")

    system_prompt += "The list of custom objects is: " + custom_objects
    system_prompt += "The list of users is: " + users
    system_prompt += "The current username: " + user.username

    user_prompt = user_message

    try:
        response = chat_json(client,
            model=get_model("structured"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
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
        response = chat_json(client,
            model=get_model("structured"),
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
