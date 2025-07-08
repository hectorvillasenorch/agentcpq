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
# LLM Utils
from .utils.quote_agent.llm_helpers import extract_quote_details, extract_product_details, extract_quote_line_updates, extract_quote_line_items_to_delete, extract_quote_level_discount
from .utils.quote_agent.llm_helpers import extract_quote_updates

# Record Helpers (add products)
from .utils.quote_agent.record_helpers import save_quote_products, handle_quote_line_update_request, save_quote_line_update, handle_quote_update_request, save_quote_update

# DB Helpers (products exists)
from .utils.quote_agent.db_helpers import get_or_create_account_and_opportunity, update_opportunity_net_amount, log_action_usage

# General Helpers
from .utils.quote_agent.general_helpers import get_active_quote, set_active_quote_to_session_data, get_quote_details, get_backup_value_from_quote_line, format_currency, wrap_text


# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"
# OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

def quote_agent(user, action, user_message, session_data):

    action_map = {
        "CreateQuote": create_quote, #HELPERS READY
        "AddProduct": add_product_to_quote, #HELPERS READY
        "UpdateQuoteLine": update_quote_line, #HELPERS READY
        "UpdateQuote": update_quote,          #HELPERS READY
        #"ApplyQuoteLineDiscount": update_quote_line,  # (Not needed) Logic already handled in update_quote function
        #"ApplyQuoteDiscount": update_quote,           # (Not needed) Logic already handled in update_quote function
        "DeleteQuoteLine": delete_quote_line,
        "DeleteQuote": delete_quote,
        "ShowQuoteDetails": show_quote_details,
        #"UpdateQuoteNotes": update_quote_notes,       # (Not needed) Logic already handled in update_quote function
        "ShowQuoteNotes": show_quote_notes,
        "GenerateQuoteDocument": generate_quote_pdf,
        "UpdateQuoteLineFromUI": update_quote_line_from_ui,
        "UpdateQuoteFromUI": update_quote_from_ui
        # "ProvideDates": provide_dates,
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user, user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request."}

#< ----------------- CREATE A QUOTE -------------------- >

def create_quote(user,user_message, session_data):
    """Handles quote creation while preserving context."""

    # ✅ Extract the quote details with LLM
    extracted_details = extract_quote_details(user_message)

    # ✅ Get or create account and opportunity
    result_account_and_opportunity = get_or_create_account_and_opportunity(extracted_details, session_data)

    # - If message in result (error or pending_action) return
    if isinstance(result_account_and_opportunity, dict) and "message" in result_account_and_opportunity:
        return result_account_and_opportunity

    # - If not, get account and opportunity
    account, opportunity = result_account_and_opportunity

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
    log_action_usage("CreateQuote", user, "Quote", quote.name)

    # ✅ Extract products
    extracted_products = extracted_details.get("products", [])
    
    # In case the quote is created without any products
    if not extracted_products:
        logging.info("🟡 No products provided in initial quote creation.")

        session_data["pending_action"] = "add_product"
        # ✅ Update quote session
        set_active_quote_to_session_data(session_data, quote)

        return {
            "message": f"✅ Quote {quote.name} created for {account.name} under opportunity {opportunity.name}. Would you like to add more products now?"
        }
    
    # In case the quote is created with any products
    logging.info("🟡 Products provided in initial quote creation.")

    response_message = f"✅ Quote {quote.name} created for {account.name} under deal {opportunity.name}.<br><br>"

    # ✅ Save quote products
    quote, response_message, added_products = save_quote_products(extracted_products, quote, response_message)

    # ✅ Update quote (subtotal, discounts fields and net amount)
    quote.save()

    # ✅ Update amount in Opportunity
    update_opportunity_net_amount(quote.opportunity)

    # ✅ Reset pending action and update session
    session_data["pending_action"] = None

    # ✅ Update quote session
    set_active_quote_to_session_data(session_data, quote)
    
    # ✅ Check if the quote requires approval after adding the product
    approval_suggestion = get_approval_status("", "", quote.id, "")

    if added_products:
        response_message += f"<br>💰 Net amount updated to ${quote.net_amount:,.2f}. Would you like to add more products?"
    else:
        # No products were added (e.g., unknown SKUs)
        session_data["pending_action"] = "add_product"
        return {
            "message": f"✅ Quote `{quote.name}` created for {account.name} under opportunity `{opportunity.name}`.<br>Would you like to add more products now?"
        }
    
    # Append approval message or default notice
    if "message" in approval_suggestion:
        response_message += f"\n\n{approval_suggestion['message']}"
    else:
        response_message += "\n\n⚠️ No approval suggestion."

    return {
        "message": response_message
    }


#< ----------------- ADD PRODUCT TO QUOTE -------------------- >

def add_product_to_quote(user, user_message, session_data):
    """Handles adding multiple products to an existing quote."""
    logging.info("🔄 Adding product(s) to existing quote...")

    # ✅ Looking for active quote
    quote = get_active_quote(user_message, session_data)

    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        return quote
    

    # ✅ Extract multiple product details
    extracted_products = extract_product_details(user_message)

    if not extracted_products or not isinstance(extracted_products, list):
        return {
            "message": "⚠️ Error: Could not extract product details. Please specify SKU, quantity, and discount for each product."
        }

    added_products = []
    response_message = ""

    # ✅ Save quote products
    quote, response_message, added_products = save_quote_products(extracted_products, quote, response_message, allow_updates=True)
    log_action_usage("AddProduct", user, "Quote", quote.name)
    # ✅ Update quote (subtotal, discounts fields and net amount)
    quote.save()

    # ✅ Reset pending action
    session_data["pending_action"] = None

    # ✅ Update quote session
    set_active_quote_to_session_data(session_data, quote)

     # ✅ Check if the quote requires approval after adding the product
    approval_suggestion = get_approval_status("", "", quote.id, "")

    if added_products:
        response_message += f"<br>💰 Net amount updated to ${quote.net_amount:,.2f}. Would you like to add more products?"
    else:
        return {
            "message": "⚠️ Error: Something went wrong — no product was added to the quote. Please try again or verify your input."
        }
    
    # If an approval suggestion exists, append it to the message
    if "message" in approval_suggestion:
        response_message += f"\n\n{approval_suggestion['message']}"
    else:
        response_message += "\n\n⚠️ No approval suggestion."
    
        
    return {
        "message": response_message,
        "update_details": get_quote_details(quote),
        "temporaryMessage": True
    }
    
#< ----------------- UPDATE QUOTE LINE -------------------- >

def update_quote_line(user, user_message, session_data):
    """Updates only the modified fields in quote lines."""

    logging.info("🔧 Updating quote line...\n\n")
    # ✅ Looking for active quote
    quote = get_active_quote(user_message, session_data)

    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        return quote
        
    # ✅ Extract quote line updates with LLM
    extracted_updates = extract_quote_line_updates(user_message)

    if not extracted_updates:
        # ✅ Save quote in session data
        set_active_quote_to_session_data(session_data, quote)
        
        return {
        "message": "⚠️ AgentCPQ: An error occurred while extracting your updates. Please try again."
        }
    
    response_message = ""

    # ✅ Handle quote line update request
    quote, response_message, updated_products = handle_quote_line_update_request(extracted_updates, quote, response_message)
    log_action_usage("UpdateQuoteLine", user, "Quote", quote.name)
    # ✅ Update quote (subtotal, discounts fields and net amount)
    quote.save()

    # ✅ Safe active quote to session data
    set_active_quote_to_session_data(session_data, quote)

    # ✅ Return
    if not updated_products:
        return {
            "message": f"No products were updated. <br><br>{response_message}",
            "temporaryMessage": True
        } 
    
    return {
        "message": response_message,
        "temporaryMessage": True
        
        }

#< ----------------- UPDATE QUOTE -------------------- >

def update_quote(user, user_message, session_data):
    """Updates only the modified fields in quote lines."""

    logging.info("🔧 Updating quote...\n\n")
    # ✅ Looking for active quote
    quote = get_active_quote(user_message, session_data)

    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        return quote
        
    # ✅ Extract quote line updates with LLM
    extracted_updates = extract_quote_updates(user_message)

    if not extracted_updates:
        # ✅ Save quote in session data
        set_active_quote_to_session_data(session_data, quote)
        return {
        "message": "⚠️ AgentCPQ: An error occurred while extracting your updates. Please try again."
        }
    
    response_message = ""

    # ✅ Handle quote line update request
    quote, response_message, updated_quote = handle_quote_update_request(extracted_updates, quote, response_message)
    log_action_usage("UpdateQuote", user, "Quote", quote.name)

    # ✅ Safe active quote to session data
    set_active_quote_to_session_data(session_data, quote)

    # ✅ Return
    if not updated_quote:
        return {
            "message": f"No quotes were updated. <br><br>{response_message}",
            "temporaryMessage": True
        } 
    
    return {
        "message": response_message,
        "temporaryMessage": True
        }


#< ----------------- DELETE QUOTE LINE -------------------- >
    
def delete_quote_line(user, user_message, session_data):
    """Deleting quote line item from quote"""
    response_message = ""
    try:
        # Looking for active quote
        quote = get_active_quote(user_message, session_data)

        # ⚠️ Verify if function return an error
        if isinstance(quote, dict) and "message" in quote:
            return quote
        
        logging.info(f"🔄 Deleting quote line item from quote {quote}...")

        extracted_sku = extract_quote_line_items_to_delete(user_message)

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

            #print(f"\n\nQuote details: {sku} | {name}\n\n")
            
            # Check is quote line exists in active quote
            try:
                quote_line = QuoteLine.objects.get(quote=quote, product=product)
                quote_line.delete()
                log_action_usage("DeleteQuoteLine", user, "Quote", quote.name)

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

#< ----------------- DELETE QUOTE -------------------- >

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

#< ----------------- SHOW QUOTE DETAILS -------------------- >

def show_quote_details(user_message, session_data):
    """Fetches and formats quote details, including quote lines, based on user input or session data."""
    try:
        logging.info("🔄 Showing quote details...")

        # Looking for active quote
        quote = get_active_quote(user_message, session_data)

        # ⚠️ Verify if function return an error
        if isinstance(quote, dict) and "message" in quote:
            return quote

        # ✅ Format the response
        quote_details = get_quote_details(quote)


        set_active_quote_to_session_data(session_data, quote)

        return {"message": "Here are the quote details:", "quote_details": quote_details, "hiddenMessage": "True"}
    
    except Quote.DoesNotExist:
        return {"message": "⚠️ Error: Quote not found. Please check the quote name."}

#< ----------------- SHOW QUOTE DETAILS -------------------- >

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
            "message": msg
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

#< ----------------- GENERATE QUOTE DOCUMENT -------------------- >

def generate_quote_pdf(user,user_message, session_data):
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

        log_action_usage("GenerateQuoteDocument", user, "Quote", quote.name)

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
<<<<<<< HEAD
=======
    
    
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
    
        
def delete_quote(user, user_message, session_data):
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
                log_action_usage("DeleteQuote", user, "Quote", quote_name)
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
    
def update_quote_notes(user, user_message, session_data):
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
                    log_action_usage("UpdateQuoteNotes", user, "Quote", quote.name)
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
>>>>>>> origin/hubspot


#< ----------------- UPDATE QUOTE LINE FROM UI -------------------- >

def update_quote_line_from_ui(user_message, session_data):
    """Handles updates to quote lines triggered from the UI."""
    logging.info("📝 Updating quote line(s) from front-end UI...")

    # ✅ Looking for active quote
    quote = get_active_quote(user_message, session_data)

    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        return quote
    
    try:
        json_match = re.search(r'\{.*\}', user_message)

        if user_message.startswith("Update Quote Line: ") and json_match:
            json_payload = user_message.replace("Update Quote Line: ", "", 1).strip()
            print(f"\n\n{json_payload}\n\n")

            # Save original values in case something went wrong and restart values on UI
            original_value = get_backup_value_from_quote_line(json_payload, quote)

            response = save_quote_line_update(json_payload, quote)

            # ✅ Save quote in session data
            set_active_quote_to_session_data(session_data, quote)

            if response.get("success") == True:
                return {
                    "message": response.get("message"),
                    "quote_details": get_quote_details(quote),
                    "hiddenMessage": True
                }
            else:
                return {
                    "message": response.get("message"),
                    "original_value": original_value,
                    "hiddenMessage": True
                }
    except Exception as e:
        logging.warning(f"⚠️ Error updating quote line: {str(e)}")
        return {"message": f"⚠️ Error updating quote line: {str(e)}"}
    
#< ----------------- UPDATE QUOTE FROM UI -------------------- >
        
def update_quote_from_ui(user,user_message, session_data):
    """Handles updates to quote lines triggered from the UI."""
    logging.info("📝 Updating quote from front-end UI...")
    
    try:
        json_match = re.search(r'\{.*\}', user_message)

        if user_message.startswith("Update Quote: ") and json_match:
            json_payload = user_message.replace("Update Quote: ", "", 1).strip()

            data = json.loads(json_payload)
            quote_name = data["quote"]
            print(f"\n\n{quote_name}\n\n")

            # Save original values in case something went wrong and restart values on UI
            #original_value = get_backup_value_from_quote_line(json_payload, quote)
            try:
                quote = Quote.objects.get(name=quote_name)
            except Quote.DoesNotExist:
                return {
                    "message": f"The quote with name '{quote_name}' could not be found.",
                    "original_value": "original_value",
                    "hiddenMessage": True
                }
            
            #Replace "quote" for "quote_id" on dict
            data["quote_id"] = quote.id
            del data["quote"]  # Delete previous key

            json_payload = json.dumps(data)

            response = save_quote_update(json_payload)

            quote.refresh_from_db()

            # ✅ Save quote in session data
            set_active_quote_to_session_data(session_data, quote)

            if response.get("success") == True:
                return {
                    "message": response.get("message"),
                    "quote_details": get_quote_details(quote),
                    "hiddenMessage": True
                }
            else:
                return {
                    "message": response.get("message"),
                    "original_value": "original_value",
                    "hiddenMessage": True
                }
    except Exception as e:
        logging.warning(f"⚠️ Error updating quote: {str(e)}")
        return {"message": f"⚠️ Error updating quote: {str(e)}"}