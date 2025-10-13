import json
import re
import os
import openai
import logging
from dotenv import load_dotenv
from datetime import date

# System Prompt Helpers
from ..prompts_helpers.system_prompt_helpers import make_system_prompt

# Models
from cpq.models import Opportunity

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"
# OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

from ..orchestrator.context_handle_helpers import estimate_cost



# ------ FUNCTION TO EXTRACT QUOTE DETAILS (CREATE_QUOTE) ------
def extract_quote_details_with_llm(user_message, current_state, previous_summary=None):
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

    # 🧹 Limpieza de bloques Markdown (```json ... ```)
    if raw_response.startswith("```"):
        raw_response = re.sub(r"^```(json)?", "", raw_response.strip())
        raw_response = re.sub(r"```$", "", raw_response.strip())
        raw_response = raw_response.strip()

    # 🪶 Mostrar la respuesta después de limpiar
    #logging.info(f"\n🧼 Cleaned JSON Response (ready for parsing):\n{raw_response}\n")

    try:
        result_json = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
        logging.error(f"🪶 Raw response that failed to decode:\n{raw_response}")
        return None

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



def generate_final_create_quote_message(quote, db_results, previous_summary, products = None):
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
    - Use this emoji: ✅ to indicate that a quote has been successfully created.
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









# FUNCTION TO EXTRACT QUOTE LINE UPDATES (UPDATE_QUOTE_LINE)
def extract_quote_line_updates(user_message):
    """Uses GPT to extract SKU, field, and new value for quote line updates."""

    allowed_fields_str = '", "'.join(["quantity", "discount_amount", "discount_percentage", "term"])

    prompt = f"""
    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**

    Extract structured update details from the following request.
    Return a JSON array with objects containing:
    - "sku" (string, required)
    - "name" (string, required)
    - "field" (one of: "{allowed_fields_str}", if user specifies any other field, set field as that field)
    - "value" (number, required)

    **Example Input & Output:**
    User: "Update AI-10 quantity to 600 and discount to 5%, then update AgentCPQ3 discount to $100."
    Response:
    [
        {{"sku": "AI-10", "name": null, "field": "quantity", "value": 600}},
        {{"sku": null, "name": "AgentCPQ3", "field": "discount_amount", "value": 100}}
    ]

    **Requirements:**
    - For discounts, if the user specifies a percentage (e.g., "15% discount"), return field: "discount_percentage" and value: 15. If the user specifies a dollar amount (e.g., "$150 off" or "150 dollars discount"), return field: "discount_amount" and value: 150. Always extract only the numeric value — remove symbols like % or $, and ignore words like "off", "discount", or "dollars".
    - Always normalize discount values to plain numbers.
    - If no SKUs are found in the message, return null as SKU
    - If no name are found in the message, return null as Name
    - If no field are found in the message, return null as field
    - If no value are found in the message, return null as value
    - If no discount are found in the message, return null as value

    **Example Input with no SKU:**
    "modify the product quantity to 200 and price to 10"

    **Expected JSON Output:**
    [
        {{"sku": null, "name": null, "field": "quantity", "value": 49.99}}
    ]

    **Example Input with no field:**
    "update AI-10 to 200"

    **Expected JSON Output:**
    [
        {{"sku": "AI-10", "name": null, "field": null, "value": 200}}
    ]

    **Example Input with no value:**
    "Update AI-20 quantity"

    **Expected JSON Output:**
    [
        {{"sku": "AI-20", "name": null, "field": "quantity", "value": null}}
    ]

    **IMPORTANT:** **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured updates details for quote line."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all("sku" in p and "name" in p and "field" in p and "value" in p for p in extracted_updates):
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





def extract_quote_updates_with_llm(user_message, current_state, previous_summary=None, quote_name=None):
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

    current_date = date.today().isoformat()

    system_prompt = """
    You are a helpful AI assistant that extracts quote updates data from user messages.
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

    try:
        result_json = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
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









# NUEVOS LLM HELPERS, EVENTUALMENTE BORRAR LOS DE ARRIBA

def extract_quote_line_updates_with_llm(user_message, current_state, previous_summary=None, line_items_on_user_message=None):
    """
    Uses LLM to extract structured quote line updates from user input.
    Returns JSON, tokens used, and estimated cost.
    """

    allowed_fields_str = '", "'.join(["quantity", "discount_amount", "discount_percentage", "term"])

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

    try:
        result_json = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
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

