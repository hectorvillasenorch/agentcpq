from django.db.models import Sum, F
import json
import os
import openai
import logging
import re
import locale
from dotenv import load_dotenv
from cpq.models import Quote, Account, Opportunity, QuoteLine, Product, QuoteDocument, Tenant
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from django.http import FileResponse
from django.conf import settings
from reportlab.lib.colors import HexColor
from django.http import JsonResponse
from django.db import models
from agents.approvals_agent import get_approval_status
from django.db.models import Max
from django.db.models import Q
from django.forms.models import model_to_dict
from django.db.models import ForeignKey
from datetime import datetime


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
        "ApplyQuoteLineDiscount": apply_discount_to_quote_line,
        "ApplyQuoteDiscount": apply_discount_to_quote,
        "DeleteQuoteLine": delete_quote_line,
        "DeleteQuote": delete_quote,
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
                product = Product.objects.get(Q(sku=sku) | Q(name=name))
            except Product.DoesNotExist:
                logging.warning(f"⚠️ Product {sku} not found. Skipping...")
                response_message += f"⚠️ Product {sku} not found. Skipping...<br>"
                continue  # Skip this product and move to the next

            # ✅ Ensure proper rounding for calculations
            unit_price = Decimal(product.price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            logging.info(f"=>>>>>>>>>>>>>>>>>>>> Unit Price: {unit_price}")
            logging.info(f"=>>>>>>>>>>>>>>>>>>>> Quantity: {quantity}")


            if discount_type == "percentage":
                # ✅ Create Quote Line Item for discount percentage
                quote_line = QuoteLine.objects.create(
                    quote=quote,
                    product=product,
                    quantity=quantity,
                    unit_price=unit_price,
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
                    discount_type="None",
                    discount_amount=Decimal("0").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    discount_percentage=Decimal("0").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                )


            # ✅ Force saving and reloading from DB to verify
            quote_line.refresh_from_db()
            logging.info(f"=>>>>>>>>>>>>>>>>>>>> Saved Total Price in DB: {quote_line.total_price}")


            
            if discount_type == "percentage":
                added_products.append(f"{quantity}x {sku} with {discount_value}% discount.")
                response_message += f"✅ Added {quantity}x {sku} to quote {quote.name} with a {discount_value}% discount.<br>"
            elif discount_type == "amount":
                added_products.append(f"{quantity}x {sku} with ${discount_value} discount.")
                response_message += f"✅ Added {quantity}x {sku} to quote {quote.name} with a ${discount_value} discount.<br>"
            else:
                added_products.append(f"{quantity}x {sku}.")
                response_message += f"✅ Added {quantity}x {sku} to quote {quote.name}.<br>"


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

    for index, product_data in enumerate(extracted_products, start=1):
        sku = product_data.get("sku")
        quantity = product_data.get("quantity", 1)
        name = product_data.get("name", "None")
        discount_type = product_data.get("discount_type", 0)
        discount_amount = product_data.get("discount_amount", 0)

        # ✅ Validate product exists
        product = None

        if sku and sku != "Null":
            try:
                product = Product.objects.get(sku=sku)
            except Product.DoesNotExist:
                msg = f"⚠️ Product {index} (SKU: {sku}) not found. Trying to find by name...<br>"
                logging.warning(msg)

        if not product and name and name != "Null":
            try:
                product = Product.objects.get(name__iexact=name)
            except Product.DoesNotExist:
                msg = f"⚠️ Product {index} (Name: {name}) not found. Skipping...<br><br>"
                response_message += msg
                logging.warning(msg)
                continue

        if not product:
            msg = f"⚠️ Product '{sku}' could not be identified by SKU or name. Skipping...<br>"
            response_message += msg
            logging.warning(msg)
            continue

        # Descriptive prefix for messages
        product_label = f"Product {index} ({name if name != 'Null' else sku})"

        if int(quantity) <= 0:
            response_message += f"⚠️ {product_label}: Quantity cannot be less than or equal to 0. Please enter a valid quantity.<br><br>"
            continue

        if float(discount_amount) < 0:
            response_message += f"⚠️ {product_label}: Discount cannot be less than 0. Please enter a valid discount.<br><br>"
            continue


        # ✅ Check if product already exists in the quote
        existing_line = QuoteLine.objects.filter(quote=quote, product=product).first()

        if existing_line:
            logging.info(f"🔁 Product `{sku}` already in quote. Updating instead of creating.")

            new_quantity = existing_line.quantity + quantity

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

            user_message = f"Update Quote Line: {json.dumps(update_payload)}"

            
            response = update_quote_line(user_message, session_data)

            if (
                response.get("message") == "✅ Quote line(s) updated successfully." and
                "quote_details" in response and
                "line_items" in response["quote_details"]
            ):
                if discount_type == "percentage":
                    added_products.append(f"{quantity}x `{sku}` with {discount_amount}% discount")
                elif discount_type == "amount":
                    added_products.append(f"{quantity}x `{sku}` with ${discount_amount} discount")
                else:
                    added_products.append(f"{quantity}x `{sku}`")
            else:
                response_message+= "⚠️ Error: While updating quote line {sku}.<br><br>"
                logging.warning("⚠️ Update Failed")


            # ✅ Refresh quote to get new net_amount from database
            quote.refresh_from_db()
            existing_line.refresh_from_db()

            continue
        
        # Add product where quote line hasn't been added
        # ✅ Create Quote Line Item
        
        if discount_type == "percentage":
            quote_line = QuoteLine.objects.create(
                quote=quote,
                product=product,
                quantity=quantity,
                discount_type="percentage",
                discount_percentage=discount_amount,
                discount_amount=0
            )
            added_products.append(f"{quantity}x `{sku}` with {discount_amount}% discount")
        elif discount_type == "amount":
            quote_line = QuoteLine.objects.create(
                quote=quote,
                product=product,
                quantity=quantity,
                discount_type="amount",
                discount_amount=discount_amount,
                discount_percentage=0
            )
            added_products.append(f"{quantity}x `{sku}` with ${discount_amount} discount")
        else:
            quote_line = QuoteLine.objects.create(
                quote=quote,
                product=product,
                quantity=quantity,
                discount_type="None",
                discount_amount=0,
                discount_percentage=0
            )
            added_products.append(f"{quantity}x `{sku}`")

        # ✅ Force saving and reloading from DB to verify
        quote_line.refresh_from_db()
        logging.info(f"=>>>>>>>>>>>>>>>>>>>> Saved Total Price in DB: {quote_line.total_price}")

        #response_message += "✅ Added product successfully.<br><br>"
        continue

    #If AI Model indetify a product but it does not exist
    if not added_products:
        return {
            "message": "⚠️ Error: The product does not exist or you did not specify one. Please specify SKU, quantity, and discount for each product. <br> E"
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
        discount = discount_data.get("discount", 0)

        #If LLM did not find a SKU
        if sku == "NoneAppear":
            return {
                "message": "⚠️ Error: No SKU was detected in your request. Please specify the product code(s) to apply the discount."
            }
        
        #If LLM did not find a discount percent
        if discount == -1:
            return {
                "message": "⚠️ Error: No discount was detected in your request. Please specify the discount percentage to apply."
            }

        # ✅ Validate product exists
        product = None
        try:
            product = Product.objects.get(sku=sku)
        except Product.DoesNotExist:
            response_message += f"⚠️ Error: Product `{sku}` does not exist in the catalog.<br>"
            logging.warning(f"⚠️ Product `{sku}` not found. Skipping...")
            continue  # Skip this product and move to the next

        # ✅ Check if product already exists in the quote
        existing_line = QuoteLine.objects.filter(quote=quote, product=product).first()

        if not existing_line:
            response_message += f"⚠️ Error: Product `{sku}` exists, but is not part of quote `{quote.name}`.<br>"
            continue
        
        logging.info(f"🔁 Product `{sku}` is already in quote. Applying a discount.")

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
            added_discounts.append(f"`{sku}` added/updated with {discount}% discount")
    
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

    **Instructions for discounts:**
    - Use `"percentage"` for `discount_type` if the user specifies a percentage (e.g., "15%", "15 percent").
    - Use `"amount"` for `discount_type` if the user specifies a fixed amount (e.g., "$15", "15 dollars", "15 USD").
    - Extract the numeric part and set it as `discount_amount` (e.g., "15%" → 15, "$15" → 15).
    - If no discount is mentioned, set `"discount_type": "None"` and `"discount_amount": "0"`.

    **Example Input:** 
    "Add AI-CPQ-001 x 5 with 10% discount, Agency PQ Solo x 2 with $20 discount, and AI-CPQ-004 x 10."

    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-001", "name": "Null", "quantity": "5", "discount_type": "percentage", "discount_amount": "10"}},
        {{"sku": "Null", "name": "Agency PQ Solo", "quantity": "2", "discount_type": "amount", "discount_amount": "20"}},
        {{"sku": "AI-CPQ-004", "name": "Null", "quantity": "1", "discount_type": "None", "discount_amount": "0"}}
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
    - discount (integer, percentage, default 0 if not specified)

    If no SKUs are found in the message, return NoneAppear as SKU]
    If no discount are found in the message, return -1 as discount]

    **Example Input:**
    "Apply 20% discount to AI-CPQ-001 and 10% off AI-CPQ-002. Also give 15% discount on AI-CPQ-003."

    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-001", "discount": 20}},
        {{"sku": "AI-CPQ-002", "discount": 10}},
        {{"sku": "AI-CPQ-003", "discount": 15}}
    ]

    **Example Input with no SKU:**
    "Apply a 50% discount."

    **Expected JSON Output:**
    [
        {{"sku": "NoneAppear", "discount": 50}}
    ]

    **Example Input with no discount:**
    "Apply a discount to AI-CPQ-001."

    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-001", "discount": -1}}
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

    For discounts:
    - If the user specifies a percentage discount (e.g. "15%"), set discount_type to "percentage" and discount_value to the numeric value (e.g. "15").
    - If the user specifies a discount in dollars, with symbols or the word "dollar(s)" (e.g. "$100" or "100 dollars"), set discount_type to "amount" and discount_value to the numeric amount (e.g. "100").
    - If no discount is specified, set discount_type to "None" and discount_value to "0".

    Return a JSON object with these keys:
    {{"account": "", "opportunity": "", "products": [{{"sku": "", "name": "", "quantity": "", "discount_type": "", "discount_value": ""}}], "start_date": "", "end_date": ""}}.

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
                "message": "⚠️ GPT did not work well."
            }

        # Check if exist the product and any (sku, field or value) is NoneAppear
        response_message_alerts = ""
        response = None
        for index, item in enumerate(extracted_updates, start=1):

            field_labels = {
                "quantity": "Quantity",
                "discount_percentage": "Discount Percentage",
                "discount_amount": "Discount Amount",
            }

            item_field = field_labels.get(item["field"], item["field"].capitalize())

            #print(f"\n\nItem : {item}")
            show_details_message = f"<b>🔄 <u>Update Request #{index} in quote {quote.name}</u> 🔄</b><br>"
            show_details_message += f"🔢 SKU: {item['sku']}<br>"
            show_details_message += f"🏷️ Field: {item_field}<br>"
            show_details_message += f"✏️ Value: {item['value']}<br><br>"

            # Does the product exist?
            try:
                product = Product.objects.get(sku=item['sku'])
            except Product.DoesNotExist:
                response_message_alerts += show_details_message
                response_message_alerts += f"⚠️ Error: The product with SKU \"{item['sku']}\" was not found in the database.<br><br>"
                continue

            #Validate if product exist in actual quote line item
            quote_line = QuoteLine.objects.filter(quote=quote, product__sku=item['sku']).first()
            if not quote_line:
                response_message_alerts += show_details_message
                response_message_alerts += f"⚠️ Error: The product with SKU \"{item['sku']}\" is not in the current quote.<br><br>"
                continue

            # Add quote_line_id to item
            item['quote_line_id'] = quote_line.id

            # General validations
            if item['sku'] == 'NoneAppear':
                response_message_alerts += show_details_message
                response_message_alerts += f"⚠️ Error: No SKU was detected in your request. Please specify the product code(s) to update.<br><br>"
                continue

            if item['field'] == 'NoneAppear':
                response_message_alerts += show_details_message
                response_message_alerts += f"⚠️ Error: No field to update was detected in your request. Please specify which attribute (e.g., quantity or discount) you want to modify.<br><br>"
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
                        response_message_alerts += f"⚠️ Error: The value for SKU \"{item['sku']}\" cannot be less than 0. Please provide a valid number.<br><br>"
                        continue
                except (InvalidOperation, ValueError, TypeError):
                    response_message_alerts += show_details_message
                    response_message_alerts += f"⚠️ Error: The value \"{item['value']}\" is not a valid number. Please enter a valid numeric value.<br><br>"
                    continue

            response_message_alerts += show_details_message

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

    allowed_fields_str = '", "'.join(["quantity", "discount_amount", "discount_percentage"])

    prompt = f"""
    Extract structured update details from the following request.
    Return a JSON array with objects containing:
    - "sku" (string, required)
    - "field" (one of: "{allowed_fields_str}")
    - "value" (string or number, new value)

    **Example Input & Output:**
    User: "Update AI-10 quantity to 600 and discount to 5%, then update AIACPQ-003 discount to $100."
    Response:
    [
        {{"sku": "AI-10", "field": "quantity", "value": "600"}},
        {{"sku": "AI-10", "field": "discount_percentage", "value": "5"}},
        {{"sku": "AIACPQ-003", "field": "discount_amount", "value": "100"}}
    ]

    **Requirements:**
    - For discounts, if the user specifies a percentage (e.g., "15% discount"), return field: "discount_percentage" and value: "15". If the user specifies a dollar amount (e.g., "$150 off" or "150 dollars discount"), return field: "discount_amount" and value: "150". Always extract only the numeric value — remove symbols like % or $, and ignore words like "off", "discount", or "dollars".
    - Always normalize discount values to plain numbers.
    - If no SKUs are found in the message, return NoneAppear as SKU
    - If no field are found in the message, return NoneAppear as field
    - If no value are found in the message, return NoneAppear as value
    - If no discount are found in the message, return NoneAppear as value

    **Example Input with no SKU:**
    "modify the product quantity to 200 and price to 10"

    **Expected JSON Output:**
    [
        {{"sku": "NoneAppear", "field": "quantity", "value": "49.99"}}
    ]

    **Example Input with no field:**
    "update AI-10 to 200"

    **Expected JSON Output:**
    [
        {{"sku": "AI-10", "field": "NoneAppear", "value": "200"}}
    ]

    **Example Input with no value:**
    "Update AI-20 quantity"

    **Expected JSON Output:**
    [
        {{"sku": "AI-20", "field": "quantity", "value": "NoneAppear"}}
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
    Extract the SKU (product code) mentioned in the following user request. 

    Return only the SKU string inside a JSON object like this:
     [{{"sku": "<SKU_CODE>"}}]

    **Rules:**
    - If no SKU is found in the message, return: {{"sku": "Null"}}
    - Do NOT include explanations.
    - Do NOT wrap the result in Markdown or use triple backticks.
    - Return only a single JSON object.


    **Examples:**

    User: "Remove AI-CPQ-10 from the quote and remove AI-CPQ-02"
    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-10"}},
        {{"sku": "AI-CPQ-02"}}
    ]

    User: "Delete product with SKU AI-CPQ-55"
    **Expected JSON Output:**
    [
        {{"sku": "AI-CPQ-55"}}
    ]

    User: "Remove the product"
    **Expected JSON Output:**
    [
        {{"sku": "NoneAppear"}}
    ]

    **IMPORTANT:** **Return a valid JSON array only of SKU. Do not include explanations, and do not format the response as Markdown (no triple backticks or ```json).**

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
    match = re.search(r"\bQ-\d{4,}\b", user_message)
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
                "message": "⚠️ GPT did not work well."
            }
        
        for index, item in enumerate(extracted_sku, start=1):
        
            sku = item["sku"]
            print(f"\n\n SKU: {sku}\n")

            # Check if the product exists
            try:
                product = Product.objects.get(sku=sku)
            except Product.DoesNotExist:
                response_message += f"⚠️ Product with SKU '{sku}' is not registered.<br>"
                continue
            
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
    try:
        # Looking for active quote
        quote = get_active_quote(user_message, session_data)

        print(f"\n\nSession data === : {session_data}\n\n")

        # ⚠️ Verify if function return an error
        if isinstance(quote, dict) and "message" in quote:
            return quote

        # ✅ Fetch related quote lines
        quote_lines = QuoteLine.objects.filter(quote=quote)

        # ✅ Fetch related company
        company = Tenant.objects.first()

        # ✅ Generate file name
        last_doc = QuoteDocument.objects.filter(quote=quote).order_by('-version').first()
        next_version = (last_doc.version if last_doc else 0) + 1

        pdf_filename = f"Quote_{quote.name}_v{next_version}.pdf"
        pdf_path = os.path.join(settings.MEDIA_ROOT, "quote_documents", pdf_filename)

        # ✅ Create PDF in memory
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=letter)
        pdf.setTitle(f"Quote {quote.name}")

        # ✅ Add Logo (Update path if needed)
        if company and company.logo:
            logo_path = company.logo.path
            if os.path.exists(logo_path):
                pdf.drawImage(logo_path, 50, 680, width=150, height=60, preserveAspectRatio=True, mask='auto')

        # ✅ Quote Header
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(400, 750, f"Quote: {quote.name}")

        # ✅ Letterhead
        pdf.setFont("Helvetica", 8)
        pdf.drawString(20, 770, f"{datetime.now().strftime("%m/%d/%Y, %H:%M:%S")}")

        # ✅ Company & Quote Information
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(50, 660, f"{company.name}")
        pdf.setFont("Helvetica", 12)

        # ✅ Company email with hyperlink
        pdf.setFillColor(HexColor("#888888"))
        x = 50
        y = 645
        email = company.contact_email
        pdf.drawString(x, y, email)
        pdf.linkURL(f"mailto:{email}", (x, y - 2, x + pdf.stringWidth(email), y + 10), relative=0)
        pdf.setFillColor(HexColor("#000000"))
    
        # ✅ Account Information
        pdf.drawString(350, 660, f"Account: {quote.account.name if quote.account else 'N/A'}")
        pdf.drawString(350, 640, f"Opportunity: {quote.opportunity.name if quote.opportunity else 'N/A'}")
        pdf.drawString(350, 620, f"Status: {quote.status}")
        pdf.drawString(350, 600, f"Quote Created At: {quote.created_at.strftime('%m/%d/%Y, %H:%M:%S')}")
        pdf.drawString(350, 580, f"Quote Expires At: {quote.expiration_date}")

        # ✅ Table header Information

        pdf.setFillColor(HexColor("#5c5c5c"))
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
    

def get_quote_details(quote):

    return {
        "quote_id": quote.id,
        "quote_name": quote.name,
        "subtotal": str(quote.subtotal),
        "net_amount": str(quote.net_amount),
        "status": quote.status,
        "account": quote.account.name if quote.account else "N/A",
        "opportunity": quote.opportunity.name if quote.opportunity else "N/A",
        "created_at": quote.created_at.isoformat(),
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
