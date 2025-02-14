from django.db.models import Sum, F
import json
import os
import openai
import logging
import re
from dotenv import load_dotenv
from cpq.models import Quote, Account, Opportunity, QuoteLine, Product
from decimal import Decimal
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from django.http import FileResponse
from django.conf import settings
from reportlab.lib.colors import HexColor
from django.http import JsonResponse
from django.db import models


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
        "GenerateQuoteDocument": generate_quote_pdf,
        "UpdateQuoteLine": update_quote_line,
        # "ApplyDiscount": apply_discount,
        # "ProvideDates": provide_dates,
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request."}

def create_quote(user_message, session_data):
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
    # ✅ Assign name after creation using quote.id
    quote.name = f"Q-0000{quote.id}"
    quote.save()

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
    logging.info("🔄 Adding product to an existing quote...")

    # ✅ Ensure we have an active quote
    active_quote = session_data.get('active_quote')

    if not active_quote or "quote_id" not in active_quote:
        logging.info("🔎 No active quote found in session. Searching by name...")
        
        # ✅ Extract quote name (Q-xxxx) from user input
        extracted_quote_name = extract_quote_name(user_message)  # Implement this function
        if not extracted_quote_name:
            return {"message": "⚠️ No active quote found. Please provide a quote name (e.g., Q-0019) or create a new quote first."}
        
        # ✅ Search for the quote by name
        try:
            quote = Quote.objects.get(name=extracted_quote_name)
            session_data["active_quote"] = {"quote_id": quote.id, "quote_name": quote.name}  # Store in session
            logging.info(f"🟢 Found and set active quote: {quote.name}")
        except Quote.DoesNotExist:
            return {"message": f"⚠️ Quote `{extracted_quote_name}` not found. Please ensure it exists or create a new one."}
    else:
        # ✅ Retrieve quote using session data
        try:
            quote = Quote.objects.get(id=active_quote['quote_id'])
        except Quote.DoesNotExist:
            return {"message": f"⚠️ Session references a non-existent quote. Please provide a valid quote name."}

    # ✅ Extract product details
    extracted_product = extract_product_details(user_message)
    if not extracted_product:
        return {"message": "⚠️ Error: Could not extract product details. Please specify SKU and quantity."}

    sku = extracted_product.get("sku")
    quantity = extracted_product.get("quantity", 1)
    discount = extracted_product.get("discount", 0)

    # ✅ Validate product exists
    try:
        product = Product.objects.get(sku=sku)
    except Product.DoesNotExist:
        return {"message": f"⚠️ Product `{sku}` not found. Please ensure it exists in the catalog."}

    # ✅ Ensure unit price and discount are Decimal values
    unit_price = Decimal(product.price)
    discount_multiplier = Decimal((100 - discount) / 100)

    # ✅ Create Quote Line Item
    quote_line = QuoteLine.objects.create(
        quote=quote,
        product=product,
        quantity=quantity,
        unit_price=unit_price,
        total_price=(unit_price * Decimal(quantity)) * discount_multiplier
    )

    # ✅ Update quote net amount
    quote.net_amount += quote_line.total_price
    quote.save()

    # ✅ Reset pending action and update session
    session_data["pending_action"] = None  
    session_data["active_quote"] = {"quote_id": quote.id, "quote_name": quote.name}  # Ensure session persists
    return {
        "message": f"✅ Added {quantity}x {sku} to quote `{quote.name}`. Net amount updated to ${quote.net_amount:.2f}. Would you like to add more products or apply a discount?"
    }

