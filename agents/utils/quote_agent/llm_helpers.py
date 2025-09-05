import json
import os
import openai
import logging
from dotenv import load_dotenv
from datetime import date

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"
# OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

from ..orchestrator.context_handle_helpers import estimate_cost

# FUNCTION TO EXTRACT QUOTE DETAILS (CREATE_QUOTE)
def extract_quote_details(user_message):
    """Use GPT to extract details for quote creation."""
    prompt = f"""
    **IMPORTANT FOR CONVERSATION CONTEXT:**
    If the user message is accompanied by previously extracted data entries , you must:
    - Use that data to preserve the context of each item, assuming the user is continuing an incomplete task.
    - Only update the items the user refers, and retain the others as incomplete.
    - Return a list of all items (updated and pending) with the following structure.
    However, if there is no prior extracted data provided, treat the message as a new standalone instruction, with no memory of previous items or context.
    **--FINAL CONVERSATION CONTEXT--**
    
    Extract the following details from the user's request for quote creation:
    - Account Name
    - Opportunity Name (if applicable)
    - Products
    - Discounts (if mentioned)
    - Subscription Start/End Dates (if applicable)
    - Term (if mentioned)

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

    Return a JSON object with these keys:
    {{"account": "", "opportunity": "", "products": [{{"sku": "", "name": "", "quantity": 1, "discount_type": "", "discount_value": "", "term": Null}}], "start_date": "", "end_date": ""}}.

    If no products are provided in the request, return a JSON object with these keys:
    {{"account": "", "opportunity": "", "products": [], "start_date": "", "end_date": ""}}.

    User Request: "{user_message}"
    """
    
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "system", "content": "Extract structured data from the user request."},
                  {"role": "user", "content": prompt}]
    )
    
    try:
        extracted_data = json.loads(response.choices[0].message.content)
        return extracted_data
    except json.JSONDecodeError:
        return None

    

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
    - "value" (number, requited)

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
    
