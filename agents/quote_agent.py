from django.db.models import Sum, F
import json
import os
import openai
import logging
import re
import locale
from dotenv import load_dotenv
from cpq.models import Quote, Account, Opportunity, QuoteLine, Product, QuoteDocument, Tenant, QuoteDocumentSettings, BusinessRule, CustomField, CustomFieldValue
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
from .utils.quote_agent.general_helpers import get_document_pdf, get_backup_value_from_quote

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
        "DeleteQuoteLine": delete_quote_line,
        "DeleteQuote": delete_quote,
        "ShowQuoteDetails": show_quote_details,
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

#< ----------------- SHOW QUOTE DETAILS -------------------- >

def show_quote_details(user, user_message, session_data):
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
        result = get_document_pdf(quote)

        # ✅ Save quote in session data
        set_active_quote_to_session_data(session_data, quote)

        if result.get("success"):
            # Guardamos la quote en la sesión
            set_active_quote_to_session_data(session_data, quote)

            log_action_usage("GenerateQuoteDocument", user, "Quote", quote.name)

            # Retornamos los datos con hiddenMessage = True
            return {
                "message": result["message"],
                "download_url": result["download_url"],
                "document_version": result["document_version"],
                "hiddenMessage": True,
            }
        else:
            # Error al generar PDF (pero manejado dentro de get_document_pdf)
            return {
                "message": result.get("message", "⚠️ Unknown error generating PDF."),
                "success": False
            }
    except Exception as e:
        # Error inesperado (por si acaso)
        return {
            "message": f"⚠️ Unexpected error: {str(e)}",
            "success": False
        }


#< ----------------- UPDATE QUOTE LINE FROM UI -------------------- >

def update_quote_line_from_ui(user, user_message, session_data):
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
            print(f"mensaje: {user_message}")
            json_payload = user_message.replace("Update Quote: ", "", 1).strip()

            data = json.loads(json_payload)
            quote_name = data["quote"]
            print(f"\n\n{quote_name}\n\n")

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

            # Save original values in case something went wrong and restart values on UI
            original_value = get_backup_value_from_quote(json_payload, quote)

            json_payload = json.dumps(data)

            response = save_quote_update(json_payload)

            print(f"Duque hijo de puta: {response}")

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
                    "original_value": original_value,
                    "hiddenMessage": True
                }
    except Exception as e:
        logging.warning(f"⚠️ Error updating quote: {str(e)}")
        return {"message": f"⚠️ Error updating quote: {str(e)}"}