def update_quote_line(user_message, session_data):
    """Updates only the modified fields in quote lines."""
    try:
        updates = json.loads(user_message.replace("Update Quote Line: ", ""))  # Extract JSON array

        active_quote = session_data.get("active_quote")

        if not active_quote:
            logging.warning("⚠️ No active quote found in session. Attempting to extract from message...")
            extracted_quote_name = extract_quote_name(user_message)

            if extracted_quote_name:
                try:
                    quote = Quote.objects.get(name=extracted_quote_name)
                    session_data["active_quote"] = {"quote_id": quote.id, "quote_name": quote.name}  # Store in session
                except Quote.DoesNotExist:
                    return {"message": f"⚠️ No quote found with name {extracted_quote_name}."}
            else:
                return {"message": "⚠️ No active quote found. Please specify a quote name."}
        else:
            quote = Quote.objects.get(id=session_data["active_quote"]["quote_id"])

        for update in updates:
            sku = update["sku"]
            field = update["field"]
            new_value = update["value"]

            try:
                quote_line = QuoteLine.objects.get(quote=quote, product__sku=sku)
            except QuoteLine.DoesNotExist:
                return {"message": f"⚠️ Error: No line item found for SKU {sku} in this quote."}

            # ✅ Update based on the field dynamically
            if field == "quantity":
                quote_line.quantity = int(new_value)
            elif field == "unit_price":
                quote_line.unit_price = Decimal(new_value)

            quote_line.save()

        return {"message": "✅ Quote line(s) updated successfully."}

    except Exception as e:
        return {"message": f"⚠️ Error updating quote line: {str(e)}"}

def extract_quote_line_updates(user_message):
    """Uses GPT to extract SKU, field, and new value for quote line updates."""
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        prompt = f"""
        Extract structured update details from the following request.
        Return a JSON array with objects containing:
        - "sku" (string, required)
        - "field" (string, either "quantity" or "unit_price")
        - "value" (string or number, new value)

        **Example Input & Output:**
        User: "Update AI-10 quantity to 600 and price to 49.99"
        Response:
        [
            {{"sku": "AI-10", "field": "quantity", "value": "600"}},
            {{"sku": "AI-10", "field": "unit_price", "value": "49.99"}}
        ]

        **IMPORTANT:** Only return the JSON array. Do not include any explanation, labels, or extra text.

        User Request: "{user_message}"
        """

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )

        raw_response = response.choices[0].message.content.strip()
        
        # 🔍 Log raw GPT response
        logging.info(f"🔍 Raw GPT Response: {raw_response}")

        # ✅ Fix: Remove unwanted prefixes like "Response:"
        cleaned_response = raw_response.lstrip("Response:").strip()

        try:
            extracted_data = json.loads(cleaned_response)

            # Ensure GPT response is a list
            if isinstance(extracted_data, list):
                return extracted_data
            else:
                logging.warning("⚠️ GPT did not return a list, returning empty array.")
                return []

        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON after cleaning: {cleaned_response}")
            return []

    except Exception as e:
        logging.error(f"❌ Error extracting quote line updates: {str(e)}")
        return []

def extract_quote_name(user_message):
    """Extracts the quote name from user input."""
    import re
    match = re.search(r"\bQ-\d{4,}\b", user_message)
    return match.group(0) if match else None

def show_quote_details(user_message, session_data):
    """Fetches and formats quote details, including quote lines, based on user input or session data."""
    try:
        # ✅ Extract quote name from user message or session
        quote_name = extract_quote_name(user_message) or session_data.get("active_quote", {}).get("quote_name")

        if not quote_name:
            return {"message": "⚠️ Please specify a quote name or select an active quote."}

        # ✅ Get the quote by name
        quote = Quote.objects.get(name=quote_name)
        session_data["active_quote"] = {"quote_id": quote.id}
         # ✅ Update session to track the active quote
    

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

def format_currency(value):
    """Formats a Decimal value into currency format with commas and two decimal places."""
    return f"{value:,.2f}"  # Example: 3,000.00 instead of 3000.0

