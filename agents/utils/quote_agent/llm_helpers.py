import json
import re
import os
import openai
import logging
from dotenv import load_dotenv
from datetime import date
from cpq.models import Quote
from django.forms.models import model_to_dict

# System Prompt Helpers
from ..prompts_helpers.system_prompt_helpers import make_system_prompt

# Agents Helpers
from ..agents_utils import clean_llm_json

# Models
from cpq.models import Opportunity

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"
# OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

from ..orchestrator.context_handle_helpers import estimate_cost
from ..message_formatters import format_message_with_standard_icons, INFO_ICON, SUCCESS_ICON, ERROR_ICON, WARNING_ICON



# ------ FUNCTION TO EXTRACT QUOTE DETAILS (CREATE_QUOTE) ------
def extract_quote_details_with_llm(user_message, current_state, previous_summary=None):
    """Extract multiple product SKUs, quantities, and discounts from user input using GPT."""

    system_prompt = """
    You are a helpful AI assistant that details from the user's request for quote creation:
    Always return JSON with structure:
    {
        "create_quote": {
            "data": {
                "account": null,
                "opportunity": null,
                "products": [
                    {
                        "sku": null,
                        "name": null,
                        "quantity": null,
                        "discount_type": null,
                        "discount_value": null,
                        "term": null
                    }
                ],
                "start_date": "",
                "end_date": ""
            },
            "completed": False
        },
        "agent_message": "string",
        "summary": "string"
    }

    For each product (ONLY if products are mentioned):
    - "sku" (string or null): The SKU is usually uppercase letters and hyphens, e.g. "SYM-HY-BGI".
        If SKU is not mentioned or not found, set it to null (not the string "null").
    - "name" (string or null): The product name.
        If name is not mentioned or not found, set it to null (not the string "null").
    - "quantity" (integer): Quantity of the product. If quantity is not mentioned but products exist, set quantity to 1 by default (as an integer, not a string).
    - "discount_type" (string): Discount type, either "percentage" or "amount".
    - "discount_value" (integer): Discount value without any dollar signs, percent signs, or text; only the numeric value.
    - "term" (integer or null): If term is mentioned, return it as an integer (not a string). If term is not mentioned, set term to null (not a string).

    For discounts:
    - If the user specifies a percentage discount (e.g. "15%"), set discount_type to "percentage" and discount_value to the numeric value (e.g. 15).
    - If the user specifies a discount in dollars, with symbols or the word "dollar(s)" (e.g. "$100" or "100 dollars"), set discount_type to "amount" and discount_value to the numeric amount (e.g. 100).
    - If no discount is specified, set discount_type to null and discount_value to 0.
    - If no term is specified, set term to null.

    If no products are provided in the request, return a JSON object with these keys:
    {
        "create_quote": {
            "data": {
                "account": null,
                "opportunity": null,
                "products": [],
                "start_date": "",
                "end_date": ""
            },
            "completed": False
        },
        "agent_message": "string",
        "summary": "string"
    }

    Rules:
    - Treat the JSON as ATTEMPTS to create a quote, NOT confirmations.
    - Required field: account.
    - completed = true if the user has provided a valid "account" value, regardless of other fields.
    - If "account" is missing, completed = false.
    - If completed=false, agent_message must politely ask for missing information instead of confirming the addition.
    - NEVER say "quote has been created" or similar; only acknowledge the user's request or attempt.
    - agent_message should be short, natural, professional, and can ask follow-up questions.
    - This message is a continuation of an ongoing conversation. Do NOT start with greetings like 'Hello' or 'Hi'. Just continue naturally.
    - The message is sensitive to HTML tags, so if you want to make line breaks use the <br> tag.
    - Create a short, detailed summary that extends the previous summary with changes from this iteration.
    - The summary must always explain the current state + why completed is false (if false) OR confirm completeness (if true).
    - Products are optional, if the user does not specify any it is not an indicator that completed has to be false.
    - Opportunity is optional, only account is required, if account is provided by the user, mark completed as true.
    - Return the response as strict JSON. Do not include comments, explanations, or trailing commas.
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

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 FIRST LLM - Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=1
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response (original):\n{raw_response}\n")

    # 🔹 Use the reusable cleaning function
    result_json = clean_llm_json(raw_response)
    if result_json is None:
        logging.error("❌ Failed to clean/parse LLM JSON response.")
        return None, tokens_used, cost_est

    # --- Normalizar structure ahora que create_quote es un dict ---
    create_quote_raw = result_json.get("create_quote", {})
    data = create_quote_raw.get("data", {})

    # Normalizar productos
    products = []
    for p in data.get("products", []):
        products.append({
            "sku": p.get("sku"),
            "name": p.get("name"),
            "quantity": p.get("quantity", 1),
            "discount_type": p.get("discount_type"),
            "discount_value": p.get("discount_value", 0),
            "term": p.get("term")
        })

    normalized_quote = {
        "data": {
            "account": data.get("account"),
            "opportunity": data.get("opportunity"),
            "products": products,
            "start_date": data.get("start_date"),
            "end_date": data.get("end_date")
        },
        # ✅ completed = True si hay account
        "completed": bool(data.get("account"))
    }

    # Sobrescribir create_quote
    result_json["create_quote"] = normalized_quote

    return result_json, tokens_used, cost_est



def generate_final_create_quote_message(quote, db_results, previous_summary, products=None, formatted_message=None):
    """
    Generates in ONE LLM call:
    1) A concise, professional, emoji-rich message for the user.
    2) An updated short summary that extends the previous summary with changes from this iteration.
    Returns (message_text, updated_summary, tokens_used, cost_est).
    """

    #successful = [r['product'] for r in db_results if r['status'] == 'success']
    #failed = [(r['product'], r['error']) for r in db_results if r['status'] == 'fail']

    final_prompt = f"""
    This is an ongoing conversation about quote creation.
    The assistant should return a JSON with two fields only: "message" and "summary".

    Context:
    - User initially wanted to create this quote: {quote}.
    - User initially wanted to add these products to quote: {products}.
    - Here you have all the backend messages about the quote creation and the products that were attempted to be added to the quote: {db_results}.
    - Previous summary: {previous_summary}.

    Instructions for "message":
    - Be short, friendly, professional, natural, ask follow-ups, concise but specific and friendly.
    - Convert all messages that occurred while attempting to create the initial quote into a natural, user-friendly message; you can use the exact same message from the backend if you prefer.
    - Always mention the quote name.
    - Remember that products are optional when creating a quote, so if no products are included, do not mention it in the message; instead, ask the user if they would like to add products now.
    - Provide the quote details, including account and opportunity.
    - Mention only which products were successfully added and which are still pending or incomplete.
    - Do NOT include the detailed changes made to each product; those details are already captured in the "summary".
    - For failed products added, mention the quote line and its error, but only if there are any.
    - For incomplete products, briefly mention them ONLY if there are any.
    If none exist, omit this section entirely (do not mention that there are no incomplete products).
    - Omit entire sections if there are no products in that category.
    - End by asking a short, natural follow-up question about next steps.
    - The message is user-facing and can use <br> for line breaks.
    - If an add fails, explain it as a short, natural comment for the user, not as a system error. Keep it user-friendly and conversational, not technical or formal.
    - NEVER start the message with phrases like "Great news!", "Good job!", "Perfect!", or similar interjections.
    - Do not include emojis; visual status indicators are handled downstream.
    - Do not put information about net amount.
    - Show the information of the triggered rules.
    Begin directly with the content.

    Instructions for "summary":
    - Write a short but detailed summary that continues the previous summary with the new changes.
    - Summarize successes, failures, and incompletes in 2–4 sentences max.
    - The summary is NOT for the user directly, it's for keeping track of progress across iterations.

    ⚠️ IMPORTANT: Return ONLY valid JSON in this format:
    {{
        "message": "...",
        "summary": "..."
    }}
    """

    messages_for_llm = [
        {"role": "system", "content": (
            "You are a concise, professional AI assistant. "
            "Always write in a natural and neutral tone. "
            "Never start with interjections or phrases like 'Great news!', 'Good job!', 'Awesome!', etc. "
            "Just provide the explanation or follow-up directly."
        )},
        {"role": "user", "content": final_prompt}
    ]

    tokens_used, cost_est = estimate_cost(messages_for_llm, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages_for_llm,
        temperature=0.7,
        response_format={"type": "json_object"}  # fuerza JSON válido (si usas GPT-4.1 / GPT-4o / GPT-5)
    )

    raw_output = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT JSON Response Create quote methond: {raw_output}\n\n")

    try:
        parsed = json.loads(raw_output)
        message = parsed.get("message", "").strip()
        updated_summary = parsed.get("summary", "").strip()
    except Exception as e:
        logging.error(f"❌ Error parsing LLM JSON output: {e}")
        message = raw_output
        updated_summary = previous_summary

    if formatted_message:
        message = formatted_message

    return message, updated_summary, tokens_used, cost_est



# FUNCTION TO EXTRACT PRODUCT DETAILS (ADD_PRODUCT_TO_QUOTE)
def extract_products_to_add_with_llm(user_message, current_state, previous_summary=None, quote_name=None):
    """Extract multiple product SKUs, quantities, and discounts from user input using GPT."""

    current_date = date.today().strftime("%Y-%m-%d")
    active_quote_name = quote_name or "the active quote"

    system_prompt = """
    You are a helpful AI assistant that extracts product line items to add to an existing quote from the user's message.
    Always return JSON with structure:
    {
        "add_product_to_quote": [
            {
                "data": {
                    "quote_name": null,
                    "sku": null,
                    "name": null,
                    "quantity": null,
                    "discount_type": null,
                    "discount_value": null,
                    "term": null
                },
                "completed": false
            }
        ],
        "agent_message": "string",
        "summary": "string"
    }

    Requirements:
    - For discounts, if the user specifies a percentage (e.g., "15% discount"), return field: "discount_percentage" and value: 15. If the user specifies a dollar amount (e.g., "$150 off", "150 dollars discount" or just a number like "150"), return field: "discount_amount" and value: 150. Always extract only the numeric value — remove symbols like % or $, and ignore words like "off", "discount", or "dollars".
    - Always normalize discount values to plain numbers.
    - If the user specifies a status value, always normalize it to match one of the following exact formats: "Draft", "Pending Approval", "Approved", "Rejected", or "Closed". Use title casing and ensure the value matches exactly (case-sensitive).
    - If no quote name are found in the message, return null as quote_name.
    - If no field are found in the message, return null as field.
    - If no value are found in the message, return null as value.
    - If the user specifies words like remove or delete discount, then set field as "discount_percentage" and value = 0.
    - For expiration dates, always return the value as a string in ISO 8601 format (YYYY-MM-DD), which is compatible with Python and Django. For example, July 30, 2025 → "2025-07-30".
    - For notes, always ensure the returned value ends with a period (.). If the user's note doesn't end with one, automatically add it to the end of the note.
    """
    system_prompt += f"""
    - The current date is {current_date}. Use this as the reference point when interpreting relative dates like "next Friday", "tomorrow", or "in two weeks".
    """

    system_prompt += f"""
    Rules:
    - Treat the JSON as ATTEMPTS to update quote, NOT confirmations.
    - If the user provides the quote name, use that, otherwise use the name of the active quote name: {active_quote_name}
    - Do NOT include explanations.
    - Do NOT wrap the result in Markdown or use triple backticks.
    - Return only a single JSON object.
    - Required fields: quote_name, field and value.
    - completed=true if quote_name, field and value are present.
    - If quote_name, field and value are provided by the user, mark completed as true.
    - If completed=false, agent_message must politely ask for missing information instead of confirming the addition.
    - NEVER say "quote has been updated" or similar; only acknowledge the user's request or attempt.
    - agent_message should be short, friendly, professionalz, and can ask follow-up questions.
    - This message is a continuation of an ongoing conversation. Do NOT start with greetings like 'Hello' or 'Hi'. Just continue naturally.
    - The message is sensitive to HTML tags, so if you want to make line breaks use the <br> tag.
    - Create a short, detailed summary that extends the previous summary with changes from this iteration.
    - The summary must always explain the current state + why completed is false (if false) OR confirm completeness (if true).
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

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 FIRST LLM - Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=1
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

    try:
        result_json = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
        return None, tokens_used, cost_est

    # Normalize structure
    normalized_products = []
    for prod in result_json.get("update_quote", []):
        normalized_products.append({
            "data": {
                "quote_name": prod.get("data", {}).get("quote_name") or prod.get("quote_name"),
                "field": prod.get("data", {}).get("field") or prod.get("field"),
                "value": prod.get("data", {}).get("value") or prod.get("value")
            },
            "completed": prod.get("data", {}).get("completed", prod.get("completed", False))
        })
    result_json["update_quote"] = normalized_products

    return result_json, tokens_used, cost_est

