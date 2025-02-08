import json
import os
from dotenv import load_dotenv
import openai
from cpq.models import Quote, Account, Opportunity, QuoteLine, Product
from decimal import Decimal
import logging

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4"

# ✅ OpenAI Client
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# def extract_quote_details(user_message):
#     """Use GPT to extract details for quote creation."""
#     prompt = f"""
#     Extract the following details from the user's request for quote creation:
#     - Account Name (Required)
#     - Opportunity Name (If applicable)
#     - Products and Quantities (Required)
#     - Discounts (If mentioned)
#     - Subscription Start/End Dates (If applicable)

#     If the opportunity is not provided, return an empty string.

#     Return a JSON object with these keys:
#     {{
#         "account": "",
#         "opportunity": "",
#         "products": [{{"sku": "", "quantity": 1}}],
#         "discount": 0,
#         "start_date": "",
#         "end_date": ""
#     }}.

#     User Request: "{user_message}"
#     """

#     response = client.chat.completions.create(
#         model=OPENAI_MODEL,
#         messages=[{"role": "system", "content": "Extract structured data from the user request."},
#                   {"role": "user", "content": prompt}]
#     )

#     try:
#         extracted_data = json.loads(response.choices[0].message.content)
#         return extracted_data
#     except json.JSONDecodeError:
#         return None

# def create_quote_agent(user_message, session_data):
#     """Handles quote creation while preserving context."""
    
#     extracted_details = extract_quote_details(user_message)
#     if not extracted_details:
#         return {"message": "⚠️ Error: Could not extract quote details. Please specify account, products, and quantity."}

#     account_name = extracted_details.get("account")
#     opportunity_name = extracted_details.get("opportunity", "")
    
#     # Ensure opportunity is provided before creating the quote
#     if not opportunity_name:
#         session_data["pending_action"] = "confirm_opportunity"
#         session_data["account"] = account_name  # Save account for later reference
#         return {"message": f"📝 Please provide an opportunity name for {account_name} before creating the quote."}

#     # ✅ Check if Account exists or create it
#     account, _ = Account.objects.get_or_create(name=account_name)

#     # ✅ Check if Opportunity exists or create it
#     opportunity, _ = Opportunity.objects.get_or_create(name=opportunity_name, account=account)

#     # ✅ Create Quote
#     quote = Quote.objects.create(
#         account=account,
#         opportunity=opportunity,
#         status="Draft",
#         net_amount=0
#     )

#     # ✅ Store quote context in session
#     session_data["active_quote"] = {
#         "quote_id": quote.id,
#         "account": account_name,
#         "opportunity": opportunity_name
#     }
#     session_data["pending_action"] = "add_product"

#     return {
#         "message": f"✅ Quote created for {account_name} under opportunity {opportunity_name}. Would you like to add products now?",
#         "quote_id": quote.id
#     }


# def add_product_to_quote(user_message, session_data):
#     """Handles adding a product to an existing quote."""
#     extracted_details = extract_product_details(user_message)
#     if not extracted_details:
#         return "⚠️ Error: Could not extract product details. Please specify a product SKU and quantity."

#     sku = extracted_details.get("sku")
#     quantity = extracted_details.get("quantity", 1)

#     # ✅ Ensure there's an active quote in session
#     quote_id = session_data.get("quote_id")
#     if not quote_id:
#         return "⚠️ No active quote found. Please create a quote first."

#     # ✅ Retrieve Quote
#     try:
#         quote = Quote.objects.get(id=quote_id)
#     except Quote.DoesNotExist:
#         return "⚠️ The referenced quote does not exist."

#     # ✅ Retrieve Product
#     try:
#         product = Product.objects.get(sku=sku)
#     except Product.DoesNotExist:
#         return f"⚠️ Product with SKU {sku} not found. Please verify."

#     # ✅ Create Quote Line
#     unit_price = product.price
#     total_price = unit_price * quantity

#     QuoteLine.objects.create(
#         quote=quote,
#         product=product,
#         quantity=quantity,
#         unit_price=unit_price,
#         total_price=total_price
#     )

#     # ✅ Update Quote Net Amount
#     quote.net_amount += total_price
#     quote.save()

#     return {
#         "message": f"✅ Added {quantity}x {product.name} to the quote. Would you like to add more products or apply discounts?",
#         "quote_id": quote.id
#     }

