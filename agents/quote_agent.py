from django.db.models import Sum, F
import json
import os
import openai
import logging
import re
import locale
from dotenv import load_dotenv
from cpq.models import Quote, Account, Opportunity, QuoteLine, Product, QuoteDocument, Tenant, QuoteDocumentSettings, BusinessRule
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas
from django.http import FileResponse
from django.conf import settings
from reportlab.lib.colors import HexColor, red
from django.http import JsonResponse
from django.db import models
from agents.approvals_agent import get_approval_status
from django.db.models import Max
from django.db.models import Q
from django.forms.models import model_to_dict
from django.db.models import ForeignKey
from datetime import datetime
from agents.admin_agent import check_for_rules


# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"
# OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

def quote_agent(action, user_message, session_data):

    action_map = {
        "CreateQuote": create_quote,
        "ShowQuoteDetails": show_quote_details,
        "AddProduct": add_product_to_quote,
        "GenerateQuoteDocument": generate_quote_pdf,
        "UpdateQuoteLine": update_quote_line,
        "UpdateQuote": update_quote,
        "ApplyQuoteLineDiscount": apply_discount_to_quote_line,
        "ApplyQuoteDiscount": apply_discount_to_quote,
        "DeleteQuoteLine": delete_quote_line,
        "DeleteQuote": delete_quote,
        "UpdateQuoteNotes": update_quote_notes,
        "ShowQuoteNotes": show_quote_notes,
        # "ProvideDates": provide_dates,
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request."}

def create_quote(user_message, session_data):
    """Handles quote creation while preserving context."""
    extracted_details = extract_quote_details(user_message)
    logging.info(f"\n\nDetails: {extracted_details}\n\n")
    account_name = extracted_details.get("account", session_data.get("account", "")).strip()
    opportunity_name = extracted_details.get("opportunity", session_data.get("opportunity", "")).strip()
    
    #  -------------- MODIFICATION --------------
    extracted_products = extracted_details.get("products", []) # ✅ Extract products

    if not account_name:
        return {
            "message": "⚠️ Error: Could not determine the account. Please specify an account name."
        }

    opportunity = Opportunity.objects.filter(name=opportunity_name, account__name=account_name).first()

    if not opportunity:
        opportunity_name = f"Opportunity {account_name}"
    
    if session_data.get("pending_action") == "confirm_opportunity":
        session_data["opportunity"] = opportunity_name
        session_data["pending_action"] = "add_product"  
        return {
            "message": f"✅ Opportunity {opportunity_name} added. Would you like to add more products now?"
            }

    if not opportunity_name:
        return {
            "message": "📝 Please provide an opportunity name before creating the quote."
        }
    
    # ✅ Create or retrieve Account
    account, _ = Account.objects.get_or_create(name=account_name)

    # ✅ Create or retrieve Opportunity
    opportunity, _ = Opportunity.objects.get_or_create(name=opportunity_name, account=account)

    # ✅ Create Quote
    quote = Quote.objects.create(
        account=account,
        opportunity=opportunity,
        status="Draft",
        net_amount=Decimal("0.00")
    )

    # ✅ Assign formatted name after creation using quote.id
    quote.name = f"Q-{quote.id:05d}"
    quote.save()

    # ✅ Store quote context in session & clear pending actions
    session_data["active_quote"] = {
        "quote_id": quote.id,
        "account": account_name,
        "opportunity": opportunity_name
    }
    
    # -------------- MODIFICATION START --------------
    if not extracted_products:
        logging.info("🟡 No products provided in initial quote creation.")

        session_data["pending_action"] = "add_product"

        return {
            "message": f"✅ Quote {quote.name} created for {account_name} under opportunity {opportunity_name}. Would you like to add more products now?"
        }
    else:
        logging.info("🟡 Products provided in initial quote creation.")

        # ✅ Add products to the quote if provided
        added_products = []

        response_message = f"✅ Quote {quote.name} created for {account_name} under deal {opportunity_name}.<br><br>"

        for product_data in extracted_products:
            sku = product_data.get("sku")
            name = product_data.get("name")
            quantity = product_data.get("quantity", 1)
            discount_type = product_data.get("discount_type", "None")
            discount_value = Decimal(product_data.get("discount_value", "0.00"))
            term=product_data.get("term", None)

            logging.info(f"=>>>>>>>>>>>>>>>>>>>> For product: {sku}")

            # Validate if quantity is be able to converto to int and is bigger than 0
            raw_quantity = product_data.get("quantity", 1)

            try:
                quantity = int(raw_quantity)
                if quantity <= 0:
                    logging.warning(f"⚠️ Invalid quantity '{quantity}' for product {sku or name}. Skipping...")
                    response_message += f"⚠️ Invalid quantity '{quantity}' for product {sku or name}. Skipping...<br>"
                    continue
            except (ValueError, TypeError):
                logging.warning(f"⚠️ Quantity '{raw_quantity}' is not a valid integer for product {sku or name}. Skipping...")
                response_message += f"⚠️ Quantity '{raw_quantity}' is not a valid integer for product {sku or name}. Skipping...<br>"
                continue

            # ✅ Validate product exists
            try:
                product = Product.objects.get(Q(sku=sku) | Q(name=sku) | Q(sku=name) | Q(name=name))
            except Product.DoesNotExist:
                logging.warning(f"⚠️ Product `{sku if sku and sku != 'Null' else name}`. Skipping...")
                response_message += f"⚠️ Product `{sku if sku and sku != 'Null' else name}` not found. Skipping...<br>"
                continue  # Skip this product and move to the next

            # ✅ Ensure proper rounding for calculations
            unit_price = Decimal(product.price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            logging.info(f"=>>>>>>>>>>>>>>>>>>>> Unit Price: {unit_price}")
            logging.info(f"=>>>>>>>>>>>>>>>>>>>> Quantity: {quantity}")

            if product.is_subscription:
                if term == "None":
                    term = 1
                else:
                    term = int(term)
            else:
                term = None

            if discount_type == "percentage":
                # ✅ Create Quote Line Item for discount percentage
                quote_line = QuoteLine.objects.create(
                    quote=quote,
                    product=product,
                    quantity=quantity,
                    unit_price=unit_price,
                    is_subscription=product.is_subscription,
                    term=term,
                    discount_type=discount_type,
                    discount_percentage=Decimal(discount_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                )
            elif discount_type == "amount":
                # ✅ Create Quote Line Item for discount amount
                quote_line = QuoteLine.objects.create(
                    quote=quote,
                    product=product,
                    quantity=quantity,
                    unit_price=unit_price,
                    is_subscription=product.is_subscription,
                    term=term,
                    discount_type=discount_type,
                    discount_amount=Decimal(discount_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                )
            else:
                # ✅ Create Quote Line Item if no discount was provided
                quote_line = QuoteLine.objects.create(
                    quote=quote,
                    product=product,
                    quantity=quantity,
                    unit_price=unit_price,
                    is_subscription=product.is_subscription,
                    term=term,
                    discount_type="None",
                    discount_amount=Decimal("0").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    discount_percentage=Decimal("0").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                )


            # ✅ Force saving and reloading from DB to verify
            quote_line.refresh_from_db()
            logging.info(f"=>>>>>>>>>>>>>>>>>>>> Saved Total Price in DB: {quote_line.total_price}")

            sku = product.sku
            name = product.name
            
            if discount_type == "percentage":
                added_products.append(f"{quantity}x {sku}/{name} with {discount_value}% discount.")
                response_message += f"✅ Added {quantity}x {sku}/{name} to quote {quote.name} with a {discount_value}% discount.<br>"
            elif discount_type == "amount":
                added_products.append(f"{quantity}x {sku} with ${discount_value} discount.")
                response_message += f"✅ Added {quantity}x {sku}/{name} to quote {quote.name} with a ${discount_value} discount.<br>"
            else:
                added_products.append(f"{quantity}x {sku}.")
                response_message += f"✅ Added {quantity}x {sku}/{name} to quote {quote.name}.<br>"


        # ✅ Update quote (subtotal, discounts fields and net amount)
        quote.save()

        # ✅ Update amount in Opportunity
        update_opportunity_net_amount(quote.opportunity)

        # ✅ Reset pending action and update session
        session_data["pending_action"] = None  
        session_data["active_quote"] = {"quote_id": quote.id, "quote_name": quote.name}  # Ensure session persists
        
        # ✅ Check if the quote requires approval after adding the product
        approval_suggestion = get_approval_status("", "", quote.id, "")

        if added_products:
            response_message += (
                f"<br>Net amount updated to ${quote.net_amount:.2f}."
                "Would you like to add more products?"
            )
        else:
            #Check if no added products (in case GPT model recognizes a product that doesn't exist.)
            session_data["pending_action"] = "add_product"  # ✅ Ensure we move to the next step

            return {
                "message": f"✅ Quote `{quote.name}` created for {account_name} under opportunity `{opportunity_name}`.<br> Would you like to add more products now?"
            }
        
        # If an approval suggestion exists, append it to the message
        if "message" in approval_suggestion:
            response_message += f"\n\n{approval_suggestion['message']}"
        
            return {
                "message": response_message
            }
        else:
            return {
                "message": "⚠️ No approval suggestion."
            }


#< ----------------- ADD PRODUCT TO QUOTE -------------------- >

def add_product_to_quote(user_message, session_data):
    """Handles adding multiple products to an existing quote."""
    logging.info("🔄 Adding product(s) to existing quote...")

    # Looking for active quote
    quote = get_active_quote(user_message, session_data)


    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        return quote
    

    # ✅ Extract multiple product details
    extracted_products = extract_product_details(user_message)
    if not extracted_products or not isinstance(extracted_products, list):
        return {"message": "⚠️ Error: Could not extract product details. Please specify SKU, quantity, and discount for each product."}

    added_products = []
    response_message = ""
    violation_products = []

    for index, product_data in enumerate(extracted_products, start=1):
        sku = product_data.get("sku")
        raw_quantity = product_data.get("quantity", 1)
        try:
            quantity = int(raw_quantity)
        except (ValueError, TypeError):
            quantity = 1

        name = product_data.get("name", "None")
        discount_type = product_data.get("discount_type", 0)
        discount_amount = product_data.get("discount_amount", 0)
        term = product_data.get("term", 0)

        # ✅ Validate product exists
        product = None

        try:
            product = Product.objects.get(Q(sku=sku) | Q(name=sku) | Q(sku=name) | Q(name=name))
        except Product.DoesNotExist:
            msg = f"⚠️ Product `{sku}/{name}` could not be identified. Skipping...<br>"
            response_message += msg
            logging.warning(msg)
            continue

        sku = product.sku
        name = product.name

        # Descriptive prefix for messages
        product_label = f"Product {index} ({name if name != 'Null' else sku})"

        if int(quantity) <= 0:
            response_message += f"⚠️ {product_label}: Quantity cannot be less than or equal to 0. Please enter a valid quantity.<br><br>"
            continue

        if float(discount_amount) < 0:
            response_message += f"⚠️ {product_label}: Discount cannot be less than 0. Please enter a valid discount.<br><br>"
            continue

        # Set term
        if product.is_subscription and (term == 0 or term == "None" or term == None):
            term = 1
        elif not product.is_subscription:
            term = None

        ################################################# ✅ Checkrules

        temp_quote_line = build_temp_quote_line(quote, product, quantity, discount_type, Decimal(discount_amount), term)

        violations = check_for_rules("quote_line", quote, product, temp_quote_line)
        #print(f"\n\nViolations: {violations}")

        if violations:
            violation_message = ""
            for v in violations:
                violation_message += f"- {v}<br>"
            violation_products.append(f"\n\n🛑 Product {product.name}/{product.sku} violated one or more validation rules 🛑<br>{violation_message}")
            print(f"\n\nViolation with product {product.name}/{product.sku}. Skipping...\n\n")
            continue

        #################################################


        # ✅ Check if product already exists in the quote
        existing_line = QuoteLine.objects.filter(quote=quote, product=product).first()

        if existing_line:
            logging.info(f"🔁 Product `{sku}/{name}` already in quote. Updating instead of creating.")

            new_quantity = existing_line.quantity + int(quantity)

            update_payload = [{
                "sku": sku,
                "field": "quantity",
                "value": str(new_quantity),
                "quote_line_id": str(existing_line.id),
                "hiddenMessage": True
            }]

            # Only add discount if discount is different than 0
            if Decimal(discount_amount) != 0 and discount_type in ["percentage", "amount"]:
                update_payload.append({
                    "sku": sku,
                    "field": "discount_percentage" if discount_type == "percentage" else "discount_amount",
                    "value": str(discount_amount),
                    "quote_line_id": str(existing_line.id),
                    "hiddenMessage": True
                })

            if term:
                update_payload.append({
                    "sku": sku,
                    "field": "term",
                    "value": str(term),
                    "quote_line_id": str(existing_line.id),
                    "hiddenMessage": True
                })

            user_message = f"Update Quote Line: {json.dumps(update_payload)}"

            
            response = update_quote_line(user_message, session_data)

            if (
                response.get("message") == "✅ Quote line(s) updated successfully." and
                "quote_details" in response and
                "line_items" in response["quote_details"]
            ):
                if discount_type == "percentage":
                    added_products.append(f"{quantity}x `{sku}/{name}`` with {discount_amount}% discount")
                elif discount_type == "amount":
                    added_products.append(f"{quantity}x `{sku}/{name}` with ${discount_amount} discount")
                else:
                    added_products.append(f"{quantity}x `{sku}/{name}`")
            else:
                response_message+= "⚠️ Error: While updating quote line {sku}/{name}.<br><br>"
                logging.warning("⚠️ Update Failed")


            # ✅ Refresh quote to get new net_amount from database
            quote.refresh_from_db()
            existing_line.refresh_from_db()

            continue
        
        # Add product where quote line hasn't been added
        # ✅ Create Quote Line Item

        sku = product.sku
        name = product.name
        
        if discount_type == "percentage":
            quote_line = QuoteLine.objects.create(
                quote=quote,
                product=product,
                quantity=quantity,
                term=term,
                discount_type="percentage",
                discount_percentage=discount_amount,
                discount_amount=0,
                description=product.description,
                is_subscription=product.is_subscription,
            )
            added_products.append(f"{quantity}x `{sku}/{name}` with {discount_amount}% discount")
        elif discount_type == "amount":
            quote_line = QuoteLine.objects.create(
                quote=quote,
                product=product,
                quantity=quantity,
                term=term,
                discount_type="amount",
                discount_amount=discount_amount,
                discount_percentage=0,
                description=product.description,
                is_subscription=product.is_subscription,
            )
            added_products.append(f"{quantity}x `{sku}/{name}` with ${discount_amount} discount")
        else:
            quote_line = QuoteLine.objects.create(
                quote=quote,
                product=product,
                quantity=quantity,
                term=term,
                discount_type="None",
                discount_amount=0,
                discount_percentage=0,
                description=product.description,
                is_subscription=product.is_subscription,
            )

            print(f"\n\nQuote Line: {quote_line}\n\n")
            added_products.append(f"{quantity}x `{sku}/{name}`")

        # ✅ Force saving and reloading from DB to verify
        quote_line.refresh_from_db()
        logging.info(f"=>>>>>>>>>>>>>>>>>>>> Saved Total Price in DB: {quote_line.total_price}")

        #response_message += "✅ Added product successfully.<br><br>"
        continue

    #If AI Model indetify a product but it does not exist
    if not added_products:
        if violations:
            return {
                "message": violation_products
            }
        return {
            "message": "⚠️ Error: Something went wrong — no product was added to the quote. Please try again or verify your input."
        }
    
    # ✅ Update quote (subtotal, discounts fields and net amount)
    quote.save()

    # ✅ Reset pending action and update session
    session_data["pending_action"] = None  
    set_active_quote_to_session_data(session_data, quote)

     # ✅ Check if the quote requires approval after adding the product
    approval_suggestion = get_approval_status("", "", quote.id, "")

    if added_products:
        for product in added_products:
            print(f"\n\n Products: {added_products}\n\n")
            response_message += f"✅ Added {product} to quote `{quote.name}`.<br>"
        
        if violation_products:
            response_message += "\n".join(violation_products)
        
        response_message += f"<br>💰 Net amount updated to ${quote.net_amount:,.2f}. Would you like to add more products?"
    
    # If an approval suggestion exists, append it to the message
    if "message" in approval_suggestion:
        response_message += f"\n\n{approval_suggestion['message']}"
    
        return {
            "message": response_message,
            "update_details": get_quote_details(quote),
            "temporaryMessage": True,
            "iterations": index
        }
    else:
        return {
            "message": "⚠️ No valid products were added. Please check the SKUs and try again."
        }
    

#< ----------------- APPLY DISCOUNT TO QUOTE LINE -------------------- >

def apply_discount_to_quote_line(user_message, session_data):
    """Applies a discount to a specific product in the quote based on the user message."""
    logging.info("🔧 Applying discount to product in quote...\n\n")
    # Looking for active quote
    quote = get_active_quote(user_message, session_data)

    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        return quote
    
    # ✅ Save quote in session data
    set_active_quote_to_session_data(session_data, quote)

    response_message = ""
        
    # ✅ Extract multiple discount details
    extracted_discounts = extract_discount_details(user_message)
    if not extracted_discounts or not isinstance(extracted_discounts, list):
        return {"message": "⚠️ Error: Could not extract discount details. Please specify SKU and discount for each product."}

    added_discounts = []

    for index, discount_data in enumerate(extracted_discounts, start=1):
        sku = discount_data.get("sku")
        name = discount_data.get("name")
        discount = discount_data.get("discount", 0)

        #If LLM did not find a SKU
        if sku == "NoneAppear" and name == "Null":
            return {
                "message": "⚠️ Error: No SKU or name was detected in your request. Please specify the product code(s)/name to apply the discount."
            }
        
        #If LLM did not find a discount percent
        if discount == -1:
            return {
                "message": "⚠️ Error: No discount was detected in your request. Please specify the discount percentage to apply."
            }

        # ✅ Validate product exists
        product = None
        try:
            product = Product.objects.get(Q(sku=sku) | Q(name=sku) | Q(sku=name) | Q(name=name))
        except Product.DoesNotExist:
            response_message += f"⚠️ Error: Product `{sku}` does not exist in the catalog.<br>"
            logging.warning(f"⚠️ Product `{sku}` not found. Skipping...")
            continue  # Skip this product and move to the next

        sku = product.sku
        name = product.name

        # ✅ Check if product already exists in the quote
        existing_line = QuoteLine.objects.filter(quote=quote, product=product).first()

        if not existing_line:
            response_message += f"⚠️ Error: Product `{sku}/{name}` exists, but is not part of quote `{quote.name}`.<br>"
            continue
        
        logging.info(f"🔁 Product `{sku}/{name}` is already in quote. Applying a discount.")

        update_payload = [{
            "sku": sku,
            "field": "discount",
            "value": discount,
            "quote_line_id": str(existing_line.id),
            "hiddenMessage": True
        }]

        discount_agent_message = f"Update Quote Line: {json.dumps(update_payload)}"

        response = update_quote_line(discount_agent_message, session_data)
        if response:
            added_discounts.append(f"`{sku}/{name}` added/updated with {discount}% discount")
    
    if not added_discounts:
        response_message += "⚠️ Error: Something went wrong while trying to apply the discount."
        return {
            "message": response_message
        }
    
    # ✅ Update quote (subtotal, discounts fields and net amount)
    quote.save()
    quote.refresh_from_db()
    
    response_message = ""

    for discount in added_discounts:
        response_message += f"✅ {discount} to quote `{quote.name}`.<br>"
    
    response_message += f"<br><br>💰 Net amount updated to ${quote.net_amount:,.2f}. Would you like to apply discounts to more products?"

    # ✅ Check if the quote requires approval after adding the product
    approval_suggestion = get_approval_status("", "", quote.id, "")
    
    # If an approval suggestion exists, append it to the message
    if "message" in approval_suggestion:
        response_message += f"\n\n{approval_suggestion['message']}"
    
    return {
        "message": response_message,
        "update_details": response["quote_details"],
        "temporaryMessage": True,
        "iterations": index
    }

    
def extract_product_details(user_message):
    """Extract multiple product SKUs, quantities, and discounts from user input using GPT."""
    prompt = f"""
    Extract all product details from the user's request. The user may specify multiple products in a single message.

    **Expected fields per product:**
    - sku (string, unique identifier)
    - name (string, product name)
    - quantity (integer, default 1 if not specified)
    - discount_type ("percentage" or "amount", based on how the user specifies the discount)
    - discount_amount (integer, default 0 if not specified)
    - term (integer, default 0 if not specified)(term is for subscription)

    **Instructions for discounts:**
    - Use `"percentage"` for `discount_type` if the user specifies a percentage (e.g., "15%", "15 percent").
    - Use `"amount"` for `discount_type` if the user specifies a fixed amount (e.g., "$15", "15 dollars", "15 USD").
    - Extract the numeric part and set it as `discount_amount` (e.g., "15%" → 15, "$15" → 15).
    - If no discount is mentioned, set `"discount_type": "None"` and `"discount_amount": "0"`.

    **Example Input:** 
    "Add AI-CPQ-001 x 5 with 10% discount, Agency PQ Solo x 2 with $20 discount, and AI-CPQ-004 x 10."

    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-001", "name": "Null", "quantity": "5", "discount_type": "percentage", "discount_amount": 10, "term": "None"}},
        {{"sku": "Null", "name": "Agency PQ Solo", "quantity": "2", "discount_type": "amount", "discount_amount": 20}},
        {{"sku": "AI-CPQ-004", "name": "Null", "quantity": "1", "discount_type": "None", "discount_amount": 0}}
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
            if isinstance(extracted_products, list) and all("sku" in p and "name" in p and "quantity" in p and "discount_type" in p and "discount_amount" in p for p in extracted_products):
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
    
def extract_discount_details(user_message):
    """Extract multiple SKUs and discounts from user input using GPT."""

    prompt = f"""
    Extract only the discount and SKU for each product from the user's request. The user may specify multiple products and discounts in a single message.

    **Expected fields per product:**
    - sku (string, unique identifier, must appear explicitly in the user message)
    - name (string)
    - discount (integer, percentage, default 0 if not specified)

    If no SKUs are found in the message, return NoneAppear as SKU]
    If no name are found in the message, return Null as Name
    If no discount are found in the message, return -1 as discount]

    **Example Input:**
    "Apply 20% discount to AI-CPQ-001 and 10% off Python System. Also give 15% discount on AI-CPQ-003."

    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-001", "name": "Null", "discount": 20}},
        {{"sku": "NoneAppear", "name": "Python System", "discount": 10}},
        {{"sku": "AI-CPQ-003", "name": "Null", "discount": 15}}
    ]

    **Example Input with no SKU:**
    "Apply a 50% discount."

    **Expected JSON Output:**
    [
        {{"sku": "NoneAppear", "name": "Null",  "discount": 50}}
    ]

    **Example Input with no discount:**
    "Apply a discount to AI-CPQ-001."

    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-001", "name": "Null", "discount": -1}}
    ]


    **User Request:** "{user_message}"

    **Return a valid JSON array only of product objects. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract structured discount details for quote addition."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_discounts = json.loads(raw_response)
            if isinstance(extracted_discounts, list) and all("sku" in p and "discount" in p for p in extracted_discounts):
                return extracted_discounts
            else:
                logging.warning("⚠️ GPT response is not in expected format.")
                return None
        except json.JSONDecodeError:
            logging.error(f"❌ GPT returned invalid JSON: {raw_response}")
            return None

    except Exception as e:
        logging.error(f"❌ Error extracting discount details: {str(e)}")
        return None    
    