def generate_quote_pdf(user_message, session_data):
    """Generates a sleek PDF document for the specified quote."""
    try:
        # ✅ Ensure we have an active quote
        active_quote = session_data.get("active_quote", {})
        if not active_quote:
            return {"message": "⚠️ No active quote found. Please specify a quote name."}

        # ✅ Retrieve quote using session data
        try:
            quote = Quote.objects.get(id=active_quote['quote_id'])
        except Quote.DoesNotExist:
            return {"message": "⚠️ Session references a non-existent quote. Please provide a valid quote name."}

        # ✅ Fetch related quote lines
        quote_lines = QuoteLine.objects.filter(quote=quote)

        # ✅ Generate file name
        pdf_filename = f"Quote_{quote.name}.pdf"
        pdf_path = os.path.join(settings.MEDIA_ROOT, pdf_filename)

        # ✅ Create PDF in memory
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=letter)
        pdf.setTitle(f"Quote {quote.name}")

        # ✅ Add Logo (Update path if needed)
        logo_path = os.path.join(settings.MEDIA_ROOT, "company_logo.png")  
        if os.path.exists(logo_path):
            pdf.drawImage(logo_path, 50, 700, width=150, height=60, preserveAspectRatio=True, mask='auto')

        # ✅ Quote Header
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(400, 750, f"Quote: {quote.name}")

        # ✅ Company & Quote Information
        pdf.setFont("Helvetica", 12)
        pdf.drawString(50, 660, "Company Name")
        pdf.drawString(50, 640, f"Opportunity: {quote.opportunity.name if quote.opportunity else 'N/A'}")
        pdf.drawString(50, 620, f"Status: {quote.status}")
        pdf.drawString(50, 600, f"Created At: {quote.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    
        # ✅ Account Information
        pdf.drawString(350, 660, f"Account: {quote.account.name if quote.account else 'N/A'}")
        pdf.drawString(350, 640, f"Opportunity: {quote.opportunity.name if quote.opportunity else 'N/A'}")
        pdf.drawString(350, 620, f"Status: {quote.status}")
        pdf.drawString(350, 600, f"Created At: {quote.created_at.strftime('%Y-%m-%d %H:%M:%S')}")

        pdf.setFillColor(HexColor("#5c5c5c"))
        # pdf.rect(50, 560, 520, 30, fill=False, stroke=True)  # Background color for header
        pdf.setLineWidth(0.5)
        pdf.setStrokeColor(HexColor("#cccccc"))  # light gray color
        pdf.rect(47, 540, 520, 30, fill=False, stroke=True)
        
        pdf.setFillColor(HexColor("#000000"))  # White text
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(55, 550, "Product")
        pdf.drawString(200, 550, "SKU")
        pdf.drawString(300, 550, "Quantity")
        pdf.drawString(400, 550, "Unit Price")
        pdf.drawString(500, 550, "Total Price")

        # ✅ Line Items
        y_position = 520
        pdf.setFont("Helvetica", 10)

        for line in quote_lines:
            pdf.drawString(50, y_position, line.product.name)
            pdf.drawString(200, y_position, line.product.sku)
            pdf.drawString(300, y_position, str(line.quantity))
            pdf.drawString(400, y_position, f"${format_currency(line.unit_price)}")
            pdf.drawString(500, y_position, f"${format_currency(line.total_price)}")
            y_position -= 20  # Move to the next line

        # ✅ Net Amount - Display at Bottom Right
        formatted_net_amount = f"${format_currency(quote.net_amount)}"
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(300, y_position - 30, "Total Quote Amount:")
        pdf.drawString(500, y_position - 30, formatted_net_amount)

        # ✅ Save PDF to buffer
        pdf.showPage()
        pdf.save()

        # ✅ Save the buffer content to the file
        with open(pdf_path, "wb") as f:
            f.write(buffer.getvalue())

        buffer.close()

        return {
            "message": "📄 Quote PDF generated successfully!",
            "download_url": f"{settings.MEDIA_URL}{pdf_filename}"
            }

    except Quote.DoesNotExist:
        return {"message": "⚠️ Error: Quote not found."}
    except Exception as e:
        return {"message": f"⚠️ Error generating PDF: {str(e)}"}