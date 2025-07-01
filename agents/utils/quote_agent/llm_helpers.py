import json
import os
import openai
import logging
from dotenv import load_dotenv

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"
# OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

# FUNCTION TO EXTRACT QUOTE DETAILS (CREATE_QUOTE)
def extract_quote_details(user_message):
    """Use GPT to extract details for quote creation."""
    prompt = f"""
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


# FUNCTION TO EXTRACT PRODUCT DETAILS (ADD_PRODUCT_TO_QUOTE)  
def extract_product_details(user_message):
    """Extract multiple product SKUs, quantities, and discounts from user input using GPT."""
    prompt = f"""
    Extract all product details from the user's request. The user may specify multiple products in a single message.

    **Expected fields per product:**
    - sku (string, unique identifier)
    - name (string, product name)
    - quantity (integer, default 1 if not specified)
    - discount_type ("percentage" or "amount", based on how the user specifies the discount)
    - discount_value (integer, default 0 if not specified)
    - term (integer, default 0 if not specified)(term is for subscription)

    **Instructions for discounts:**
    - Use `"percentage"` for `discount_type` if the user specifies a percentage (e.g., "15%", "15 percent").
    - Use `"amount"` for `discount_type` if the user specifies a fixed amount (e.g., "$15", "15 dollars", "15 USD").
    - Extract the numeric part and set it as `discount_value` (e.g., "15%" → 15, "$15" → 15).
    - If no discount is mentioned, set `"discount_type": "None"` and `"discount_value": "0"`.

    **Example Input:** 
    "Add AI-CPQ-001 x 5 with 10% discount, Agency PQ Solo x 2 with $20 discount, and AI-CPQ-004 x 10."

    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-001", "name": "Null", "quantity": 5, "discount_type": "percentage", "discount_value": 10, "term": null}},
        {{"sku": "Null", "name": "Agency PQ Solo", "quantity": 2, "discount_type": "amount", "discount_value": 20, "term": null}},
        {{"sku": "AI-CPQ-004", "name": "Null", "quantity": 1, "discount_type": "None", "discount_value": 0, "term": null}}
    ]

    **User Request:** "{user_message}"

    **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json) — just return the JSON.**
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured product details for quote addition."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"🔍 Raw GPT Response: {raw_response}")

        # ✅ Ensure valid JSON response
        try:
            extracted_products = json.loads(raw_response)
            if isinstance(extracted_products, list) and all("sku" in p and "name" in p and "quantity" in p and "discount_type" in p and "discount_value" in p and "term" in p for p in extracted_products):
                return extracted_products
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting product details: {str(e)}")
        return None
    

# FUNCTION TO EXTRACT QUOTE LINE UPDATES (UPDATE_QUOTE_LINE)    
def extract_quote_line_updates(user_message):
    """Uses GPT to extract SKU, field, and new value for quote line updates."""

    allowed_fields_str = '", "'.join(["quantity", "discount_amount", "discount_percentage", "term"])

    prompt = f"""
    Extract structured update details from the following request.
    Return a JSON array with objects containing:
    - "sku" (string, required)
    - "name" (string, required)
    - "field" (one of: "{allowed_fields_str}")
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