def apply_discount_to_quote(user_message, session_data):
    """Applies a discount to quote based on the user message."""
    logging.info("🔧 Applying discount to quote level...\n\n")

    # Looking for active quote
    quote = get_active_quote(user_message, session_data)

    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        return quote
    
    # ✅ Save quote in session data
    set_active_quote_to_session_data(session_data, quote)

    # ✅ Check if quote has quote line items
    quote_lines = quote.quote_lines.all()

    if not quote_lines.exists():
        return {
            "message": "⚠️ Error: The selected quote has no line items. Please add products to the quote before applying a discount."
        }

    response_message = ""
        
    # ✅ Extract multiple discount details
    extracted_discounts = extract_quote_level_discount(user_message)
    if not extracted_discounts or not isinstance(extracted_discounts, list):
        return {"message": "⚠️ Error: Could not extract discount details. Please specify the discount."}

    added_discounts = []

    for index, discount_data in enumerate(extracted_discounts, start=1):
        discount_value = discount_data.get("discount")
        discount_type = discount_data.get("discount_type", 0)

        #If LLM did not find a discount
        if discount_value == "None":
            return {
                "message": "⚠️ Error: No discount was detected in your request. Please specify the discount to apply."
            }
        
        #If LLM did not find a discount type
        if discount_type == "None":
            return {
                "message": "⚠️ Error: No discount type was detected in your request. Please specify the type of discount you'd like to apply (e.g., percentage or dollars)."
            }
        
        #Convert from string to numeric for validations
        discount_numeric_value = Decimal(discount_value)
        
        if discount_type == "percentage" and not (0 < discount_numeric_value <= 100):
            return {
                "message": "⚠️ Error: Percentage discounts must be between 0 and 100."
            }

        if discount_type == "amount" and discount_numeric_value <= 0:
            return {
                "message": "⚠️ Error: Discount amount must be greater than 0."
            }
        
        if discount_type not in ["percentage", "amount"]:
            return {
                "message": "⚠️ Error: Invalid discount type. Please use 'percentage' or 'amount'."
            }
    
        quote_total = quote_lines.aggregate(total=Sum('total_price'))['total'] or 0

        if quote_total == 0:
            return {
                "message": "⚠️ Error: Cannot apply amount-based discount. The quote total is zero."
            }

        if discount_type == "amount":
            #SSave both values
            discount_amount = Decimal(discount_value)
            discount_percentage = (discount_amount / Decimal(quote_total)) * 100
            discount_percentage = discount_percentage.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            added_discounts.append(f"Discount #{index}: ${discount_value} applied to Quote {quote.name}")
        
        else:
            #Discount_type = "percentage"
            discount_percentage = Decimal(discount_value)
            discount_amount = (discount_percentage / Decimal(100)) * Decimal(quote_total)
            print(f"\n\n Discount before quantize: {discount_amount}\n\n")
            discount_amount = discount_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            print(f"\n\n Discount after quantize: {discount_amount}\n\n")
            added_discounts.append(f"Discount #{index}: {discount_value}% applied to Quote {quote.name}")

        # ✅ Apply the discount to the quote
        quote.discount_type = discount_type
        quote.discount_percentage = discount_percentage
        quote.discount_amount = discount_amount

        # ✅ Update quote (subtotal, discounts fields and net amount)
        quote.save()

        # ✅ Update related opportunity
        if quote.opportunity:
            update_opportunity_net_amount(quote.opportunity)


    if not added_discounts:
        response_message += "⚠️ Error: Something went wrong while trying to apply the discount."
        return {
            "message": response_message
        }
    
    quote.refresh_from_db()
    
    response_message = ""

    for discount in added_discounts:
        response_message += f"✅ {discount}.<br>"
    
    response_message += f"<br><br>💰 Net amount updated to ${quote.net_amount:,.2f}."

    # ✅ Check if the quote requires approval after adding the product
    approval_suggestion = get_approval_status("", "", quote.id, "")

    response = get_quote_details(quote)
    
    # If an approval suggestion exists, append it to the message
    if "message" in approval_suggestion:
        response_message += f"\n\n{approval_suggestion['message']}"
    
    return {
        "message": response_message,
        "update_details": response,
        "temporaryMessage": True,
        "iterations": index
    }
    
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