def extract_product_details(user_message):
    """Extract product SKU and quantity from user input using GPT."""
    prompt = f"""
    Extract the following details from the user's request:
    - Product SKU
    - Quantity

    Return a JSON object with:
    {{"sku": "", "quantity": 1}}

    User Request: "{user_message}"
    """

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "system", "content": "Extract structured data for product addition."},
                  {"role": "user", "content": prompt}]
    )

    try:
        extracted_data = json.loads(response.choices[0].message.content)
        return extracted_data
    except json.JSONDecodeError:
        return None

def extract_quote_details(user_message):
    """Use GPT to extract details for quote creation."""
    prompt = f"""
    Extract the following details from the user's request for quote creation:
    - Account Name
    - Opportunity Name (if applicable)
    - Products and Quantities
    - Discounts (if mentioned)
    - Subscription Start/End Dates (if applicable)
    
    Return a JSON object with these keys:
    {{"account": "", "opportunity": "", "products": [{{"sku": "", "quantity": 1, "discount": 0}}], "start_date": "", "end_date": ""}}.
    
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

def create_quote_agent(user_message, session_data):
    """Handles quote creation while preserving context."""

    extracted_details = extract_quote_details(user_message)
    if not extracted_details:
        return {"message": "⚠️ Error: Could not extract quote details. Please specify account, products, and quantity."}

    account_name = extracted_details.get("account", "").strip()
    opportunity_name = extracted_details.get("opportunity", "").strip()

    # ✅ Ensure opportunity is provided before proceeding
    if session_data.get("pending_action") == "confirm_opportunity":
        if opportunity_name:
            session_data["opportunity"] = opportunity_name
            session_data["pending_action"] = "add_product"  # ✅ Update the flow to expect product addition next
            return {"message": f"✅ Opportunity `{opportunity_name}` added. Would you like to add products now?"}
        else:
            return {"message": "📝 Please provide an opportunity name before creating the quote."}

    # ✅ Check if Account exists or create it
    account, _ = Account.objects.get_or_create(name=account_name)

    # ✅ Check if Opportunity exists or create it
    opportunity, _ = Opportunity.objects.get_or_create(name=session_data.get("opportunity", opportunity_name), account=account)

    # ✅ Create Quote
    quote = Quote.objects.create(
        account=account,
        opportunity=opportunity,
        status="Draft",
        net_amount=0
    )

    # ✅ Store quote context in session & clear pending actions
    session_data["active_quote"] = {
        "quote_id": quote.id,
        "account": account_name,
        "opportunity": opportunity_name
    }
    session_data["pending_action"] = "add_product"  # ✅ Ensure we move to the next step

    return {
        "message": f"✅ Quote created for {account_name} under opportunity {opportunity_name}. Would you like to add products now?",
        "quote_id": quote.id
    }



def add_product_to_quote(user_message, session_data):
    """Handles adding products to an existing quote."""
    logging.info("🔄 Adding product to existing quote...")

    # ✅ Ensure we have an active quote
    active_quote = session_data.get("active_quote")
    if not active_quote:
        return {"message": "⚠️ No active quote found. Please create a quote first."}

    quote_id = active_quote.get("quote_id")

    # ✅ Extract product details
    extracted_product = extract_product_details(user_message)
    if not extracted_product:
        return {"message": "⚠️ Error: Could not extract product details. Please specify SKU and quantity."}

    sku = extracted_product.get("sku")
    quantity = extracted_product.get("quantity", 1)
    discount = extracted_product.get("discount", 0)

    # ✅ Fetch product from DB
    try:
        product = Product.objects.get(sku=sku)
    except Product.DoesNotExist:
        return {"message": f"⚠️ Product {sku} not found. Please ensure it exists in the catalog."}

    # ✅ Convert values to Decimal
    unit_price = Decimal(product.price)  # Ensure unit price is Decimal
    discount_multiplier = Decimal((100 - discount) / 100)  # Convert discount to Decimal

    # ✅ Create Quote Line Item
    quote = Quote.objects.get(id=quote_id)
    QuoteLine.objects.create(
        quote=quote,
        product=product,
        quantity=quantity,
        unit_price=unit_price,
        total_price=(unit_price * Decimal(quantity)) * discount_multiplier  # ✅ Ensure all values are Decimal
    )

    # ✅ Update session state
    session_data["pending_action"] = None  # Reset action
    return {
        "message": f"✅ Added {quantity}x {sku} to quote {quote_id}. Would you like to add more products or apply a discount?"
    }