def extract_quote_line_updates_with_llm2(user_message, current_state, previous_summary=None, line_items_on_user_message=None):
    """
    Uses LLM to extract structured quote line updates from user input.
    Returns JSON, tokens used, and estimated cost.
    """

    system_prompt = """
    You are a helpful AI assistant that updates quote line items from user messages.
    Always return JSON with structure:
    {
    "update_quote_line": [
        {
        "data": {
            "sku": null,
            "name": null,
            "fields": {
                "quantity": null,
                "discount_type": null,
                "discount_percentage": null,
                "discount_amount": null,
                "term": null,
                "unit_price": null
            },
            "value":
        },
        "completed": false
        }
    ],
    "agent_message": "string",
    "summary": "string"
    }

    Rules:
    1. I will provide you with a list of dictionaries containing the line items mentioned by the user in their message under "Current line items mentioned." Your task is to modify only the fields the user specifies with the values they provide.

    2. If the user attempts to modify a line item that is not found in "Current line items mentioned," indicate in the agent_message that the product is not in the quote.

    3. Only modify the fields that the user mentions, do not change the rest.

    4. If the user attempts to do anything other than update a line item, do not modify any data and indicate in the agent_message that this agent can only update a line item/quote_lines.

    5. If the user's intention is to delete the value of a field, set that value to 0.

    6. If the user wants to remove the discount from a line item, set discount_percentage to 0, discount_amount to 0, and discount_type to "percentage."

    7. If the user adds a discount to the line item as a percentage, calculate the discount_amount based on the provided unit_price for that line item. Conversely, if the user wants to apply a discount amount, then calculate the discount_percentage based on the unit_price.

    8. If the user updates any discount in percentage, set discount_type to "percentage." If they update any discount in amount, set discount_type to "amount."

    9. Fields quantity, discount_percentage, and discount_amount must not return as null.

    10. Mark "completed" as true if a line item receives an update, provided it is within the following parameters:
    - quantity: integer >= 0
    - term: integer between 1 and 12
    - discount_percentage: between 0 and 100
    - discount_amount: >= 0 and <= unit_price (if unit_price is provided)
    - If unit_price is provided:
    - discount_percentage → discount_amount = (discount_percentage / 100) * unit_price
    - discount_amount → discount_percentage = (discount_amount / unit_price) * 100
    - If unit_price is NOT provided, just set the discount as given by the user.

    11. Support flexible update actions: add, remove, delete, multiply, duplicate, divide, among others.

    12. The only fields can be updated are: quantity, discount_type, discount_amount, discount_percentage and term.
    - Do not mention or claim updates on any other fields.

    - Only update the fields explicitly mentioned by the user.
    - Do not assume or fill in fields that the user did not specify.
    - Do not include unchanged information in the agent_message.
    - Only include line items in "update_quote_line" if at least one field is actually modified. Do not include line items where no changes were applied.
    - If a line item has no changes, do not include it in update_quote_line


    Agent message:
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

    try:
        result_json = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
        return None, tokens_used, cost_est

    # Normalize structure
    normalized_updates = []
    for item in result_json.get("update_quote_line", []):
        normalized_updates.append({
            "data": {
                "sku": item.get("data", {}).get("sku") or item.get("sku"),
                "name": item.get("data", {}).get("name") or item.get("name"),
                "fields": {
                    "quantity": item.get("data", {}).get("fields", {}).get("quantity"),
                    "discount_percentage": item.get("data", {}).get("fields", {}).get("discount_percentage"),
                    "discount_amount": item.get("data", {}).get("fields", {}).get("discount_amount"),
                    "term": item.get("data", {}).get("fields", {}).get("term"),
                    "unit_price": item.get("data", {}).get("fields", {}).get("unit_price"),
                }
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


# FUNCTION TO EXTRACT PRODUCT DETAILS (ADD_PRODUCT_TO_QUOTE)
def extract_products_to_add_with_llm(user_message, current_state, previous_summary=None):
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
    You are a helpful AI assistant that extracts product data from user messages.
    Always return JSON with structure:
    {
        "add_product_to_quote": [
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

    try:
        result_json = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
        return None, tokens_used, cost_est

    # Normalize structure
    normalized_products = []
    for prod in result_json.get("add_product_to_quote", []):
        normalized_products.append({
            "data": {
                "sku": prod.get("data", {}).get("sku") or prod.get("sku"),
                "name": prod.get("data", {}).get("name") or prod.get("name"),
                "quantity": prod.get("data", {}).get("quantity") or prod.get("quantity"),
                "discount_type": prod.get("data", {}).get("discount_type"),
                "discount_value": prod.get("data", {}).get("discount_value"),
                "term": prod.get("data", {}).get("term")
            },
            "completed": prod.get("data", {}).get("completed", prod.get("completed", False))
        })
    result_json["create_product"] = normalized_products

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