def extract_quote_details(user_message):
    """Use GPT to extract details for quote creation."""
    prompt = f"""
    Extract the following details from the user's request for quote creation:
    - Account Name
    - Opportunity Name (if applicable)
    - Products and Quantities
    - Discounts (if mentioned)
    - Subscription Start/End Dates (if applicable)
    - Term (if mentioned)

    For discounts:
    - If the user specifies a percentage discount (e.g. "15%"), set discount_type to "percentage" and discount_value to the numeric value (e.g. "15").
    - If the user specifies a discount in dollars, with symbols or the word "dollar(s)" (e.g. "$100" or "100 dollars"), set discount_type to "amount" and discount_value to the numeric amount (e.g. "100").
    - If no discount is specified, set discount_type to "None" and discount_value to "0".
    - if no term is specified, set term to "None"

    Return a JSON object with these keys:
    {{"account": "", "opportunity": "", "products": [{{"sku": "", "name": "", "quantity": "", "discount_type": "", "discount_value": "", "term": "None"}}], "start_date": "", "end_date": ""}}.

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

def update_quote_line(user_message, session_data):
    """Updates only the modified fields in quote lines."""

    json_is_exist_in_message = re.search(r'\{.*\}', user_message)

    if user_message.startswith("Update Quote Line: ") and json_is_exist_in_message:
        try:
            updates = json.loads(user_message.replace("Update Quote Line: ", ""))  # Extract JSON array

            # Looking for active quote
            quote = get_active_quote(user_message, session_data)

            # ⚠️ Verify if function return an error
            if isinstance(quote, dict) and "message" in quote:
                return quote

            for update in updates:
                sku = update["sku"]
                field = update["field"]
                new_value = update["value"]
                quote_line_id = update["quote_line_id"]

                try:
                    quote_line = QuoteLine.objects.get(id=quote_line_id, quote=quote, product__sku=sku)
                except QuoteLine.DoesNotExist:
                    # ✅ Save quote in session data
                    set_active_quote_to_session_data(session_data, quote)
                    return {"message": f"⚠️ Error: No line item found for SKU {sku} in this quote."}

                # ✅ Update based on the field dynamically
                if field == "quantity":
                    quote_line.quantity = int(new_value)
                elif field == "unit_price":
                    quote_line.unit_price = Decimal(new_value)
                elif field == "discount_percentage":
                    quote_line.discount_type = "percentage"
                    quote_line.discount_percentage = Decimal(new_value)
                elif field == "discount_amount":
                    quote_line.discount_type = "amount"
                    quote_line.discount_amount = Decimal(new_value)
                elif field == "term":
                    quote_line.term = int(new_value)

                quote_line.save()

            # ✅ Update quote (subtotal, discounts fields and net amount)
            quote.save()
            update_opportunity_net_amount(quote.opportunity)

            # ✅ Save quote in session data
            set_active_quote_to_session_data(session_data, quote)
            
            return {
                "message": "✅ Quote line(s) updated successfully.",
                "quote_details": get_quote_details(quote),
                "hiddenMessage": "True"
            }
        except Exception as e:
            logging.warning(f"⚠️ Error updating quote line: {str(e)}")
            return {"message": f"⚠️ Error updating quote line: {str(e)}"}
    else:
        logging.info("🔧 Updating quote...\n\n")
        # Looking for active quote
        quote = get_active_quote(user_message, session_data)

        # ⚠️ Verify if function return an error
        if isinstance(quote, dict) and "message" in quote:
            return quote
            

        extracted_updates = extract_quote_line_updates(user_message)

        if not extracted_updates:
            # ✅ Save quote in session data
            set_active_quote_to_session_data(session_data, quote)
            
            return {
                "message": "⚠️ AgentCPQ ."
            }

        # Check if exist the product and any (sku, field or value) is NoneAppear
        response_message_alerts = ""
        response = None
        for index, item in enumerate(extracted_updates, start=1):

            field_labels = {
                "quantity": "Quantity",
                "discount_percentage": "Discount Percentage",
                "discount_amount": "Discount Amount",
                "term": "Term"
            }

            item_field = field_labels.get(item["field"], item["field"].capitalize())

            # Does the product exist?
            try:
                product = Product.objects.get(Q(sku=item['sku']) | Q(sku=item['name']))

                show_details_message = f"<b>🔄 <u>Update Request #{index} in quote {quote.name}</u> 🔄</b><br>"
                show_details_message += f"🔢 SKU: {item['sku']}<br>"
                show_details_message += f"🏷️ Field: {item_field}<br>"
                show_details_message += f"✏️ Value: {item['value']}<br><br>"
            except Product.DoesNotExist:
                try:
                    product = Product.objects.get(Q(name=item['sku']) | Q(name=item['name']))

                    show_details_message = f"<b>🔄 <u>Update Request #{index} in quote {quote.name}</u> 🔄</b><br>"
                    show_details_message += f"🔢 Name: {item['name']}<br>"
                    show_details_message += f"🏷️ Field: {item_field}<br>"
                    show_details_message += f"✏️ Value: {item['value']}<br><br>"
                except Product.DoesNotExist:
                    response_message_alerts += show_details_message
                    response_message_alerts += f"⚠️ Error: The product with SKU/Name \"{item['sku']}\" was not found in the database.<br><br>"
                    continue

            item['sku'] = product.sku
            item['name'] = product.name

            #Validate if product exist in actual quote line item
            quote_line = QuoteLine.objects.filter(quote=quote, product=product).first()
            if not quote_line:
                response_message_alerts += show_details_message
                response_message_alerts += f"⚠️ Error: The product with SKU/Name \"{item['sku']}\" is not in the current quote.<br><br>"
                continue

            # Add quote_line_id to item
            item['quote_line_id'] = quote_line.id

            # General validations
            if item['sku'] == 'NoneAppear':
                response_message_alerts += show_details_message
                response_message_alerts += f"⚠️ Error: No SKU/Name was detected in your request. Please specify the product code(s) to update.<br><br>"
                continue

            if item['field'] == 'NoneAppear':
                response_message_alerts += show_details_message
                response_message_alerts += f"⚠️ Error: No field to update was detected in your request. Please specify which attribute (e.g., quantity, discount or term) you want to modify.<br><br>"
                continue

            if item['field'] not in field_labels:
                response_message_alerts += show_details_message
                response_message_alerts += f"⚠️ Error: No valid field to update was detected in your request. Please specify which attribute (e.g., quantity or discount) you want to modify.<br><br>"
                continue

            if item['value'] == "NoneAppear":
                response_message_alerts += show_details_message
                response_message_alerts += f"⚠️ Error: No value was detected in your request. Please specify the new value for the update.<br><br>"
                continue 

            if item['field'] != "discount":
                try:
                    numeric_value = Decimal(item['value'])
                    if numeric_value < 0:
                        response_message_alerts += show_details_message
                        response_message_alerts += f"⚠️ Error: The value for SKU/Name \"{item['sku']}\" cannot be less than 0. Please provide a valid number.<br><br>"
                        continue
                except (InvalidOperation, ValueError, TypeError):
                    response_message_alerts += show_details_message
                    response_message_alerts += f"⚠️ Error: The value \"{item['value']}\" is not a valid number. Please enter a valid numeric value.<br><br>"
                    continue
            
            if item['field'] == "term":
                try:
                    int(item['value'])
                except (ValueError, TypeError):
                    response_message_alerts += show_details_message
                    response_message_alerts += f"⚠️ Error: The value {item['value']} is not a number.<br><br>"
                    continue

                if int(item['value']) < 1:
                    response_message_alerts += show_details_message
                    response_message_alerts += f"⚠️ Error: The value {item['value']} can not be less than 1.<br><br>"
                    continue

            response_message_alerts += show_details_message

            item['sku'] = product.sku #Assign sku to item['sku'] in case of product was found by name
            item_json = json.dumps([item])  #Convert list to valid JSON
            request_message = f"Update Quote Line: {item_json}"

            #Safe active quote to session data
            set_active_quote_to_session_data(session_data, quote)

            response = update_quote_line(request_message, session_data)

            if (
                response.get("message") == "✅ Quote line(s) updated successfully." and
                "quote_details" in response and
                "line_items" in response["quote_details"]
            ):
                response_message_alerts += "✅ Quote line updated successfully.<br><br>"
            else:
                response_message_alerts += "⚠️ Error: While updating quote line.<br>"
                logging.warning("⚠️ Update Failed")

        # ✅ Update quote (subtotal, discounts fields and net amount)
        quote.save()

        if response == None:
            return {
            "message": response_message_alerts,
            "temporaryMessage": True,
            "iterations": index
            }
        
        return {
            "message": response_message_alerts,
            "update_details": response["quote_details"],
            "temporaryMessage": True,
            "iterations": index
            }
            
        

def update_quote(user_message, session_data):
    """Updates only the modified fields in quote lines."""

    json_is_exist_in_message = re.search(r'\{.*\}', user_message)

    if user_message.startswith("Update Quote: ") and json_is_exist_in_message:
        try:
            updates = json.loads(user_message.replace("Update Quote: ", ""))  # Extract JSON array

            for update in updates:
                field = update["field"]
                new_value = update["value"]
                quote = update["quote"]

                try:
                    quote = Quote.objects.get(name=quote)
                except QuoteLine.DoesNotExist:
                    # ✅ Save quote in session data
                    return {"message": f"⚠️ Error: No quote found with name {quote}."}

                # ✅ Update based on the field dynamically
                if field == "expiration_date":
                    parsed_date = datetime.strptime(new_value, "%m/%d/%Y")
                    quote.expiration_date = parsed_date
                elif field == "discount_percentage":
                    quote.discount_type = "percentage"
                    quote.discount_percentage = Decimal(new_value)
                elif field == "discount_amount":
                    quote.discount_type = "amount"
                    quote.discount_amount = Decimal(new_value)
                elif field == "status":
                    quote.status = new_value


            # ✅ Update quote (subtotal, discounts fields and net amount)
            quote.save()

            # ✅ Save quote in session data
            set_active_quote_to_session_data(session_data, quote)
            
            return {
                "message": "✅ Quote was updated successfully.",
                "quote_details": get_quote_details(quote),
                "hiddenMessage": "True"
            }
        except Exception as e:
            logging.warning(f"⚠️ Error updating quote expiration date: {str(e)}")
            return {"message": f"⚠️ Error updating quote expiration date: {str(e)}"}

def update_quote_net_amount(quote):
    """Recalculate and update the quote's net amount based on all quote lines."""
    try:
        # ✅ Fetch total from all related QuoteLines
        quote_total = quote.get_subtotal_amount()

        if quote.discount_type == "percentage":
            discount = quote.discount_percentage / Decimal(100)
            quote.net_amount = quote_total * (1 - discount)
        elif quote.discount_type == "amount":
            quote.net_amount = quote_total - quote.discount_amount
        else:
            quote.net_amount = quote_total # Fallback without discount

        # ✅ Ensure we round to 2 decimal places
        quote.net_amount = max(quote.net_amount, Decimal(0)) #Avoid negative values

        # ✅ Update quote (subtotal, discounts fields and net amount)
        quote.save()

        # ✅ Ensure the value is saved correctly
        Quote.objects.filter(id=quote.id).update(net_amount=quote.net_amount)

        print(f"✅ Updated Quote {quote.id} Net Amount: {quote.net_amount}")  # Debugging log
    except Exception as e:
        print(f"⚠️ Error updating net amount for Quote {quote.id}: {str(e)}")