# FUNCTION TO EXTRACT QUOTE UPDATES (UPDATE_QUOTE)    
def extract_quote_updates(user_message):
    """Uses GPT to extract quote name, field, and new value for quote updates."""

    current_date = date.today().isoformat()

    print(f"Current Date: {current_date}")

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
    - "quote_name" (string, required)
    - "field"
    - "value" (number, string or date)

    **Example Input & Output:**
    User: "Set the status of quote Q-00023 to approved, then change the status of Q-00047 to "Pending Approval" also mark quote as rejected."
    Response:
    [
        {{"quote_name": "Q-00023", "field": "status", "value": "Approved"}},
        {{"quote_name": "Q-00047", "field": "status", "value": "Pending Approval"}},
        {{"quote_name": null, "field": "status", "value": "Rejected"}}
    ]

    **Example Input & Output:**
    User: "Apply a 10% discount to quote and set the discount of Q-00056 to 150"
    Response:
    [
        {{"quote_name": null, "field": "discount_percentage", "value": 10}},
        {{"quote_name": "Q-00056", "field": "discount_amount", "value": 150}}
    ]

    **Example Input & Output:**
    User: "Extend the expiration date of quote to July 30, 2025."
    Response:
    [
        {{"quote_name": null, "field": "expiration_date", "value": "2025-07-30"}}
    ]

    **Example Input & Output:**
    User: "Add the note "Urgent request from client" to quote Q-00048."
    Response:
    [
        {{"quote_name": "Q-00048", "field": "notes", "value": "Urgent request from client."}}
    ]

    **Example Input & Output:**
    User: "update tax to 7% to quote Q-00076"
    Response:
    [
        {{"quote_name": "Q-00076", "field": "tax_percentage", "value": 7.00}}
    ]

    **Requirements:**
    - For discounts, if the user specifies a percentage (e.g., "15% discount"), return field: "discount_percentage" and value: 15. If the user specifies a dollar amount (e.g., "$150 off", "150 dollars discount" or just a number like "150"), return field: "discount_amount" and value: 150. Always extract only the numeric value — remove symbols like % or $, and ignore words like "off", "discount", or "dollars".
    - Always normalize discount values to plain numbers.
    - If the user specifies a status value, always normalize it to match one of the following exact formats: "Draft", "Pending Approval", "Approved", "Rejected", or "Closed". Use title casing and ensure the value matches exactly (case-sensitive).
    - If no quote name are found in the message, return null as quote_name
    - If no field are found in the message, return null as field
    - If no value are found in the message, return null as value
    - For expiration dates, always return the value as a string in ISO 8601 format (YYYY-MM-DD), which is compatible with Python and Django. For example, July 30, 2025 → "2025-07-30".
    - For notes, always ensure the returned value ends with a period (.). If the user’s note doesn’t end with one, automatically add it to the end of the note.
    - The current date is {current_date}. Use this as the reference point when interpreting relative dates like "next Friday", "tomorrow", or "in two weeks".

    **IMPORTANT:** **Return a valid JSON array only of product objects. DO NOT include explanations, and DO NOT format the response as Markdown (NO triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured updates details for quote."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_updates = json.loads(raw_response)
            if isinstance(extracted_updates, list) and all("quote_name" in p and "field" in p and "value" in p for p in extracted_updates):
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

# FUNCTION TO EXTRACT QUOTE LEVEL DISCOUNT (APPLY_DISCOUNT_TO_QUOTE)  
def extract_quote_level_discount(user_message):
    """Extract discount for quote level discount."""

    prompt = f"""
    Extract only the discount amount from the user's request, which can be expressed either as a percentage (%) or a dollar value (USD or $).

    **Expected discount fields:**
    - discount (integer or float): The numeric value of the discount specified by the user (e.g., 10 for "10%" or 50 for "$50").
    - discount_type (string): Indicates the type of discount. ("percentage"  if the user specified the discount as a percentage (e.g., "10%"). "amount"  if the user specified the discount in dollars (e.g., "$50", "USD 50"). "None" if the type cannot be determined.)

    [If no discount is found in the message, return None]
    [If no discount_type is found in the message, return None]

    **Example Input:**
    "Apply a 5% discount to the quote."

    **Expected JSON Output:**
    [
        {{"discount": "5", "discount_type": "percentage"}}
    ]

    **Example Input:**
    "Apply a $40 discount."

    **Expected JSON Output:**
    [
        {{"discount": "40", "discount_type": "amount"}}
    ]

    **Example Input:**
    "Update a 15% off to this quote."

    **Expected JSON Output:**
    [
        {{"discount": "15", "discount_type": "percentage"}}
    ]

    **Example Input with no discount:**
    "Apply a discount to quote."
    
    **Expected JSON Output:**
    [
        {{"discount": "None", "discount_type": "amount"}}
    ]

    **Example Input with no discount type:**
    "Apply a 30 discount to the quote."

    **Expected JSON Output:**
    [
        {{"discount": "30", "discount_type": "None"}}
    ]


    **User Request:** "{user_message}"

    **Return a valid JSON array only of discount objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured discount details applied at the quote level (not per product line)."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_discounts = json.loads(raw_response)
            if isinstance(extracted_discounts, list) and all("discount" in p and "discount_type" in p for p in extracted_discounts):
                return extracted_discounts
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting discount quote details: {str(e)}")
        return None
    

# NUEVOS LLM HELPERS, EVENTUALMENTE BORRAR LOS DE ARRIBA

def extract_quote_line_updates_with_llm(user_message, current_state, previous_summary=None, line_items_on_user_message=None):
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
            }
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

    successful = [r['product'] for r in db_results if r['status'] == 'success']
    failed = [(r['product'], r['error']) for r in db_results if r['status'] == 'fail']

    final_prompt = f"""
    This is an ongoing conversation about quote line update. 
    The assistant should return a JSON with two fields only: "message" and "summary".

    Context:
    - User initially wanted to update or create these products: {completed_updates}.
    - Quote lines successfully saved: {successful}.
    - Quote lines failed to save (with errors): {failed}.
    - Quote lines still incomplete: {remaining_updates}.
    - Previous summary: {previous_summary}.

    Instructions for "message":
    - Be short, friendly, professional, natural, ask follow-ups, concise but specific and friendly.
    - Mention only which quote lines were successfully updated and which are still pending or incomplete.
    - Do NOT include the detailed changes made to each line item; those details are already captured in the "summary".
    - For failed quote lines updates, mention the quote line and its error, but only if there are any.
    - For incomplete quote lines updates, briefly mention them ONLY if there are any. 
    If none exist, omit this section entirely (do not mention that there are no incomplete lines).
    - Omit entire sections if there are no quote lines in that category.
    - End by asking a short, natural follow-up question about next steps.
    - The message is user-facing and can use <br> for line breaks.
    - If an update fails, explain it as a short, natural comment for the user, not as a system error. Keep it user-friendly and conversational, not technical or formal.

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

def generate_final_add_product_to_quote_message2(completed_products, db_results, remaining_products, previous_summary):
    """
    Generates in ONE LLM call:
    1) A concise, professional, emoji-rich message for the user.
    2) An updated short summary that extends the previous summary with changes from this iteration.
    Returns (message_text, updated_summary, tokens_used, cost_est).
    """

    successful = [r['product'] for r in db_results if r['status'] == 'success']
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
    - For incomplete products, briefly mention them ONLY if there are any. 
    If none exist, omit this section entirely (do not mention that there are no incomplete products).
    - Omit entire sections if there are no products in that category.
    - End by asking a short, natural follow-up question about next steps.
    - The message is user-facing and can use <br> for line breaks.
    - If an add fails, explain it as a short, natural comment for the user, not as a system error. Keep it user-friendly and conversational, not technical or formal.

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
        {"role": "system", "content": "You are a concise and friendly AI assistant for CPQ products to add."},
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