def generate_final_quote_updates_message(completed_quote_updates, db_results, remaining_quote_updates, previous_summary):
    """
    Generates in ONE LLM call:
    1) A concise, professional, emoji-rich message for the user.
    2) An updated short summary that extends the previous summary with changes from this iteration.
    Returns (message_text, updated_summary, tokens_used, cost_est).
    """

    #successful = [r['product'] for r in db_results if r['status'] == 'success']
    #failed = [(r['product'], r['error']) for r in db_results if r['status'] == 'fail']

    final_prompt = f"""
    This is an ongoing conversation about quote line deletions.
    The assistant should return a JSON with two fields only: "message" and "summary".

    Context:
    - User initially wanted to update this quote: {completed_quote_updates}.
    - Here you have all the backend messages about the quote updates and the quote that were attempted to be updated to the quote: {db_results}.
    - Quote updates still incomplete: {remaining_quote_updates}
    - Previous summary: {previous_summary}.

    Instructions for "message":
    - Be short, friendly, professional, natural, ask follow-ups, concise but specific and friendly.
    - Convert all the messages that appeared when removing the quote updates into a natural, user-friendly message; you can use the exact same message from the backend if you prefer.
    - Always mention the quote name.
    - Use symple emojis.
    - Mention only which quote updates were successfully and which are still pending or incomplete.
    - Do NOT include the detailed changes made to each quote update; those details are already captured in the "summary".
    - Do not specify if there are no incomplete quote updates.
    - Do not specify that there are no pending updates.
    - For failed quote updates, mention the quote and its error, but only if there are any.
    - For incomplete quote updated, briefly mention them ONLY if there are any.
    If none exist, omit this section entirely (do not mention that there are no incomplete quote).
    - Omit entire sections if there are no products in that category.
    - End by asking a short, natural follow-up question about next steps.
    - The message is user-facing and can use <br> for line breaks.
    - If an add fails, explain it as a short, natural comment for the user, not as a system error. Keep it user-friendly and conversational, not technical or formal.
    - NEVER start the message with phrases like "Great news!", "Good job!", "Perfect!", or similar interjections.
    - Use this emoji: ✅ to indicate that a quote has been successfully updated.
    Begin directly with the content.

    Instructions for "summary":
    - Write a short but detailed summary that continues the previous summary with the new changes.
    - Summarize successes, failures, and incompletes in 2–4 sentences max.
    - The summary is NOT for the user directly, it's for keeping track of progress across iterations.

    ⚠️ IMPORTANT: Return ONLY valid JSON in this format:
    {{
        "message": "...",
        "summary": "..."
    }}
    """

    messages_for_llm = [
        {"role": "system", "content": (
            "You are a concise, professional AI assistant. "
            "Always write in a natural and neutral tone. "
            "Never start with interjections or phrases like 'Great news!', 'Good job!', 'Awesome!', etc. "
            "Just provide the explanation or follow-up directly."
        )},
        {"role": "user", "content": final_prompt}
    ]

    tokens_used, cost_est = estimate_cost(messages_for_llm, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages_for_llm,
        temperature=0.7,
        response_format={"type": "json_object"}  # fuerza JSON válido (si usas GPT-4.1 / GPT-4o / GPT-5)
    )

    raw_output = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT JSON Response FInal Quote Updates: {raw_output}\n\n")

    try:
        parsed = json.loads(raw_output)
        message = parsed.get("message", "").strip()
        updated_summary = parsed.get("summary", "").strip()
    except Exception as e:
        logging.error(f"❌ Error parsing LLM JSON output: {e}")
        message = raw_output
        updated_summary = previous_summary

    if message:
        message_lower = message.lower()
        success_triggers = [
            "successfully updated",
            "successfully created",
            "successfully deleted",
            "successfully removed",
            "successfully",
            "success",
            "updated",
            "created",
            "deleted",
            "removed",
        ]

        if (
            not message.lstrip().startswith("<span")
            and "not success" not in message_lower
            and "not successfully" not in message_lower
            and "unsuccess" not in message_lower
            and any(trigger in message_lower for trigger in success_triggers)
        ):
            message = f"{SUCCESS_ICON} {message.strip()}"

    message = format_message_with_standard_icons(message)

    if message:
        formatted_lower = message.lower()
        if (
            not message.lstrip().startswith("<span")
            and "not success" not in formatted_lower
            and "not successfully" not in formatted_lower
            and "unsuccess" not in formatted_lower
            and any(trigger in formatted_lower for trigger in (
                "successfully updated",
                "successfully created",
                "successfully deleted",
                "successfully removed",
                "successfully",
                "success",
                "updated",
                "created",
                "deleted",
                "removed",
            ))
        ):
            message = f"{SUCCESS_ICON} {message.strip()}"

    if message:
        separator = "<br>" if "<br>" in message else "\n"
        segments = message.split(separator)
        if segments:
            first_segment = segments[0].strip()
            if first_segment and not first_segment.startswith((SUCCESS_ICON, INFO_ICON, ERROR_ICON, WARNING_ICON)):
                segments[0] = f"{SUCCESS_ICON} {first_segment}"
                message = separator.join(segments)

    return message, updated_summary, tokens_used, cost_est