def update_opportunity_net_amount(opportunity):
    """Recalculate and update the opportunity's total amount from all related quotes."""
    try:
        # ✅ Add all the net_amounts of the quotes associated with the opportunity
        total_amount = opportunity.quotes.aggregate(
            total=Sum('net_amount')
        )['total']

        # ✅ Ensure we round to 2 decimal places
        opportunity.amount = Decimal(total_amount or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # ✅ Guardar la oportunidad actualizada
        opportunity.save()

        print(f"✅ Updated Opportunity {opportunity.id} Amount: {opportunity.amount}")
    except Exception as e:
        print(f"⚠️ Error updating amount for Opportunity {opportunity.id}: {str(e)}")
    
def extract_quote_line_updates(user_message):
    """Uses GPT to extract SKU, field, and new value for quote line updates."""

    allowed_fields_str = '", "'.join(["quantity", "discount_amount", "discount_percentage", "term"])

    prompt = f"""
    Extract structured update details from the following request.
    Return a JSON array with objects containing:
    - "sku" (string, required)
    - "name" (string, required)
    - "field" (one of: "{allowed_fields_str}")
    - "value" (string or number, new value)

    **Example Input & Output:**
    User: "Update AI-10 quantity to 600 and discount to 5%, then update AgentCPQ3 discount to $100."
    Response:
    [
        {{"sku": "AI-10", "name": "Null", "field": "quantity", "value": "600"}},
        {{"sku": "NoneAppear", "name": "AgentCPQ3", "field": "discount_percentage", "value": "5"}},
        {{"sku": "NoneAppear", "name": "Null", "field": "discount_amount", "value": "100"}}
    ]

    **Requirements:**
    - For discounts, if the user specifies a percentage (e.g., "15% discount"), return field: "discount_percentage" and value: "15". If the user specifies a dollar amount (e.g., "$150 off" or "150 dollars discount"), return field: "discount_amount" and value: "150". Always extract only the numeric value — remove symbols like % or $, and ignore words like "off", "discount", or "dollars".
    - Always normalize discount values to plain numbers.
    - If no SKUs are found in the message, return NoneAppear as SKU
    - If no name are found in the message, return Null as Name
    - If no field are found in the message, return NoneAppear as field
    - If no value are found in the message, return NoneAppear as value
    - If no discount are found in the message, return NoneAppear as value

    **Example Input with no SKU:**
    "modify the product quantity to 200 and price to 10"

    **Expected JSON Output:**
    [
        {{"sku": "NoneAppear", "name": "Null", "field": "quantity", "value": "49.99"}}
    ]

    **Example Input with no field:**
    "update AI-10 to 200"

    **Expected JSON Output:**
    [
        {{"sku": "AI-10", "name": "Null", "field": "NoneAppear", "value": "200"}}
    ]

    **Example Input with no value:**
    "Update AI-20 quantity"

    **Expected JSON Output:**
    [
        {{"sku": "AI-20", "name": "Null", "field": "quantity", "value": "NoneAppear"}}
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
            if isinstance(extracted_updates, list) and all("sku" in p and "field" in p and "value" in p for p in extracted_updates):
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

    
def extract_quote_line_skus(user_message):
    """Uses GPT to extract quote line name."""

    prompt = f"""
    Extract the SKU (product code) or name mentioned in the following user request. 

    Return only the SKU and name string inside a JSON object like this:
     [{{"sku": "<SKU_CODE>", "name": "Null"}}]

    **Rules:**
    - If no SKU is found in the message, return: {{"sku": "Null"}}
    - If no name is found in the message, return: {{"name": "Null"}}
    - Do NOT include explanations.
    - Do NOT wrap the result in Markdown or use triple backticks.
    - Return only a single JSON object.


    **Examples:**

    User: "Remove AI-CPQ-10 from the quote and remove ProductName1"
    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-10", "name": "Null"}},
        {{"sku": "Null", "name": "ProductName1"}}
    ]

    User: "Delete product with SKU AI-CPQ-55"
    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-55", "name": "Null"}}
    ]

    User: "Remove the product"
    **Expected JSON Output:**
    [
        {{"sku": "Null", "name": "Null"}}
    ]

    **IMPORTANT:** **Return a valid JSON array only of SKU and name. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract the SKU mentioned in the user's request."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_sku = json.loads(raw_response)
            if isinstance(extracted_sku, list) and all("sku" in p for p in extracted_sku):
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

