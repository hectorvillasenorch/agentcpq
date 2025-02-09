from django.db.models import Sum, F
import json, os, openai, logging, re
from dotenv import load_dotenv
from cpq.models import Quote, Account, Opportunity, QuoteLine, Product
from decimal import Decimal

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4"

# ✅ OpenAI Client
client = openai.OpenAI(api_key=OPENAI_API_KEY)


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


def quote_agent(action, user_message, session_data):
    """Handles all quote-related actions dynamically."""

    # ✅ Action-to-function mapping
    action_map = {
        "CreateQuote": create_quote,
        "ShowQuoteDetails": show_quote_details,
        "AddProduct": add_product_to_quote,
        # "ApplyDiscount": apply_discount,
        # "ProvideDates": provide_dates,
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request."}

# def create_quote(user_message, session_data):
#     """Handles quote creation while preserving context."""

#     extracted_details = extract_quote_details(user_message)
#     if not extracted_details:
#         return {"message": "⚠️ Error: Could not extract quote details. Please specify account, products, and quantity."}

#     account_name = extracted_details.get("account", "").strip()
#     opportunity_name = extracted_details.get("opportunity", "").strip()

#     # ✅ Ensure opportunity is provided before proceeding
#     if session_data.get("pending_action") == "confirm_opportunity":
#         if opportunity_name:
#             session_data["opportunity"] = opportunity_name
#             session_data["pending_action"] = "add_product"  # ✅ Update the flow to expect product addition next
#             return {"message": f"✅ Opportunity `{opportunity_name}` added. Would you like to add products now?"}
#         else:
#             return {"message": "📝 Please provide an opportunity name before creating the quote."}

#     # ✅ Check if Account exists or create it
#     account, _ = Account.objects.get_or_create(name=account_name)

#     # ✅ Check if Opportunity exists or create it
#     opportunity, _ = Opportunity.objects.get_or_create(name=session_data.get("opportunity", opportunity_name), account=account)

#     # ✅ Create Quote
#     quote = Quote.objects.create(
#         account=account,
#         opportunity=opportunity,
#         status="Draft",
#         net_amount=0
#     )
#     # ✅ Assign name after creation using quote.id
#     quote.name = f"Q-0000{quote.id}"
#     quote.save()

#     # ✅ Store quote context in session & clear pending actions
#     session_data["active_quote"] = {
#         "quote_id": quote.id,
#         "account": account_name,
#         "opportunity": opportunity_name
#     }
#     session_data["pending_action"] = "add_product"  # ✅ Ensure we move to the next step

#     return {
#         "message": f"✅ Quote created for {account_name} under opportunity {opportunity_name}. Would you like to add products now?",
#         "quote_id": quote.id
#     }

def create_quote(user_message, session_data):
    """Handles quote creation while preserving context."""
    extracted_details = extract_quote_details(user_message)
    if not extracted_details:
        return {"message": "⚠️ Please provide account, opportunity, and product details."}

    account_name = extracted_details.get("account")
    opportunity_name = extracted_details.get("opportunity", "")

    # ✅ Ensure an opportunity exists before creating the quote
    if not opportunity_name:
        session_data["pending_action"] = "confirm_opportunity"
        session_data["account"] = account_name
        return {"message": f"📝 Please provide an opportunity name for {account_name} before creating the quote."}

    # ✅ Create account and opportunity if needed
    account, _ = Account.objects.get_or_create(name=account_name)
    opportunity, _ = Opportunity.objects.get_or_create(name=opportunity_name, account=account)

    # ✅ Create quote
    quote = Quote.objects.create(
        account=account,
        opportunity=opportunity,
        status="Draft",
        net_amount=0
    )

    session_data["active_quote"] = quote.id
    session_data["pending_action"] = "add_product"

    return {"message": f"✅ Quote {quote.name} created for {account_name}. Would you like to add products now?", "quote_id": quote.id}



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

def show_quote_details(user_message, session_data):
    """Fetches and formats quote details, including quote lines, based on user input or session data."""
    try:
        # ✅ Extract quote name from user message or session
        quote_name = extract_quote_name(user_message) or session_data.get("active_quote", {}).get("quote_name")

        if not quote_name:
            return {"message": "⚠️ Please specify a quote name or select an active quote."}

        # ✅ Get the quote by name
        quote = Quote.objects.get(name=quote_name)

        # ✅ Fetch related quote lines
        quote_lines = QuoteLine.objects.filter(quote=quote)

        # ✅ Calculate the net amount dynamically
        

        net_amount = quote_lines.aggregate(total=Sum(F('total_price')))['total'] or 0

        # ✅ Format the response
        quote_details = {
            "quote_name": quote.name,
            "net_amount": f"${net_amount:.2f}",
            "status": quote.status,
            "account": quote.account.name if quote.account else "N/A",
            "opportunity": quote.opportunity.name if quote.opportunity else "N/A",
            "created_at": quote.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "line_items": [
                {
                    "product": line.product.name,
                    "sku": line.product.sku,
                    "quantity": line.quantity,
                    "unit_price": f"${line.unit_price:.2f}",
                    "total_price": f"${line.total_price:.2f}",
                    # "discount": f"{line.discount}%" if line.discount else "0%"
                } for line in quote_lines
            ]
        }

        return {"message": "✅ Here are the quote details:", "quote_details": quote_details}

    except Quote.DoesNotExist:
        return {"message": "⚠️ Error: Quote not found. Please check the quote name."}
    

def extract_quote_name(user_message):
  """Extracts a quote name from the user input."""
  match = re.search(r'Q-\d+', user_message)
  return match.group(0) if match else None