# FUNCTION TO EXTRACT QUOTE LINE ITEMS TO DELETE (DELETE_QUOTE_LINE)
def extract_quote_line_items_to_delete(user_message):
    """Uses GPT to extract quote line name."""

    prompt = f"""
    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**

    Extract the SKU (product code) or name mentioned in the following user request.

    Return only the SKU and name string inside a JSON object like this:
     [{{"sku": "<SKU_CODE>", "name": "<PRODUCT_NAME>"}}]

    **Rules:**
    - If no SKU is found in the message, return: {{"sku": null}}
    - If no name is found in the message, return: {{"name": null}}
    - Do NOT include explanations.
    - Do NOT wrap the result in Markdown or use triple backticks.
    - Return only a single JSON object.


    **Examples:**

    User: "Remove AI-CPQ-10 from the quote and remove ProductName1"
    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-10", "name": null}},
        {{"sku": null, "name": "ProductName1"}}
    ]

    User: "Delete product with SKU AI-CPQ-55"
    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-55", "name": null}}
    ]

    User: "Remove the product"
    **Expected JSON Output:**
    [
        {{"sku": null, "name": null}}
    ]

    **IMPORTANT:** **Return a valid JSON array only of SKU and name. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract the SKU or NAME mentioned in the user's request."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_sku = json.loads(raw_response)
            if isinstance(extracted_sku, list) and all("sku" in p and "name" in p for p in extracted_sku):
                return extracted_sku
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting discount details: {str(e)}")
        return None









def extract_quote_line_to_delete_with_llm(user_message, current_state, previous_summary=None):
    """Extract multiple product SKUs, quantities, and discounts from user input using GPT."""

    # 👉 Si es lista, imprimir con índices
    if isinstance(current_state, list):
        print("\n📦 Current State (indexed):")
        for idx, item in enumerate(current_state, start=1):
            print(f"\n[{idx}] {json.dumps(item, indent=2)}")
    else:
        # 👉 Si es dict, imprimir directo formateado
        print("\n📦 Current State (dict):")
        print(json.dumps(current_state, indent=2))

    system_prompt = """
    You are a helpful AI assistant that extracts quote lines data from user messages.
    Always return JSON with structure:
    {
        "delete_quote_line": [
            {
                "data": {
                    "sku": null,
                    "name": null,
                    "quantity": null,
                    "discount_type": null,
                    "discount_value": null,
                    "term": null
                },
                "completed": False
            },
        ],
        "agent_message": "string",
        "summary": "string"
    }

    Rules:
    - Treat the JSON as ATTEMPTS to add products, NOT confirmations.
    - Required fields: (SKU and quantity) OR (Name and quantity).
    - completed=true if one of these combinations is present:
    1. SKU + quantity
    2. Name + quantity
    - If the sku and quantity have been provided by the user, mark completed as true.
    - If the name and quantity have been provided by the user, mark completed as true.
    - Do NOT ask for both SKU and Name if one of them is already present.
    - Optional: discount_value and term.
    - completed=true only if required fields are present.
    - If completed=false, agent_message must politely ask for missing information instead of confirming the addition.
    - NEVER say "product has been added" or similar; only acknowledge the user's request or attempt.
    - agent_message should be short, friendly, professionalz, and can ask follow-up questions.
    - This message is a continuation of an ongoing conversation. Do NOT start with greetings like 'Hello' or 'Hi'. Just continue naturally.
    - The message is sensitive to HTML tags, so if you want to make line breaks use the <br> tag.
    - Create a short, detailed summary that extends the previous summary with changes from this iteration.
    - The summary must always explain the current state + why completed is false (if false) OR confirm completeness (if true).
    - If quantity is missing, assume 1 by default, but still mark completed=false unless the user confirmed it explicitly.
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

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 FIRST LLM - Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=1
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")
    result_json = clean_llm_json(raw_response)
    

    # 🔹 Use the reusable cleaning function
    if result_json is None:
        logging.error("❌ Failed to clean/parse LLM JSON response.")
        return None, tokens_used, cost_est

    normalized_products = []
    for prod in result_json.get("add_product_to_quote", []):
        data = prod.get("data", {})
        normalized_products.append({
            "data": {
                "sku": data.get("sku") or prod.get("sku"),
                "name": data.get("name") or prod.get("name"),
                "quantity": data.get("quantity") if data.get("quantity") is not None else 1,
                "discount_type": data.get("discount_type"),
                "discount_value": data.get("discount_value") if data.get("discount_value") is not None else 0,
                "term": data.get("term")
            },
            "completed": bool(data.get("completed", prod.get("completed", False)))
        })

    for prod in normalized_products:
        data = prod["data"]
        has_identifier = bool(data.get("sku") or data.get("name"))
        has_quantity = (data.get("quantity") is not None and data.get("quantity") > 0)

        if has_identifier and has_quantity:
            prod["completed"] = True
        else:
            prod["completed"] = False

    result_json["add_product_to_quote"] = normalized_products

    return result_json, tokens_used, cost_est