def get_editable_quoteline_fields():
    editable_fields = []
    for field in QuoteLine._meta.fields:
        if (
            not isinstance(field, ForeignKey)  # No foreign keys
            and field.editable  # Only editable fields
            and field.name not in ["id", "total_price"]  # Not id or total_price
        ):
            editable_fields.append(field.name)
    return editable_fields

def extract_quote_name(user_message):
    """Extracts the quote name from user input."""
    import re
    match = re.search(r"\bQ-\d{4,}\b", user_message, re.IGNORECASE)
    return match.group(0) if match else None

def show_quote_details(user_message, session_data):
    """Fetches and formats quote details, including quote lines, based on user input or session data."""
    try:
        logging.info("🔄 Showing quote details...")

        # Looking for active quote
        quote = get_active_quote(user_message, session_data)

        # ⚠️ Verify if function return an error
        if isinstance(quote, dict) and "message" in quote:
            return quote

        # ✅ Fetch related quote lines
        quote_lines = QuoteLine.objects.filter(quote=quote)

        # ✅ Format the response
        quote_details = get_quote_details(quote)

        print(f"\n\nExpiration Date: {quote_details["expiration_date"]}")

        set_active_quote_to_session_data(session_data, quote)

        return {"message": "Here are the quote details:", "quote_details": quote_details, "hiddenMessage": "True"}
    
    except Quote.DoesNotExist:
        return {"message": "⚠️ Error: Quote not found. Please check the quote name."}
    
def delete_quote_line(user_message, session_data):
    """Deleting quote line item from quote"""
    response_message = ""
    try:
        # Looking for active quote
        quote = get_active_quote(user_message, session_data)

        # ⚠️ Verify if function return an error
        if isinstance(quote, dict) and "message" in quote:
            return quote
        
        logging.info(f"🔄 Deleting quote line item from quote {quote}...")

        extracted_sku = extract_quote_line_skus(user_message)

        if not extracted_sku:
            # ✅ Save quote in session data
            set_active_quote_to_session_data(session_data, quote)

            return {
                "message": "⚠️ Failed to extract SKUs or product names for removing the quote line item. Please try again or check your input."
            }
        
        for index, item in enumerate(extracted_sku, start=1):
        
            sku = item["sku"]
            name = item["name"]

            # Check if the product exists
            try:
                product = Product.objects.get(Q(sku=sku) | Q(sku=name) | Q(name=sku) | Q(name=name))
            except Product.DoesNotExist:
                response_message += f"⚠️ Product '{sku}/{name}' is not registered.<br>"
                continue

            sku = product.sku
            name = product.name

            print(f"\n\nQuote details: {sku} | {name}\n\n")
            
            # Check is quote line exists in active quote
            try:
                quote_line = QuoteLine.objects.get(quote=quote, product=product)
                quote_line.delete()

                response_message += f"✅ The quote line with product SKU '{product.sku}' was successfully deleted from quote '{quote.name}'.<br>"
                continue

            except QuoteLine.DoesNotExist:
                quote_line = None
                response_message += f"⚠️ The quote line with product SKU '{product.sku}' does not exist in quote {quote.name}.<br>"
                continue

    except Quote.DoesNotExist:
        return {
            "message": "⚠️ Error: Quote not found. Please check the quote name."
        }
    
    # ✅ Save quote in session data
    set_active_quote_to_session_data(session_data, quote)

    # ✅ Update quote (subtotal, discounts fields and net amount)
    quote.save()

    return {
        "message": response_message,
        "update_details": get_quote_details(quote),
        "temporaryMessage": True,
        "iterations": index
    }

def format_currency(value):
    """Formats a Decimal value into currency format with commas and two decimal places."""
    return f"{value:,.2f}"  # Example: 3,000.00 instead of 3000.0

def generate_quote_pdf(user_message, session_data):
    """Generates a sleek PDF document for the specified quote."""
    # Looking for active quote
    quote = get_active_quote(user_message, session_data)

    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        return quote
    
    try:
        # ✅ Fetch related quote lines
        quote_lines = QuoteLine.objects.filter(quote=quote)

        # ✅ Fetch related company
        company = Tenant.objects.first()

        # ✅ Fetch related quote document settings (template)
        template = QuoteDocumentSettings.objects.first()

        # ✅ Fetch related account
        account = quote.account

        # ✅ Generate file name
        last_doc = QuoteDocument.objects.filter(quote=quote).order_by('-version').first()
        next_version = (last_doc.version if last_doc else 0) + 1

        pdf_filename = f"Quote_{quote.name}_v{next_version}.pdf"
        pdf_path = os.path.join(settings.MEDIA_ROOT, "quote_documents", pdf_filename)

        # ✅ Create PDF in memory
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=letter)
        pdf.setTitle(f"Quote {quote.name}")
        CBLACK = "#000000"
        

        # MODERN TEMPLATE
        if template.template_style == 'modern':
            PCOLOR = company.primary_color
            SCOLOR = company.secondary_color
        elif template.template_style == 'classic':
            PCOLOR = CBLACK
            SCOLOR = CBLACK


        # ✅ Letterhead
        pdf.setFont("Helvetica", 8)
        pdf.drawString(20, 770, f"{datetime.now().strftime("%m/%d/%Y, %H:%M:%S")}")

        # ✅ Quote Header
        pdf.setFont("Helvetica-Bold", 26)
        pdf.setFillColor(HexColor(SCOLOR))
        pdf.drawString(50, 730, f"Quote: {quote.name}")
        pdf.setFillColor(HexColor(CBLACK))

        # ✅ Add Logo (Update path if needed)
        if template.show_company_logo:
            if company and company.logo:
                logo_path = company.logo.path
                if os.path.exists(logo_path):
                    pdf.drawImage(logo_path, 430, 710, width=150, height=60, preserveAspectRatio=True, mask='auto')

        # ------------------------------------
        pdf.setStrokeColor(HexColor(SCOLOR))
        pdf.setLineWidth(3)
        pdf.line(32, 700, 580, 700) 

        # ✅ Set Y and X position for Company Information
        y_position = 660
        x_position = 50
        company_count = 0
        pdf.setFont("Helvetica-Bold", 12)
        
        # ✅ Company Information
        if template.show_company_name and company.name:
            pdf.drawString(x_position, y_position, f"{company.name}")
            company_count += 1
            y_position -= 15

        # ✅ Company email with hyperlink
        if template.show_company_email and company.contact_email:
            pdf.setFillColor(HexColor("#888888"))
            x = x_position
            y = y_position
            email = company.contact_email
            pdf.drawString(x_position, y_position, email)
            pdf.linkURL(f"mailto:{email}", (x_position, y_position - 2, x + pdf.stringWidth(email), y + 10), relative=0)
            pdf.setFillColor(HexColor(CBLACK))
            company_count += 1
            y_position -= 15

        # ✅ Company addres
        if template.show_company_address and company.street_address and company.city and company.state:
            pdf.setFillColor(HexColor("#888888"))
            pdf.drawString(x_position, y_position, company.street_address)
            y_position -= 15
            pdf.drawString(x_position, y_position, f"{company.city}, {company.state}")
            pdf.setFillColor(HexColor(CBLACK))
            company_count += 1
            y_position -= 15
        
        # ✅ Company phone
        if template.show_company_phone and company.phone_number:
            pdf.setFillColor(HexColor("#888888"))
            pdf.drawString(x_position, y_position, f"Phone: {company.phone_number}")
            pdf.setFillColor(HexColor(CBLACK))
            company_count += 1
            y_position -= 15

        # ✅ Company domain
        if template.show_company_domain and company.domain:
            pdf.setFillColor(HexColor("#888888"))
            pdf.drawString(x_position, y_position, company.domain)
            pdf.setFillColor(HexColor(CBLACK))
            company_count += 1
            y_position -= 15

        # ✅ Set Y and X position for Account Information
        y_position = 660
        x_position = 350
        account_count = 0
    
        # ✅ Account Name
        if template.show_account_name and account.name:
            pdf.setFillColor(HexColor(CBLACK))
            pdf.drawString(x_position, y_position, "Account:")
            y_position -= 15
            pdf.drawString(x_position, y_position, account.name)
            y_position -= 15
            account_count += 1

        # ✅ Account Website
        if template.show_account_website and account.website:
            pdf.setFillColor(HexColor("#888888"))
            pdf.drawString(x_position, y_position, account.website)
            pdf.setFillColor(HexColor(CBLACK))
            y_position -= 15
            account_count += 1

        # ✅ Account Website
        if template.show_account_phone and account.phone:
            pdf.setFillColor(HexColor("#888888"))
            pdf.drawString(x_position, y_position, account.phone)
            pdf.setFillColor(HexColor(CBLACK))
            y_position -= 15
            account_count += 1

        # ✅ Set Y and X position for General Quote Information
        y_position = 660 - (max(company_count, account_count) * 15) - 30
        x_position = 350

        # ✅ Quote Opportunity Name
        if template.show_quote_opportunity and quote.opportunity.name:
            pdf.setFillColor(HexColor(CBLACK))
            pdf.drawString(x_position, y_position, quote.opportunity.name)
            y_position -= 15

        # ✅ Quote Status
        if template.show_quote_status and quote.status:
            pdf.setFillColor(HexColor(CBLACK))
            pdf.drawString(x_position, y_position, f"Status: {quote.status}")
            y_position -= 15

        # ✅ Quote Created Date
        if template.show_quote_created_at and quote.created_at:
            pdf.setFillColor(HexColor(CBLACK))
            pdf.drawString(x_position, y_position, f"Created at: {quote.created_at.strftime('%m/%d/%Y')}")
            y_position -= 15

        # ✅ Quote Expiration Date
        if template.show_quote_expires_at: #and quote.expiration_date:
            pdf.setFillColor(HexColor(CBLACK))
            pdf.drawString(x_position, y_position, f"Expiration Date: {quote.expiration_date.strftime('%m/%d/%Y')}")
            y_position -= 15

        # ✅ Quote Notes
        if template.show_quote_notes and quote.notes:
            x_position = 50
            lines_count = 15
            y_position -= 15
            line_spacing = 12
            left_margin = x_position + 5
            pdf.drawString(left_margin, y_position, f"Quote Notes:")
            # Pre settings and draw notes
            max_width = 500
            font_name = "Helvetica"
            font_size = 10
            pdf.setFont(font_name, font_size)

            lines = wrap_text(quote.notes, font_name, font_size, max_width, pdf)

            y_position -= 15
            new_page_bool = False

            for index, line in enumerate(lines, start=1):
                if y_position < 50:  # Si nos acercamos al final de la hoja
                    lines_count += 12 * index

                    pdf.setFillColor(HexColor(PCOLOR))
                    pdf.setLineWidth(1)
                    pdf.setStrokeColor(HexColor(PCOLOR))
                    pdf.rect(x_position, y_position, 510, lines_count, fill=False, stroke=True)

                    pdf.showPage()
                    y_position = letter[1] - 50  # Reinicia desde arriba con margen
                    pdf.setFont(font_name, font_size)
                    pdf.setFillColor(HexColor(CBLACK))

                    new_page_bool = True
                    lines_before_new_page = index
                    
                    lines_count = 15
                else:
                    pdf.drawString(left_margin, y_position, line)
                    y_position -= line_spacing
            
            #-----------------
            if new_page_bool:
                lines_count += line_spacing * (len(lines) - lines_before_new_page)
            else:
                lines_count += line_spacing * (len(lines) + 1)

            pdf.setFillColor(HexColor(PCOLOR))
            pdf.setLineWidth(1)
            pdf.setStrokeColor(HexColor(PCOLOR))
            pdf.rect(x_position, y_position, 510, lines_count, fill=False, stroke=True)

            # Set all up back again
            pdf.setFont("Helvetica-Bold", 12)
            pdf.setFillColor(HexColor(CBLACK))
        
        x_position = 50
        y_position -= 30
        font_name = "Helvetica-Bold"
        font_size = 12

        if y_position < 100:  # Si nos acercamos al final de la hoja
            pdf.showPage()
            y_position = letter[1] - 50  # Reinicia desde arriba con margen
            pdf.setFont(font_name, font_size)
            pdf.setFillColor(HexColor(CBLACK))

        # ✅ Products and Services
        if template.rendered_fields:
            pdf.drawString(x_position, y_position, "Products and Services")
            y_position -= 25

            # ✅ Table header Information
            pdf.setFont("Helvetica-Bold", 10)
            pdf.setFillColor(HexColor(CBLACK))
            column_spacing = 512 / len(template.rendered_fields)

            for index, field in enumerate(template.rendered_fields):
                column_x = x_position + index * column_spacing
                text_width = pdf.stringWidth(field, "Helvetica-Bold", 10)
                last_index = len(template.rendered_fields) - 1

                if field == "Product And SKU" and index == 0:
                    aligned_x = column_x + 2 
                elif index == 0:
                    aligned_x = column_x
                elif index == last_index:
                    aligned_x = column_x + column_spacing - text_width
                else:
                    aligned_x = column_x + (column_spacing - text_width) / 2

                pdf.drawString(aligned_x, y_position, field)
            
            y_position -= 15
            # ------------------------------------
            pdf.setStrokeColor(HexColor(SCOLOR))
            pdf.setLineWidth(2)
            pdf.line(50, y_position, 562, y_position) 
            y_position -= 27

            FIELD_MAP = {
                "Product And SKU": lambda line: f"{line.product_name} ({line.sku})" if line.sku else line.product_name,
                "Product": lambda line: line.product_name,
                "SKU": lambda line: line.sku,
                "Description": lambda line: line.description,
                "Quantity": lambda line: str(line.quantity),
                "Unit Price": lambda line: f"${line.unit_price:,.2f}",
                "Special Price": lambda line: f"${line.special_price:,.2f}",
                "Discount": lambda line: (
                    f"${line.discount_amount:,.2f}" if line.discount_type == "amount"
                    else f"{line.discount_percentage:.2f}%" if line.discount_type == "percentage"
                    else "---"
                ),
                "Subtotal": lambda line: f"${line.subtotal:,.2f}",
                "Total Price": lambda line: f"${line.total_price:,.2f}",
            }

            for line in quote.quote_lines.all():
                if y_position < 70:  # Si nos acercamos al final de la hoja
                    right_margin = 562
                    y_position += 15
                    pdf.setStrokeColor(HexColor(SCOLOR))
                    pdf.setLineWidth(2)
                    pdf.line(50, y_position, right_margin, y_position) 
                    pdf.showPage()
                    y_position = letter[1] - 50  # Reinicia desde arriba con margen

                    # ✅ Table header Information
                    pdf.setFont("Helvetica-Bold", 10)
                    pdf.setFillColor(HexColor(CBLACK))
                    column_spacing = 512 / len(template.rendered_fields)

                    for index, field in enumerate(template.rendered_fields):
                        column_x = x_position + index * column_spacing
                        text_width = pdf.stringWidth(field, "Helvetica-Bold", 10)
                        last_index = len(template.rendered_fields) - 1

                        if field == "Product And SKU" and index == 0:
                            aligned_x = column_x + 2 
                        elif index == 0:
                            aligned_x = column_x
                        elif index == last_index:
                            aligned_x = column_x + column_spacing - text_width
                        else:
                            aligned_x = column_x + (column_spacing - text_width) / 2

                        pdf.drawString(aligned_x, y_position, field)
                    
                    y_position -= 15
                    # ------------------------------------
                    pdf.setStrokeColor(HexColor(SCOLOR))
                    pdf.setLineWidth(2)
                    pdf.line(50, y_position, 562, y_position) 
                    y_position -= 27
            
                set_y_position = y_position
                for index, field_title in enumerate(template.rendered_fields):
                    column_x = x_position + index * column_spacing
                    last_index = len(template.rendered_fields) - 1

                    if field_title == "Product And SKU":
                        if index == 0:
                            aligned_x = column_x
                        else:
                            aligned_x = column_x + column_spacing / 2
                    else:
                        if index == 0:
                            aligned_x = column_x
                        elif index == last_index:
                            aligned_x = column_x + column_spacing - 1
                        else:
                            aligned_x = column_x + column_spacing / 2

                    if field_title == "Product And SKU":
                        sku = line.sku or ""
                        product = line.product_name or ""

                        max_width = column_spacing - 5 
                        sku_font_size = 10
                        product_font_size = 9

                        sku_text_width = pdf.stringWidth(sku, "Helvetica-Bold", sku_font_size)
                        if sku_text_width > max_width:
                            sku_font_size = max(6, int(sku_font_size * max_width / sku_text_width))

                        product_text_width = pdf.stringWidth(product, "Helvetica", product_font_size)
                        if product_text_width > max_width:
                            product_font_size = max(6, int(product_font_size * max_width / product_text_width))

                        if index == 0:
                            pdf.setFont("Helvetica-Bold", sku_font_size)
                            pdf.setFillColor(HexColor("#000000"))
                            pdf.drawString(column_x + 2, set_y_position, sku)
                            pdf.setFont("Helvetica", product_font_size)
                            pdf.setFillColor(HexColor("#666666"))  
                            pdf.drawString(column_x + 2, set_y_position - 10, product)
                        else:
                            pdf.setFont("Helvetica-Bold", sku_font_size)
                            pdf.setFillColor(HexColor("#000000"))
                            pdf.drawCentredString(aligned_x, set_y_position, sku)
                            pdf.setFont("Helvetica", product_font_size)
                            pdf.setFillColor(HexColor("#666666"))
                            pdf.drawCentredString(aligned_x, set_y_position - 10, product)

                    else:
                        value_func = FIELD_MAP.get(field_title, lambda l: "")
                        if field_title == "Total Price" and template.show_subscription_term and line.term is not None:
                            monthly_total = line.subtotal * line.quantity
                            text = f"${monthly_total:,.2f} /mo"
                        else:
                            text = value_func(line) or ""


                        if field_title == "Description":
                            max_font_size = 9
                            min_font_size = 8
                            font_name = "Helvetica"
                            max_width = column_spacing - 5
                            line_spacing = 10

                            is_short = template.line_description_detail_level == 'short'
                            max_lines = 3 if is_short else 100

                            font_size = max_font_size
                            wrapped_lines = []

                            while font_size >= min_font_size:
                                words = text.split()
                                lines = []
                                current_line = ""
                                for word in words:
                                    test_line = f"{current_line} {word}".strip()
                                    line_width = pdf.stringWidth(test_line, font_name, font_size)
                                    if line_width <= max_width:
                                        current_line = test_line
                                    else:
                                        lines.append(current_line)
                                        current_line = word
                                if current_line:
                                    lines.append(current_line)

                                wrapped_lines = lines
                                if not is_short or len(wrapped_lines) <= max_lines:
                                    break

                                font_size -= 1

                            if is_short and len(wrapped_lines) > max_lines:
                                wrapped_lines = wrapped_lines[:max_lines]
                                last_line = wrapped_lines[-1]
                                ellipsis = "..."
                                while pdf.stringWidth(last_line + ellipsis, font_name, font_size) > max_width and len(last_line) > 0:
                                    last_line = last_line[:-1]
                                wrapped_lines[-1] = last_line.strip() + ellipsis

                            start_y = set_y_position

                            pdf.setFont(font_name, font_size)
                            pdf.setFillColor(HexColor(CBLACK))
                            counter_lines = 0

                            for i, wrapped_line in enumerate(wrapped_lines):
                                counter_lines += 1
                                y = start_y - i * line_spacing
                                text_width = pdf.stringWidth(wrapped_line, font_name, font_size)
                                aligned_x = column_x + (column_spacing - text_width) / 2
                                pdf.drawString(aligned_x, y, wrapped_line)

                            y_position -= 5

                        else:
                            font_size = 9
                            text_width = pdf.stringWidth(text, "Helvetica", font_size)
                            if text_width > column_spacing - 5:
                                font_size = max(6, int(font_size * (column_spacing - 5) / text_width))

                            text_width = pdf.stringWidth(text, "Helvetica", font_size)
                            if index == 0:
                                aligned_x = column_x
                            elif index == last_index:
                                aligned_x = column_x + column_spacing - text_width
                            else:
                                aligned_x = column_x + (column_spacing - text_width) / 2

                            pdf.setFont("Helvetica", font_size)
                            pdf.setFillColor(HexColor("#000000"))
                            pdf.drawString(aligned_x, set_y_position, text)

                            if field_title == "Total Price" and template.show_line_discount and line.discount_type != "None":
                                set_y_position -= 13
                                pdf.setFillColor(HexColor("#666666"))

                                # Get discount text
                                discount_text = (
                                    f"after a {line.discount_percentage:.2f}% discount"
                                    if line.discount_type == "percentage"
                                    else f"after a ${line.discount_amount:,.2f} discount"
                                )

                                # Text's width
                                discount_text_width = pdf.stringWidth(discount_text, "Helvetica", font_size)

                                # Align depending last field
                                if index == last_index:
                                    discount_x = column_x + column_spacing - discount_text_width  # Right align
                                else:
                                    discount_x = column_x + (column_spacing - discount_text_width) / 2  # Centered

                                pdf.setFont("Helvetica", font_size)
                                pdf.drawString(discount_x, set_y_position, discount_text)

                            if field_title == "Total Price" and template.show_subscription_term and line.term is not None:
                                set_y_position -= 13
                                pdf.setFillColor(HexColor("#666666"))

                                # Get discount text
                                term_text = f"for {line.term} months"

                                term_text_width = pdf.stringWidth(term_text, "Helvetica", font_size)

                                if index == last_index:
                                    term_x = column_x + column_spacing - term_text_width 
                                else:
                                    term_x = column_x + (column_spacing - term_text_width) / 2 

                                pdf.setFont("Helvetica", font_size)
                                pdf.drawString(term_x, set_y_position, term_text)
                            
                            y_position -= 5

                y_position -= 30 

            # ------------------------------------
            right_margin = 562
            y_position += 15
            pdf.setStrokeColor(HexColor(SCOLOR))
            pdf.setLineWidth(2)
            pdf.line(50, y_position, right_margin, y_position)

            y_position -= 27

            if y_position < 100:  # Si nos acercamos al final de la hoja
                pdf.showPage()
                y_position = letter[1] - 50  # Reinicia desde arriba con margen
                pdf.setFont(font_name, font_size)
                pdf.setFillColor(HexColor(CBLACK))

            label_font = "Helvetica-Bold"
            label_size = 12
            value_font = "Helvetica"
            value_size = 10
            spacing = 100

            # === Subtotal ===
            subtotal_label = "Subtotal:"
            subtotal_value = f"${format_currency(quote.subtotal)}"

            subtotal_label_width = pdf.stringWidth(subtotal_label, label_font, label_size)
            subtotal_value_width = pdf.stringWidth(subtotal_value, value_font, value_size)

            start_x = right_margin - 150 - subtotal_label_width

            pdf.setFont(label_font, label_size)
            pdf.setFillColor(HexColor(CBLACK))
            #Render subtotal label
            pdf.setFont(label_font, label_size)
            pdf.drawString(start_x, y_position, subtotal_label)
            #Render subtotal value
            pdf.setFont(value_font, value_size)
            pdf.drawString(right_margin - subtotal_value_width, y_position, subtotal_value)

            y_position -= 30

            # === Discount ===
            discount_label = "Discount:"
            discount_value = f"{quote.discount_percentage:.2f}% (-{format_currency(quote.discount_amount)})"

            discount_label_width = pdf.stringWidth(discount_label, label_font, label_size)
            discount_value_width = pdf.stringWidth(discount_value, value_font, value_size)

            start_x = right_margin - 150 - discount_label_width

            pdf.setFont(label_font, label_size)
            pdf.setFillColor(HexColor(CBLACK))
            pdf.drawString(start_x, y_position, discount_label)

            pdf.setFont(value_font, value_size)
            pdf.setFillColor(red)
            pdf.drawString(right_margin - discount_value_width, y_position, discount_value)

            y_position -= 30

            # === Net Amount ===
            net_label = "Net Amount:"
            net_value = f"${format_currency(quote.net_amount)}"

            net_label_width = pdf.stringWidth(net_label, label_font, label_size)
            net_value_width = pdf.stringWidth(net_value, value_font, value_size)

            start_x = right_margin - 150 - net_label_width

            pdf.setFont(label_font, label_size)
            pdf.setFillColor(HexColor(CBLACK))
            pdf.drawString(start_x, y_position, net_label)

            pdf.setFont(value_font, value_size)
            pdf.drawString(right_margin - net_value_width, y_position, net_value)

            y_position -= 30
            x_position = 50

        

        if template.terms_and_conditions:
            if y_position < 50:  # Si nos acercamos al final de la hoja
                pdf.showPage()
                y_position = letter[1] - 50  # Reinicia desde arriba con margen
            #Terms and conditions
            tac_value = "Terms And Conditions"
            value_font = "Helvetica-Bold"
            value_size = 12
            terms_and_conditions_width = pdf.stringWidth(tac_value, value_font, value_size)
            
            left_margin = 50
            right_margin = 50
            usable_width = letter[0] - left_margin - right_margin  # 612 - 100 = 512

            font_name = "Helvetica"
            font_size = 10
            line_spacing = 12

            # Título
            pdf.setFont("Helvetica-Bold", 12)
            pdf.setFillColor(HexColor(CBLACK))
            pdf.drawString(left_margin, y_position, "Terms And Conditions")
            y_position -= 15

            # Texto
            pdf.setFont(font_name, font_size)
            pdf.setFillColor(HexColor(CBLACK))

            lines = wrap_text(template.terms_and_conditions, font_name, font_size, usable_width, pdf)

            for line in lines:
                if y_position < 50:  # Si nos acercamos al final de la hoja
                    pdf.showPage()
                    y_position = letter[1] - 50  # Reinicia desde arriba con margen
                    pdf.setFont(font_name, font_size)
                    pdf.setFillColor(HexColor(CBLACK))
                
                pdf.drawString(left_margin, y_position, line)
                y_position -= line_spacing
            
            y_position -= 18
            
        #Show sign
        x_position = 50
        if template.show_sign:
            if y_position < 160:  # Si nos acercamos al final de la hoja
                pdf.showPage()
                y_position = letter[1] - 50  # Reinicia desde arriba con margen

            pdf.setFont("Helvetica-Bold", 12)
            pdf.setFillColor(HexColor(CBLACK))
            pdf.drawString(x_position, y_position, "Signature")

            y_position -= 40

            pdf.setStrokeColor(HexColor(CBLACK))
            pdf.setLineWidth(1)
            line_width = 150
            spacing = 50
            pdf.line(x_position, y_position, x_position + line_width, y_position)
            pdf.line(x_position + line_width + spacing, y_position, x_position + line_width + spacing + line_width, y_position)

            y_position -= 15
            pdf.setFont("Helvetica", 10)
            pdf.setFillColor(HexColor(CBLACK))
            pdf.drawString(x_position, y_position, "Sign")
            pdf.drawString(x_position + line_width + spacing, y_position, "Date")

            y_position -= 40

            pdf.setStrokeColor(HexColor(CBLACK))
            pdf.setLineWidth(1)
            line_width = 150
            spacing = 50
            pdf.line(x_position, y_position, x_position + line_width, y_position)

            y_position -= 15
            pdf.setFont("Helvetica", 10)
            pdf.setFillColor(HexColor(CBLACK))
            pdf.drawString(x_position, y_position, "Name")
                

        # ✅ Save PDF to buffer
        pdf.showPage()
        pdf.save()

        # ✅ Ensure target folder exists before writing the PDF
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)

        # ✅ Save the buffer content to the file
        with open(pdf_path, "wb") as f:
            f.write(buffer.getvalue())


        # ✅ Save the buffer content to the file
        with open(pdf_path, "wb") as f:
            f.write(buffer.getvalue())

        buffer.close()

        # ✅ Save record in QuoteDocument
        QuoteDocument.objects.create(
            quote=quote,
            version=next_version,
            name=pdf_filename,
            file=f"quote_documents/{pdf_filename}",
            generated_by="system"
        )

        # ✅ Save quote in session data
        set_active_quote_to_session_data(session_data, quote)

        return {
            "message": f"📄 Quote PDF (v{next_version}) generated successfully!",
            "download_url": f"{settings.MEDIA_URL}quote_documents/{pdf_filename}",
            "document_version": next_version,
            "hiddenMessage": True
            }

    except Quote.DoesNotExist:
        return {"message": "⚠️ Error: Quote not found."}
    except Exception as e:
        return {"message": f"⚠️ Error generating PDF: {str(e)}"}
    
    