def generate_final_add_product_to_quote_message(completed_products, db_results, remaining_products, previous_summary):
    """
    Generates in ONE LLM call:
    1) A concise, professional, emoji-rich message for the user.
    2) An updated short summary that extends the previous summary with changes from this iteration.
    Returns (message_text, updated_summary, tokens_used, cost_est).
    """

    successful = [
        {
            'product': r['product'],
            'inclusion_message': r.get('inclusion_message')  # usa get por si no existe
        }
        for r in db_results
        if r['status'] == 'success'
    ]
    failed = [(r['product'], r['error']) for r in db_results if r['status'] == 'fail']

    final_prompt = f"""
    This is an ongoing conversation about add products to quote.
    The assistant should return a JSON with two fields only: "message" and "summary".

    Context:
    - User initially wanted to add to quote these products: {completed_products}.
    - Products successfully added: {successful}.
    - Products failed to add (with errors): {failed}.
    - Products still incomplete: {remaining_products}.
    - Previous summary: {previous_summary}.

    Instructions for "message":
    - Be short, friendly, professional, natural, ask follow-ups, concise but specific and friendly.
    - Mention only which products were successfully added and which are still pending or incomplete.
    - Do NOT include the detailed changes made to each product; those details are already captured in the "summary".
    - For failed products added, mention the quote line and its error, but only if there are any.
    - For incomplete products, ONLY mention them if they exist.
    - If there are none, do not write anything about them at all.
    - Absolutely never write phrases like "There are no incomplete products" or "There are no pending items".
    - Omit entire sections if there are no products in that category.
    - End by asking a short, natural follow-up question about next steps.
    - The message is user-facing and can use <br> for line breaks.
    - If an add fails, explain it as a short, natural comment for the user, not as a system error. Keep it user-friendly and conversational, not technical or formal.
    - NEVER start the message with phrases like "Great news!", "Good job!", "Perfect!", or similar interjections.
    - Do not include emojis; visual status indicators are handled downstream.
    Begin directly with the content.
    - Don't specify that there were no errors when adding products.
    - Don't specify that there are no incomplete items.
    - If there are no pending or incomplete products, do not mention that fact in the message. Only include pending or incomplete products when they exist.

    Instructions for "message" and "inclusion_message"
    - If the key "inclusion_message" is included in the database response, add a message indicating the products that were added, their quantities, and which product triggered the rule. The details will be in the "inclusion rule" key.

    Instructions for "summary":
    - Write a short but detailed summary that continues the previous summary with the new changes.
    - Summarize successes, failures, and incompletes in 2–4 sentences max.
    - The summary is NOT for the user directly, it's for keeping track of progress across iterations.

    ⚠️ IMPORTANT: Return ONLY valid JSON in this format:
    {{
        "message": "...",
        "summary": "..."
    }}
    """

    messages_for_llm = [
        {"role": "system", "content": (
            "You are a concise, professional AI assistant. "
            "Always write in a natural and neutral tone. "
            "Never start with interjections or phrases like 'Great news!', 'Good job!', 'Awesome!', etc. "
            "Just provide the explanation or follow-up directly."
        )},
        {"role": "user", "content": final_prompt}
    ]

    tokens_used, cost_est = estimate_cost(messages_for_llm, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages_for_llm,
        temperature=0.7,
        response_format={"type": "json_object"}  # fuerza JSON válido (si usas GPT-4.1 / GPT-4o / GPT-5)
    )

    raw_output = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT JSON Response Delete QuoteLines: {raw_output}\n\n")

    try:
        parsed = json.loads(raw_output)
        message = parsed.get("message", "").strip()
        updated_summary = parsed.get("summary", "").strip()
    except Exception as e:
        logging.error(f"❌ Error parsing LLM JSON output: {e}")
        message = raw_output
        updated_summary = previous_summary

    return message, updated_summary, tokens_used, cost_est