def wrap_text(text, font_name, font_size, max_width, pdf_canvas):
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        if pdf_canvas.stringWidth(test_line, font_name, font_size) <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    return lines

def set_active_quote_to_session_data(session_data, quote):
    session_data["active_quote"] = {
        "quote_id": quote.id,
        "quote_name": quote.name,
        "account": quote.account.name if quote.account else "N/A",
        "opportunity": quote.opportunity.name if quote.opportunity else "N/A"
    }
    
def get_active_quote(user_message, session_data):
    logging.info("🔄 Getting active quote.")

    # Looking for active quote
    quote_name = extract_quote_name(user_message)

    if not quote_name:
        active_quote = session_data.get('active_quote')

        if not active_quote or "quote_id" not in active_quote:
            logging.info("🔎 No active quote found in session either in user message.")
            return {"message": "⚠️ No active quote found. Please provide a quote name (e.g., Q-0019) or create a new quote first."}
        else:
            # ✅ Retrieve quote using session data
            try:
                quote = Quote.objects.get(id=active_quote['quote_id'])
                logging.info(f"🟢 Found and set active quote from session: {quote.name}")
                return quote
            except Quote.DoesNotExist:
                return {"message": f"⚠️ Session references a non-existent quote. Please provide a valid quote name."}
    else:
        # ✅ Search for the quote by name
        try:
            quote = Quote.objects.get(name=quote_name)
            logging.info(f"🟢 Found and set active quote: {quote.name}")
            return quote
        except Quote.DoesNotExist:
            return {"message": f"⚠️ Quote `{quote_name}` not found. Please ensure it exists or create a new one."}
        
def delete_quote(user_message, session_data):
    """Deleting Quote"""
    response_message = ""
    try:
        #Looking for active quote
        quote = get_active_quote(user_message, session_data)

        # ⚠️ Verify if function return an error
        if isinstance(quote, dict) and "message" in quote:
            return quote
        
        logging.info(f"Deleting quote with name: {quote.name}...")

        #If quote status is not in Draft Status
        #print(f"\n\nQuote: {quote.__dict__}\n\n")
        if quote.status == "Draft":
            if session_data["pending_action"] == "delete_quote_confirmed":
                quote_name = quote.name  # Save quote name before to delete
                quote.delete()

                return {
                    "message": f"✅ Quote '{quote_name}' has been successfully deleted."
                }
            else:
                session_data["pending_action"] = "delete_quote_confirmation"
                return{
                    "message": f"⚠️ Are you sure you want to delete the quote <strong>{quote.name}</strong>? (Yes/No)"
                }
        else:
            return {
                "message": f"⚠️ Quote '{quote.name}' can not be deleted because it's status is '{quote.status}'. Only 'Draft' quotes can be deleted."
            }   

    except Quote.DoesNotExist:
        return {
            "message": "⚠️ Quote doesn't exist."
        }
    
    except Exception as e:
        logging.exception("An unexpected error occurred while deleting the quote.")
        return {
            "message": f"❌ An unexpected error occurred: {str(e)}"
        }
    
def update_quote_notes(user_message, session_data):
    """Updating Quote Notes"""
    try:
        #Looking for active quote
        quote = get_active_quote(user_message, session_data)

        # ⚠️ Verify if function return an error
        if isinstance(quote, dict) and "message" in quote:
            return quote
        
        logging.info(f"updating notes for quote: {quote.name}...")

        extracted_notes = get_quote_notes_details(user_message)

        if not extracted_notes:
            # ✅ Save quote in session data
            set_active_quote_to_session_data(session_data, quote)
            
            return {
                "message": "⚠️ Sorry, I couldn't recognize a quote note from your message."
            }
        
        for index, item in enumerate(extracted_notes, start=1):
            notes = item['notes']

            if not isinstance(notes, str) or not notes.strip():
                return {
                    "message": "⚠️ Sorry, an error occurred. I couldn't extract a valid note from your message. Please try again or modify your input."
                }

            if notes is None or notes == "Null":
                return {
                    "message": "⚠️ Sorry, an error occurred. I couldn't extract a quote note from your message. Please try again or modify your input."
                }
            
            if quote.notes != notes:
                try:
                    quote.notes = notes
                    quote.save()
                except Exception as e:
                    return {
                        "message": "⚠️ An error occurred while trying to save the notes to the quote. Please try again."
                    }
                
            return {
                "message": "✅ Quote notes have been successfully updated."
            }
    except Quote.DoesNotExist:
        return {
            "message": "⚠️ Quote doesn't exist."
        }
    except Exception as e:
        logging.exception("An unexpected error occurred while showing the quote.")
        return {
            "message": f"❌ An unexpected error occurred: {str(e)}"
        }
    
    
def get_quote_notes_details(user_message):
    """Uses GPT to extract quote notes."""

    prompt = f"""
    Extract the quote notes in the following user request.

    Return only the text of notes inside a JSON object like this:
    [{{"notes": "This is a note."}}]

    "Look for phrases such as:
    - 'quote notes to:'
    - 'quote note should be'
    - 'set the note to'
    - 'make the quote note:'"

    **Rules:**
    - If no notes are found in the message, return Null as notes.

    **Examples:**

    User: "Update quote notes to: This is a simple note for this quote."
    **Expected JSON Output:**
    [
        {{"notes": "This is a symple notes for this quote."}}
    ]

    User: "Change the quote notes to This is a symple notes for this quote."
    **Expected JSON Output:**
    [
        {{"notes": "This is a symple notes for this quote."}}
    ]
    **IMPORTANT:** **Return a valid JSON array only of notes. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Extract the notes mentioned in the user's request."},
                {"role": "user", "content": prompt}
            ]
        )

        # ✅ Extract raw response
        raw_response = response.choices[0].message.content.strip()
        logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

        # ✅ Ensure valid JSON response
        try:
            extracted_sku = json.loads(raw_response)
            if isinstance(extracted_sku, list) and all("notes" in p for p in extracted_sku):
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

def show_quote_notes(user_message, session_data):
    """Showing Quote Notes"""
    response_message = ""
    try:
        #Looking for active quote
        quote = get_active_quote(user_message, session_data)

        # ⚠️ Verify if function return an error
        if isinstance(quote, dict) and "message" in quote:
            return quote
        
        logging.info(f"Showing notes for quote: {quote.name}...")

        notes = quote.notes

        if notes is None:
            msg = "📝 There are no notes on the current quote. You can add or update it by typing: “Update quote notes to: your message”."
            return {
                "message": msg
            }
        
        msg = f"<b>Quote Notes:</b><br><br>{notes}"
        
        return {
            "message": msg#,
            #"quote_details": get_quote_details(quote),
            #"quote_notes": quote.notes,
            #"hiddenMessage": True
        }

    except Quote.DoesNotExist:
        return {
            "message": "⚠️ Quote doesn't exist."
        }
    
    except Exception as e:
        logging.exception("An unexpected error occurred while showing the quote.")
        return {
            "message": f"❌ An unexpected error occurred: {str(e)}"
        }
    

def get_quote_details(quote):

    return {
        "quote_id": quote.id,
        "quote_name": quote.name,
        "subtotal": str(quote.subtotal),
        "net_amount": str(quote.net_amount),
        "status": quote.status,
        "account": quote.account.name if quote.account else "N/A",
        "opportunity": quote.opportunity.name if quote.opportunity else "N/A",
        "created_at": quote.created_at.isoformat() if quote.created_at else '',
        "expiration_date": quote.expiration_date.isoformat() if quote.expiration_date else '',
        "discount_type": str(quote.discount_type),
        "discount_amount": str(quote.discount_amount),
        "discount_percentage": str(quote.discount_percentage),
        "line_items": [
            {
                "id": ql.id,
                "product": ql.product.name,
                "sku": ql.product.sku,
                "quantity": ql.quantity,
                "unit_price": str(ql.unit_price),
                "total_price": str(ql.total_price),
                "discount_type": ql.discount_type,
                "discount_percentage": str(f"{ql.discount_percentage}%" if ql.discount_percentage else "0%"),
                "discount_amount": str(f"${ql.discount_amount}" if ql.discount_amount else "$0"),
                "is_subscription": ql.is_subscription,
                "term": ql.term,
            }
            for ql in QuoteLine.objects.filter(quote=quote)
        ]
    }


def build_temp_quote_line(quote, product, quantity, discount_type, discount_amount, term):
    """
    Construye una instancia temporal de QuoteLine sin guardarla en DB.
    Se usa para validar reglas antes de crearla.
    """
    temp_line = QuoteLine(
        quote=quote,
        product=product,
        quantity=quantity,
        discount_type=discount_type,
        discount_percentage=discount_amount if discount_type == "percentage" else 0,
        discount_amount=discount_amount if discount_type == "amount" else 0,
        unit_price=product.price,
        is_subscription=product.is_subscription,
        term=term
    )

    if not temp_line.product_name:
        temp_line.product_name = product.name
    if not temp_line.sku:
        temp_line.sku = product.sku

    # Aplica los cálculos de descuento, subtotal y total
    temp_line.update_discount_fields()
    temp_line.update_subtotal()
    temp_line.update_total_price()

    return temp_line