def extract_quote_line_updates_with_llm(user_message, current_state, previous_summary=None, line_items_on_user_message=None):
    """
    Uses LLM to extract structured quote line updates from user input.
    Returns JSON, tokens used, and estimated cost.
    """

    allowed_fields_str = '", "'.join(["quantity", "discount_amount", "discount_percentage", "term"])
    current_date = date.today().strftime("%Y-%m-%d")

    system_prompt = """
    You are a helpful AI assistant that updates quote line items from user messages.
    Always return JSON with structure:
    {
    "update_quote_line": [
        {
            "data": {
                "sku": null,
                "name": null,
                "field": null,
                "value": null
            },
            "completed": false
        }
    ],
    "agent_message": "string",
    "summary": "string"
    }


    Rules:
    1. I will provide you with a list of dictionaries containing the line items mentioned by the user in their message under "Current line items mentioned." Your task is to modify only the field the user specifies with the values they provide.

    2. If the user attempts to modify a line item that is not found in "Current line items mentioned," indicate in the agent_message that the product is not in the quote.

    """

    system_prompt += f"""
    3. Modify only the field mentioned by the user, the only fields can be updated are: {allowed_fields_str}
    """

    system_prompt += """
    4. If the user attempts to do anything other than update a line item, do not modify any data and indicate in the agent_message that this agent can only update a line item/quote_lines.

    5. For discounts, if the user specifies a percentage (e.g., "15% discount"), return field: "discount_percentage" and value: 15. If the user specifies a dollar amount (e.g., "$150 off" or "150 dollars discount"), return field: "discount_amount" and value: 150. Always extract only the numeric value - remove symbols like % or $, and ignore words like "off", "discount" or "dollars".

    6. Always normalize discount values to plain numbers.

    7. If the user's intention is to delete the value of a field, set that value to 0.


    9. Mark "completed" as true if a line item receives an update, provided it is within the following parameters:
    - quantity: integer >= 0
    - term: integer between 1 and 12
    - discount_percentage: between 0 and 100
    - discount_amount: >= 0 and <= unit_price (if unit_price is provided)

    10. Support flexible update actions: add, remove, delete, multiply, duplicate, divide, among others.

    11. When the user provides multiple updates (e.g., apply a discount and change a quantity),
        you MUST return one entry per update in the array `update_quote_line`.

    - Only update the fields explicitly mentioned by the user.
    - Do not include unchanged information in the agent_message.
    - Only include line items in "update_quote_line" if at least one field is actually modified. Do not include line items where no changes were applied.
    - If a line item has no changes, do not include it in update_quote_line


    Agent message:
    - Interpret this as an attempt, therefore do not say things like 'has been successfully updated'.
    - If no products or quote lines are mentioned in "Current line items mentioned", respond naturally asking the user which products they want to update. Use language that a regular user would understand, without emphasizing technical or internal terms. It's okay to mention 'quote lines' if it helps clarity, but keep the message user-friendly.
    - Generate a natural response for the user explaining what happened: updates, errors, missing information, questions for the user, requests for data, etc.
    - Short, professional, natural.
    - Don't be technical.
    - Continue naturally (do NOT start with 'Hello' or 'Hi')
    - Use <br> for line breaks
    - Include information if the user tried to update a product that does not exist.
    - Do not explain if there are no failed or incomplete quote lines.
    - If the user requests to modify a field but the value would be the same as the existing one, explain naturally that no changes were applied because the value is already the same.

    Summary:
    - Create a short summary combining previous summary + this iteration.
    """


    user_prompt = f"""
    User message: "{user_message}"

    Current line items mentioned:
    {json.dumps(line_items_on_user_message, indent=2)}

    Previous summary:
    {previous_summary if previous_summary else "None"}

    Return JSON as described above.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 LLM - Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.8
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

    # 🔹 Use the reusable cleaning function
    result_json = clean_llm_json(raw_response)
    if result_json is None:
        logging.error("❌ Failed to clean/parse LLM JSON response.")
        return None, tokens_used, cost_est

    # Normalize structure
    normalized_updates = []
    for item in result_json.get("update_quote_line", []):
        data = item.get("data", {})

        # Si 'data' es lista, tomamos el primer dict
        if isinstance(data, list) and data:
            data = data[0]

        normalized_updates.append({
            "data": {
                "sku": data.get("sku"),
                "name": data.get("name"),
                "field": data.get("field"),
                "value": data.get("value")
            },
            "completed": item.get("completed", False)
        })

    result_json["update_quote_line"] = normalized_updates

    return result_json, tokens_used, cost_est


def generate_final_update_line_items_message(completed_updates, db_results, remaining_updates, previous_summary):
    """
    Generates in ONE LLM call:
    1) A concise, professional, emoji-rich message for the user.
    2) An updated short summary that extends the previous summary with changes from this iteration.
    Returns (message_text, updated_summary, tokens_used, cost_est).
    """

    final_prompt = f"""
    This is an ongoing conversation about quote line update.
    The assistant should return a JSON with two fields only: "message" and "summary".

    Context:
    - User initially wanted to update or create these products: {completed_updates}.
    - Here you have all the backend messages about the quote lines deletion and the quote lines that were attempted to be deleted to the quote: {db_results}.
    - Quote lines still incomplete: {remaining_updates}.
    - Previous summary: {previous_summary}.

    Instructions for "message":
    - Be short, friendly, professional, natural, ask follow-ups, concise but specific and friendly.
    - Mention only which quote lines were successfully updated and which are still pending or incomplete.
    - You don’t need to list each change in detail; instead, describe the updates naturally in the message.
    - For failed quote lines updates, mention the quote line and its error, but only if there are any.
    - For incomplete quote lines updates, briefly mention them ONLY if there are any.
    If none exist, omit this section entirely (do not mention that there are no incomplete lines).
    - Omit entire sections if there are no quote lines in that category.
    - End by asking a short, natural follow-up question about next steps.
    - The message is user-facing and can use <br> for line breaks.
    - If an update fails, explain it as a short, natural comment for the user, not as a system error. Keep it user-friendly and conversational, not technical or formal.
    - Do not include any statement about incomplete quote lines if none exist. For example, do not say things like 'There are currently no incomplete quote lines.' Simply omit that information.
    - When a change has been successfully made, specify the field and the value that were updated in a natural way.
    - Be specific with the fields and values that has been updated for every quote line.

    Instructions for "summary":
    - Write a short but detailed summary that continues the previous summary with the new changes.
    - Summarize successes, failures, and incompletes in 2–4 sentences max.
    - The summary is NOT for the user directly, it's for keeping track of progress across iterations.

    ⚠️ IMPORTANT: Return ONLY valid JSON in this format:
    {{
        "message": "...",
        "summary": "..."
    }}
    """

    messages_for_llm = [
        {"role": "system", "content": "You are a concise and friendly AI assistant for CPQ quote lines updates."},
        {"role": "user", "content": final_prompt}
    ]

    tokens_used, cost_est = estimate_cost(messages_for_llm, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages_for_llm,
        temperature=0.7,
        response_format={"type": "json_object"}  # fuerza JSON válido (si usas GPT-4.1 / GPT-4o / GPT-5)
    )

    raw_output = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT JSON Response Update LineItems: {raw_output}\n\n")

    try:
        parsed = json.loads(raw_output)
        message = parsed.get("message", "").strip()
        updated_summary = parsed.get("summary", "").strip()
    except Exception as e:
        logging.error(f"❌ Error parsing LLM JSON output: {e}")
        message = raw_output
        updated_summary = previous_summary

    if message:
        lowered = message.lower()
        success_triggers = (
            "successfully updated",
            "successfully created",
            "successfully deleted",
            "successfully",
            "success",
            "updated",
            "created",
            "deleted",
        )

        if (
            not message.lstrip().startswith("<span")
            and "not success" not in lowered
            and "not successfully" not in lowered
            and "unsuccess" not in lowered
            and any(trigger in lowered for trigger in success_triggers)
        ):
            message = f"{SUCCESS_ICON} {message.strip()}"

    message = format_message_with_standard_icons(message)

    return message, updated_summary, tokens_used, cost_est


def extract_quote_updates_with_llm(user_message, current_state, previous_summary=None, quote_name=None):
    """Extract multiple product SKUs, quantities, and discounts from user input using GPT."""

    current_date = date.today().isoformat()

    quote = Quote.objects.get(name=quote_name)
    quote_data = model_to_dict(quote)

    print(f"\n\nThis is quote: {quote_data}\n\n")

    system_prompt = """
    You are a helpful AI assistant that modifies a quote and responds in the following format:
    Always return JSON with structure:
    {
        "update_quote": [
            {
                "data": {
                    "quote_name": null,
                    "field": null,
                    "value": null
                },
                "completed": False
            },
        ],
        "agent_message": "string",
        "summary": "string"
    }
    """

    system_prompt += f"""
    The quote you are going to modify is the following:
    Current quote (JSON representation):
    {json.dumps(quote_data, indent=2, default=str)}
    """

    system_prompt += """
    You must use the current quote data as the base state.
    - When the user asks to modify, increase, decrease, extend, or remove something, use the existing values in the current quote to determine the new value.
    - For example:
    - If the user says “increase the discount by 1%”, and the current discount_percentage is 5, the new value must be 6.
    - If the user says “extend the expiration date by one week”, and the current expiration_date is "2025-07-10", then the new value must be "2025-07-17".
    - Apply this rule for ALL fields (numbers, dates, text, etc.).
    - Never ask for information that already exists in the current quote.
    - Assume that the current quote data is accurate and complete.
    """

    system_prompt += """
    Modify only the fields that the user mentions in their message, and for each field they want to change, add a record like this:
    {
        "data": {
            "quote_name": null,
            "field": null,
            "value": null
        },
        "completed": false
    }
    to the list "update_quote".

    Support flexible update actions such as add, remove, delete, multiply, double, divide, among others.

    Requirements:
    - For discounts, if the user specifies a percentage (e.g., "15% discount"), return field: "discount_percentage" and value: 15. If the user specifies a dollar amount (e.g., "$150 off", "150 dollars discount" or just a number like "150"), return field: "discount_amount" and value: 150. Always extract only the numeric value — remove symbols like % or $, and ignore words like "off", "discount", or "dollars".
    - Always normalize discount values to plain numbers.
    - If the user specifies a status value, always normalize it to match one of the following exact formats: "Draft", "Pending Approval", "Approved", "Rejected", or "Closed". Use title casing and ensure the value matches exactly (case-sensitive).
    - If no field are found in the message, return null as field.
    - If no value are found in the message, return null as value.
    - If the user specifies words like remove or delete discount, then set field as "discount_percentage" and value = 0.
    - For expiration dates, always return the value as a string in ISO 8601 format (YYYY-MM-DD), which is compatible with Python and Django. For example, July 30, 2025 → "2025-07-30".
    - For notes, always ensure the returned value ends with a period (.). If the user's note doesn't end with one, automatically add it to the end of the note.
    """
    system_prompt += f"""
    - The current date is {current_date}. Use this as the reference point when interpreting relative dates like "next Friday", "tomorrow", or "in two weeks".
    """

    system_prompt += f"""

    Rules:
    - Treat the JSON as ATTEMPTS to update quote, NOT confirmations.
    - If the user provides the quote name, use that, otherwise use the name of the active quote name: {quote_name}
    - Do NOT include explanations.
    - Do NOT wrap the result in Markdown or use triple backticks.
    - Return only a single JSON object.
    - Required fields: quote_name, field and value.
    - completed=true if quote_name, field and value are present.
    - If quote_name, field and value are provided by the user, mark completed as true.
    - If completed=false, agent_message must politely ask for missing information instead of confirming the addition.
    - NEVER say "quote has been updated" or similar; only acknowledge the user's request or attempt.
    - agent_message should be short, friendly, professionalz, and can ask follow-up questions.
    - This message is a continuation of an ongoing conversation. Do NOT start with greetings like 'Hello' or 'Hi'. Just continue naturally.
    - The message is sensitive to HTML tags, so if you want to make line breaks use the <br> tag.
    - Create a short, detailed summary that extends the previous summary with changes from this iteration.
    - The summary must always explain the current state + why completed is false (if false) OR confirm completeness (if true).

    Agent message:
    - Interpret this as an attempt, therefore do not say things like 'has been successfully updated'.
    - If no quote are mentioned in "Current quote", respond naturally asking the user which fields they want to update. Use language that a regular user would understand, without emphasizing technical or internal terms. It's okay to mention 'quote' if it helps clarity, but keep the message user-friendly.
    - Generate a natural response for the user explaining what happened: updates, errors, missing information, questions for the user, requests for data, etc.
    - Short, professional, natural.
    - Don't be technical.
    - Continue naturally (do NOT start with 'Hello' or 'Hi')
    - Use <br> for line breaks
    - Do not explain if there are no failed or incomplete quotes.
    - If the user requests to modify a field but the value would be the same as the existing one, explain naturally that no changes were applied because the value is already the same.
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

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 FIRST LLM - Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=1
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

    # 🔹 Use the reusable cleaning function
    result_json = clean_llm_json(raw_response)
    if result_json is None:
        logging.error("❌ Failed to clean/parse LLM JSON response.")
        return None, tokens_used, cost_est

    # Normalize structure
    normalized_products = []
    for prod in result_json.get("update_quote", []):
        data = prod.get("data", {})

        quote_name = data.get("quote_name") if data.get("quote_name") is not None else prod.get("quote_name")
        field = data.get("field") if data.get("field") is not None else prod.get("field")
        value = data.get("value") if data.get("value") is not None else prod.get("value")

        # ✅ Marcar como True solo si field y value tienen valores
        completed = field is not None and value is not None

        normalized_products.append({
            "data": {
                "quote_name": quote_name,
                "field": field,
                "value": value
            },
            "completed": completed
        })

    result_json["update_quote"] = normalized_products

    return result_json, tokens_used, cost_est

def generate_final_quote_updates_message(completed_quote_updates, db_results, remaining_quote_updates, previous_summary):
    """
    Generates in ONE LLM call:
    1) A concise, professional, emoji-rich message for the user.
    2) An updated short summary that extends the previous summary with changes from this iteration.
    Returns (message_text, updated_summary, tokens_used, cost_est).
    """

    #successful = [r['product'] for r in db_results if r['status'] == 'success']
    #failed = [(r['product'], r['error']) for r in db_results if r['status'] == 'fail']

    final_prompt = f"""
    This is an ongoing conversation about quote line deletions.
    The assistant should return a JSON with two fields only: "message" and "summary".

    Context:
    - User initially wanted to update this quote: {completed_quote_updates}.
    - Here you have all the backend messages about the quote updates and the quote that were attempted to be updated to the quote: {db_results}.
    - Quote updates still incomplete: {remaining_quote_updates}
    - Previous summary: {previous_summary}.

    Instructions for "message":
    - Be short, friendly, professional, natural, ask follow-ups, concise but specific and friendly.
    - Convert all the messages that appeared when removing the quote updates into a natural, user-friendly message; you can use the exact same message from the backend if you prefer.
    - Always mention the quote name.
    - Do not specify when there are no pending updates; do not respond with messages like: “There are no pending updates.”, "There are no pending updates at this time."
    - Mention only which quote updates were successfully and which are still pending or incomplete.
    - Do NOT include the detailed changes made to each quote update; those details are already captured in the "summary".
    - Do not specify if there are no incomplete quote updates.
    - Do not specify that there are no pending updates.
    - For failed quote updates, mention the quote and its error, but only if there are any.
    - For incomplete quote updated, briefly mention them ONLY if there are any.
    If none exist, omit this section entirely (do not mention that there are no incomplete quote).
    - Omit entire sections if there are no products in that category.
    - End by asking a short, natural follow-up question about next steps.
    - The message is user-facing and can use <br> for line breaks.
    - If an add fails, explain it as a short, natural comment for the user, not as a system error. Keep it user-friendly and conversational, not technical or formal.
    - NEVER start the message with phrases like "Great news!", "Good job!", "Perfect!", or similar interjections.
    - Use this emoji: ✅ to indicate that a quote has been successfully updated.
    Begin directly with the content.

    Instructions for "summary":
    - Write a short but detailed summary that continues the previous summary with the new changes.
    - Summarize successes, failures, and incompletes in 2–4 sentences max.
    - The summary is NOT for the user directly, it's for keeping track of progress across iterations.

    ⚠️ IMPORTANT: Return ONLY valid JSON in this format:
    {{
        "message": "...",
        "summary": "..."
    }}
    """

    messages_for_llm = [
        {"role": "system", "content": (
            "You are a concise, professional AI assistant. "
            "Always write in a natural and neutral tone. "
            "Never start with interjections or phrases like 'Great news!', 'Good job!', 'Awesome!', etc. "
            "Just provide the explanation or follow-up directly."
        )},
        {"role": "user", "content": final_prompt}
    ]

    tokens_used, cost_est = estimate_cost(messages_for_llm, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages_for_llm,
        temperature=0.7,
        response_format={"type": "json_object"}  # fuerza JSON válido (si usas GPT-4.1 / GPT-4o / GPT-5)
    )

    raw_output = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT JSON Response Final Quote Updates: {raw_output}\n\n")

    try:
        parsed = json.loads(raw_output)
        message = parsed.get("message", "").strip()
        updated_summary = parsed.get("summary", "").strip()
    except Exception as e:
        logging.error(f"❌ Error parsing LLM JSON output: {e}")
        message = raw_output
        updated_summary = previous_summary

    if message:
        message_lower = message.lower()
        success_triggers = [
            "successfully updated",
            "successfully created",
            "successfully deleted",
            "successfully",
            "success",
            "updated",
            "created",
            "deleted",
        ]

        if (
            not message.lstrip().startswith("<span")
            and "not success" not in message_lower
            and "not successfully" not in message_lower
            and "unsuccess" not in message_lower
            and any(trigger in message_lower for trigger in success_triggers)
        ):
            message = f"{SUCCESS_ICON} {message.strip()}"

    message = format_message_with_standard_icons(message)

    if message:
        formatted_lower = message.lower()
        if (
            not message.lstrip().startswith("<span")
            and "not success" not in formatted_lower
            and "not successfully" not in formatted_lower
            and "unsuccess" not in formatted_lower
            and any(trigger in formatted_lower for trigger in (
                "successfully updated",
                "successfully created",
                "successfully deleted",
                "successfully",
                "success",
                "updated",
                "created",
                "deleted",
            ))
        ):
            message = f"{SUCCESS_ICON} {message.strip()}"

    return message, updated_summary, tokens_used, cost_est

def extract_quote_line_to_delete_with_llm(user_message, current_state, previous_summary=None):
    """Extract multiple product SKUs, quantities, and discounts from user input using GPT."""

    system_prompt = """
    You are a helpful AI assistant that extracts quote lines data from user messages.
    Always return JSON with structure:
    {
        "delete_quote_line": [
            {
                "data": {
                    "sku": null,
                    "name": null
                },
                "completed": False
            },
        ],
        "agent_message": "string",
        "summary": "string"
    }

    Rules:
    - Treat the JSON as ATTEMPTS to delete quote lines, NOT confirmations.
    - If no SKU is found in the message, return: {{"sku": null}}
    - If no name is found in the message, return: {{"name": null}}
    - Do NOT include explanations.
    - Do NOT wrap the result in Markdown or use triple backticks.
    - Return only a single JSON object.
    - Required fields: sku or name.
    - completed=true if sku or name is present.
    - If name is provided by the user, mark completed as true.
    - If sku is provided by the user, mark completed as true.
    - If the user provides multiple skus or names, add different entries in "delete_quote_line."
    - Do NOT ask for both SKU and Name if one of them is already present.
    - If sku or name is not provided, set completed to false and ask the user if they can provide either of those information.
    - If completed=false, agent_message must politely ask for missing information instead of confirming the addition.
    - NEVER say "quote line has been deleted" or similar; only acknowledge the user's request or attempt.
    - agent_message should be short, friendly, professionalz, and can ask follow-up questions.
    - This message is a continuation of an ongoing conversation. Do NOT start with greetings like 'Hello' or 'Hi'. Just continue naturally.
    - The message is sensitive to HTML tags, so if you want to make line breaks use the <br> tag.
    - Create a short, detailed summary that extends the previous summary with changes from this iteration.
    - The summary must always explain the current state + why completed is false (if false) OR confirm completeness (if true).
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

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 FIRST LLM - Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=1
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

    # 🔹 Use the reusable cleaning function
    result_json = clean_llm_json(raw_response)
    if result_json is None:
        logging.error("❌ Failed to clean/parse LLM JSON response.")
        return None, tokens_used, cost_est

    # Normalize structure
    normalized_products = []
    for prod in result_json.get("delete_quote_line", []):
        normalized_products.append({
            "data": {
                "sku": prod.get("data", {}).get("sku") or prod.get("sku"),
                "name": prod.get("data", {}).get("name") or prod.get("name")
            },
            "completed": prod.get("data", {}).get("completed", prod.get("completed", False))
        })
    result_json["delete_quote_line"] = normalized_products

    return result_json, tokens_used, cost_est



def generate_final_delete_quote_lines_message(completed_quote_lines, db_results, remaining_quote_lines, previous_summary):
    """
    Generates in ONE LLM call:
    1) A concise, professional, emoji-rich message for the user.
    2) An updated short summary that extends the previous summary with changes from this iteration.
    Returns (message_text, updated_summary, tokens_used, cost_est).
    """

    #successful = [r['product'] for r in db_results if r['status'] == 'success']
    #failed = [(r['product'], r['error']) for r in db_results if r['status'] == 'fail']

    final_prompt = f"""
    This is an ongoing conversation about quote line deletions.
    The assistant should return a JSON with two fields only: "message" and "summary".

    Context:
    - User initially wanted to delete this quote lines: {completed_quote_lines}.
    - Here you have all the backend messages about the quote lines deletion and the quote lines that were attempted to be deleted to the quote: {db_results}.
    - Quote lines still incomplete: {remaining_quote_lines}
    - Previous summary: {previous_summary}.

    Instructions for "message":
    - Be short, friendly, professional, natural, ask follow-ups, concise but specific and friendly.
    - Convert all the messages that appeared when removing the quote lines into a natural, user-friendly message; you can use the exact same message from the backend if you prefer.
    - Always mention the quote line name or sku.
    - Use symple emojis.
    - Mention only which quote lines were successfully deleted and which are still pending or incomplete.
    - Do NOT include the detailed changes made to each quote line; those details are already captured in the "summary".
    - Do not specify if there are no incomplete quote lines.
    - For failed quote lines deleted, mention the quote line and its error, but only if there are any.
    - For incomplete quote lines, briefly mention them ONLY if there are any.
    If none exist, omit this section entirely (do not mention that there are no incomplete quote lines).
    - Omit entire sections if there are no products in that category.
    - End by asking a short, natural follow-up question about next steps.
    - The message is user-facing and can use <br> for line breaks.
    - If an add fails, explain it as a short, natural comment for the user, not as a system error. Keep it user-friendly and conversational, not technical or formal.
    - NEVER start the message with phrases like "Great news!", "Good job!", "Perfect!", or similar interjections.
    - Use this emoji: ✅ to indicate that a quote line has been successfully deleted.
    Begin directly with the content.

    Instructions for "summary":
    - Write a short but detailed summary that continues the previous summary with the new changes.
    - Summarize successes, failures, and incompletes in 2–4 sentences max.
    - The summary is NOT for the user directly, it's for keeping track of progress across iterations.

    ⚠️ IMPORTANT: Return ONLY valid JSON in this format:
    {{
        "message": "...",
        "summary": "..."
    }}
    """

    messages_for_llm = [
        {"role": "system", "content": (
            "You are a concise, professional AI assistant. "
            "Always write in a natural and neutral tone. "
            "Never start with interjections or phrases like 'Great news!', 'Good job!', 'Awesome!', etc. "
            "Just provide the explanation or follow-up directly."
        )},
        {"role": "user", "content": final_prompt}
    ]

    tokens_used, cost_est = estimate_cost(messages_for_llm, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages_for_llm,
        temperature=0.7,
        response_format={"type": "json_object"}  # fuerza JSON válido (si usas GPT-4.1 / GPT-4o / GPT-5)
    )

    raw_output = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT JSON Response: {raw_output}\n\n")

    try:
        parsed = json.loads(raw_output)
        message = parsed.get("message", "").strip()
        updated_summary = parsed.get("summary", "").strip()
    except Exception as e:
        logging.error(f"❌ Error parsing LLM JSON output: {e}")
        message = raw_output
        updated_summary = previous_summary

    return message, updated_summary, tokens_used, cost_est
