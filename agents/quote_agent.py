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
import logging
logger = logging.getLogger(__name__)
# LLM Utils
from .utils.quote_agent.llm_helpers import extract_quote_details, extract_quote_details_with_llm, generate_final_create_quote_message, extract_quote_line_items_to_delete, generate_final_delete_quote_lines_message, generate_final_quote_updates_message, extract_quote_line_to_delete_with_llm
from .utils.quote_agent.llm_helpers import extract_quote_updates, extract_quote_updates_with_llm

# Record Helpers (add products)
from .utils.quote_agent.record_helpers import save_quote_products, save_quote_line_update, handle_quote_update_request, save_quote_update

# DB Helpers (products exists)
from .utils.quote_agent.db_helpers import get_or_create_account_and_opportunity, update_opportunity_net_amount, log_action_usage

# General Helpers
from .utils.quote_agent.general_helpers import get_active_quote, set_active_quote_to_session_data, get_quote_details, get_backup_value_from_quote_line, format_currency, wrap_text
from .utils.quote_agent.general_helpers import get_document_pdf, get_backup_value_from_quote

from .utils.orchestrator.context_handle_helpers import save_or_update_conversation_context, make_session_context

# Session Context Helpers
from .utils.session_context_helpers.session_context_helpers import get_session_context

# Notification Email Functions
from cpq.notifications.notifications import notify_opportunity_created

from .utils.quote_agent.general_helpers import extract_line_items_from_user_message

# New LLm Helpers
from .utils.quote_agent.llm_helpers import extract_products_to_add_with_llm, generate_final_add_product_to_quote_message, extract_quote_line_updates_with_llm, generate_final_update_line_items_message

from .utils.quote_agent.handle_helpers import handle_products_to_add, handle_quote_line_update_request, handle_line_items_updates

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo"
# OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

def quote_agent(user, action, user_message, session_data):

    action_map = {
        "CreateQuote": create_quote, #CONTEXT READY
        "AddProductToQuote": add_product_to_quote, #CONTEXT READY
        "UpdateQuoteLine": update_quote_line, #CONTEXT READY
        "UpdateQuote": update_quote, #CONTEXT READY
        "DeleteQuoteLine": delete_quote_line, #CONTEXT READY
        "DeleteQuote": delete_quote,
        "ShowQuoteDetails": show_quote_details, #CONTEXT READY
        "ShowQuoteNotes": show_quote_notes, #CONTEXT READY
        "GenerateQuoteDocument": generate_quote_pdf, #CONTEXT READY
        "UpdateQuoteLineFromUI": update_quote_line_from_ui, # NO NEED CONTEXT
        "UpdateQuoteFromUI": update_quote_from_ui # NO NEED CONTEXT
        # "ProvideDates": provide_dates,
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user, user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request."}

#< ----------------- CREATE A QUOTE -------------------- >

def create_quote(user,user_message, session_data):
    """Handles quote creation while preserving context."""
    # 🧠 Make the session context
    #session_context = make_session_context(user, "CreateQuote", "quote_agent", session_data, user_message)

    current_state, previous_summary = get_session_context("create_product", session_data)

    # ✅ Extract the quote details with LLM
    #extracted_details = extract_quote_details(user_message)

    # --- 1️⃣ Llamada inicial al LLM para extraer quote details ---
    llm_result, tokens_used, cost_est = extract_quote_details_with_llm(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary
    )

    if llm_result["create_quote"]["completed"] == False:
        return {
            "message": llm_result["agent_message"],
            "session_summary": llm_result["summary"]
        }

    if llm_result:
        extracted_details = llm_result["create_quote"]["data"]

    # ✅ Get or create account and opportunity
    result_account_and_opportunity = get_or_create_account_and_opportunity(user, extracted_details, session_data)

    # - If message in result (error or pending_action) return
    if isinstance(result_account_and_opportunity, dict) and "message" in result_account_and_opportunity:
        return result_account_and_opportunity
    
    result = []

    # - If not, get account and opportunity
    account, opportunity = result_account_and_opportunity

    # ✅ Create Quote
    quote = Quote.objects.create(
        account=account,
        opportunity=opportunity,
        status="Draft",
        net_amount=Decimal("0.00"),
        owner=user,
        created_by=user
    )

    # ✅ Assign formatted name after creation using quote.id
    quote.name = f"Q-{quote.id:05d}"
    quote.save()
    log_action_usage("CreateQuote", user, "Quote", quote.name)

    logging.info(f"✅ Quote {quote.name} created for {account.name} under opportunity {opportunity.name}. Would you like to add more products now?")

    # ✅ Extract products
    extracted_products = extracted_details.get("products", [])
    
    # In case the quote is created without any products
    if not extracted_products:

        result.append(f"✅ Quote {quote.name} created for {account.name} under opportunity {opportunity.name}. Would you like to add more products now?")
        result.append("🟡 No products provided in initial quote creation.")

        session_data["pending_action"] = "add_product"
        # ✅ Update quote session
        set_active_quote_to_session_data(session_data, quote)

        dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_create_quote_message(
            quote=extracted_details,
            db_results=result,
            previous_summary=llm_result["summary"]
        )

        return {
            "message": dynamic_message,
            "session_summary": updated_summary
        }
    
    # In case the quote is created with any products
    logging.info("🟢 Products provided in initial quote creation.")

    response_message = f"✅ Quote {quote.name} created for {account.name} under deal {opportunity.name}.<br><br>"

    result.append(f"✅ Quote {quote.name} created for {account.name} under deal {opportunity.name}.<br><br>")
    result.append("🟢 Products provided in initial quote creation.")

    # ✅ Save quote products
    quote, response_message, added_products = save_quote_products(extracted_products, quote, response_message)

    # ✅ Update quote (subtotal, discounts fields and net amount)
    quote.save()

    # ✅ Update amount in Opportunity
    update_opportunity_net_amount(quote.opportunity)

    # Send email notification with opportunity
    if quote.opportunity:
        notify_opportunity_created(quote.opportunity)

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
        response_message += f"{approval_suggestion['message']}"
    else:
        response_message += "⚠️ No approval suggestion."

    result.append(response_message)

    dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_create_quote_message(
        quote=extracted_details,
        db_results=result,
        previous_summary=llm_result["summary"]
    )

    return {
        "message": dynamic_message,
        "session_summary": updated_summary
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
    

    current_state, previous_summary = get_session_context("add_product_to_quote", session_data)


    # --- 1️⃣ Llamada inicial al LLM para extraer los productos que se agregaran al quote ---
    llm_result, tokens_used, cost_est = extract_products_to_add_with_llm(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary
    )

    # --- 3️⃣ Separar productos completados vs incompletos ---
    completed_products = []
    remaining_products = []

    for line_item in llm_result["add_product_to_quote"]:
        if line_item.get("completed"):
            completed_products.append(line_item["data"])
        else:
            remaining_products.append(line_item)


    # Guardar solo los incompletos en session state
    session_data["state"]["add_product_to_quote"] = remaining_products

    # Return if not any completed products
    if not completed_products:
        return {
            "message": llm_result["agent_message"],
            "session_summary": llm_result["summary"]
        }

    # --- 4️⃣ Persistir productos completados y capturar errores ---
    result = handle_products_to_add(user, completed_products, quote, allow_updates=True)

    print(f"Esto es result: {result}")

    # --- 5️⃣ Generar mensaje final dinámico usando función separada ---
    dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_add_product_to_quote_message(
        completed_products=completed_products,
        db_results=result,
        remaining_products=remaining_products,
        previous_summary=llm_result["summary"]
    )

    return {
        "message": dynamic_message,
        "session_summary": updated_summary
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

    current_state, previous_summary = get_session_context("update_quote_line", session_data)

    line_items_on_user_message = extract_line_items_from_user_message(user_message, quote)

    print(f"\n\nLine items mencionados: {line_items_on_user_message}\n\n")

    # --- 1️⃣ Llamada inicial al LLM para extraer actualizaciones de quote line ---
    llm_result, tokens_used, cost_est = extract_quote_line_updates_with_llm(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary,
        line_items_on_user_message=line_items_on_user_message #Send line items to LLM can updates
    )
    
    # --- 3️⃣ Separar productos completados vs incompletos ---
    completed_updates = []
    remaining_updates = []

    for line_item in llm_result["update_quote_line"]:
        if line_item.get("completed"):
            completed_updates.append(line_item["data"])
        else:
            remaining_updates.append(line_item)

    # Guardar solo los incompletos en session state
    session_data["state"]["line_items_updates"] = remaining_updates

    # Return if not any completed products
    if not completed_updates:
        return {
            "message": llm_result["agent_message"],
            "session_summary": llm_result["summary"]
        }
    
    print(f"Esto es completed updates: {completed_updates}")
    
    ################################################

    response_message = ""

    # ✅ Handle quote line update request
    quote, response_message, updated_products = handle_quote_line_update_request(completed_updates, quote, response_message)
    log_action_usage("UpdateQuoteLine", user, "Quote", quote.name)
    # ✅ Update quote (subtotal, discounts fields and net amount)
    quote.save()

    # ✅ Safe active quote to session data
    set_active_quote_to_session_data(session_data, quote)

    # --- 5️⃣ Generar mensaje final dinámico usando función separada ---
    dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_update_line_items_message(
        completed_updates=completed_updates,
        db_results=response_message,
        remaining_updates=remaining_updates,
        previous_summary=llm_result["summary"]
    )

    return {
        "message": dynamic_message,
        "session_summary": updated_summary
    }
    
#< ----------------- UPDATE QUOTE LINE -------------------- >

def update_quote_line2(user, user_message, session_data):
    """
    Handles product creation requests for multiple products.
    Tracks products in session state, saves completed products, 
    and generates dynamic messages using LLM including DB errors.
    """
    logging.info("🔧 Updating quote line...\n\n")

    # ✅ Looking for active quote
    quote = get_active_quote(user_message, session_data)

    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        return quote
    

    current_state, previous_summary = get_session_context("update_quote_line", session_data)

    line_items_on_user_message = extract_line_items_from_user_message(user_message, quote)

    print(f"\n\nLine items mencionados: {line_items_on_user_message}\n\n")

    # --- 1️⃣ Llamada inicial al LLM para extraer actualizaciones de quote line ---
    llm_result, tokens_used, cost_est = extract_quote_line_updates_with_llm(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary,
        line_items_on_user_message=line_items_on_user_message #Send line items to LLM can updates
    )

    # --- 3️⃣ Separar productos completados vs incompletos ---
    completed_updates = []
    remaining_updates = []

    for line_item in llm_result["update_quote_line"]:
        if line_item.get("completed"):
            completed_updates.append(line_item["data"])
        else:
            remaining_updates.append(line_item)


    # Guardar solo los incompletos en session state
    session_data["state"]["line_items_updates"] = remaining_updates

    # Return if not any completed products
    if not completed_updates:
        return {
            "message": llm_result["agent_message"],
            "session_summary": llm_result["summary"]
        }

    # --- 4️⃣ Persistir productos completados y capturar errores ---
    result = handle_line_items_updates(user, completed_updates, quote)

    # --- 5️⃣ Generar mensaje final dinámico usando función separada ---
    dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_update_line_items_message(
        completed_updates=completed_updates,
        db_results=result,
        remaining_updates=remaining_updates,
        previous_summary=llm_result["summary"]
    )

    return {
        "message": dynamic_message,
        "session_summary": updated_summary
    }

#< ----------------- UPDATE QUOTE -------------------- >

def update_quote(user, user_message, session_data):
    """Updates only the modified fields in quote lines."""

    logging.info("🔧 Updating quote...\n\n")
    
    # 🧠 Make the session context
    #session_context = make_session_context(user, "UpdateQuote", "quote_agent", session_data, user_message)

    current_state, previous_summary = get_session_context("update_quote", session_data)
        
    # ✅ Extract quote line updates with LLM
    #extracted_updates = extract_quote_updates(user_message)

    # ✅ Looking for active quote
    quote = get_active_quote(user_message, session_data)

    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        return quote

    # --- 1️⃣ Llamada inicial al LLM para extraer productos ---
    llm_result, tokens_used, cost_est = extract_quote_updates_with_llm(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary,
        quote_name=quote.name
    )

    # --- 3️⃣ Separar productos completados vs incompletos ---
    completed_quote_updates = []
    remaining_quote_updates = []

    for product in llm_result["update_quote"]:
        if product.get("completed"):
            completed_quote_updates.append(product["data"])
        else:
            remaining_quote_updates.append(product)

    # Guardar solo los incompletos en session state
    session_data["state"]["update_quote"] = remaining_quote_updates

    # Return if not any completed products
    if not completed_quote_updates:
        return {
            "message": llm_result["agent_message"],
            "session_summary": llm_result["summary"]
        }
    
    extracted_updates = []

    for quote_update in llm_result["update_quote"]:
            extracted_updates.append(quote_update["data"])

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

    dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_quote_updates_message(
        completed_quote_updates=completed_quote_updates,
        db_results=response_message,
        remaining_quote_updates=remaining_quote_updates,
        previous_summary=llm_result["summary"]
    )

    # ✅ Return
    if not updated_quote:
        return {
            "message": f"No quotes were updated. <br><br>{dynamic_message}",
            "temporaryMessage": True
        } 
    
    return {
        "message": dynamic_message,
        "temporaryMessage": True
        }
    
def delete_quote_line(user, user_message, session_data):
    """Deleting quote line item from quote"""
    # 🧠 Make the session context
    #session_context = make_session_context(user, "DeleteQuoteLine", "quote_agent", session_data, user_message)

    current_state, previous_summary = get_session_context("delete_quote_line", session_data)

    response_message = ""

    try:
        llm_result, tokens_used, cost_est = extract_quote_line_to_delete_with_llm(
            user_message=user_message,
            current_state=current_state,
            previous_summary=previous_summary
        )

        #print(f"\n\nEsto retorna el LLM: {llm_result}\n\n")

        # --- 3️⃣ Separar productos completados vs incompletos ---
        completed_quote_lines = []
        remaining_quote_lines = []

        for product in llm_result["delete_quote_line"]:
            if product.get("completed"):
                completed_quote_lines.append(product["data"])
            else:
                remaining_quote_lines.append(product)

        # Guardar solo los incompletos en session state
        session_data["state"]["delete_quote_line"] = remaining_quote_lines

        # Return if not any completed products
        if not completed_quote_lines:
            return {
                "message": llm_result["agent_message"],
                "session_summary": llm_result["summary"]
            }
        
        #extracted_sku = extract_quote_line_items_to_delete(user_message)

        extracted_sku = []

        for quote_line in llm_result["delete_quote_line"]:
            extracted_sku.append(quote_line["data"])


        # Looking for active quote
        quote = get_active_quote(user_message, session_data)

        # ⚠️ Verify if function return an error
        if isinstance(quote, dict) and "message" in quote:
            agent_response = f"Missing fields: quantity, discount or term"

            return quote
        
        logging.info(f"🔄 Deleting quote line item from quote {quote}...")

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
            
            # Check is quote line exists in active quote
            try:
                quote_line = QuoteLine.objects.get(quote=quote, product=product, is_bundle_child=False)

                quote_line.delete()
                
                log_action_usage("DeleteQuoteLine", user, "Quote", quote.name)

                response_message += f"✅ The quote line with product SKU '{product.sku}' was successfully deleted from quote '{quote.name}'.<br>"
                continue

            except QuoteLine.DoesNotExist:
                quote_line = None
                response_message += f"⚠️ The quote line with product SKU '{product.sku}' does not exist in quote {quote.name}.<br>"
                continue

            except Exception as e:
                quote_line = None
                response_message += f"⚠️ Something went wrong when trying to update the quote line Error: {e}.<br>"
                continue

    except Quote.DoesNotExist:
        return {
            "message": "⚠️ Error: Quote not found. Please check the quote name."
        }
    
    # ✅ Save quote in session data
    set_active_quote_to_session_data(session_data, quote)

    # ✅ Update quote (subtotal, discounts fields and net amount)
    quote.save()

    dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_delete_quote_lines_message(
        completed_quote_lines=completed_quote_lines,
        db_results=response_message,
        remaining_quote_lines=remaining_quote_lines,
        previous_summary=llm_result["summary"]
    )

    return {
        "message": dynamic_message,
        "session_summary": updated_summary,
        "update_details": get_quote_details(quote),
        "temporaryMessage": True,
        "iterations": index
    }

#< ----------------- DELETE QUOTE -------------------- >

def delete_quote(user, user_message, session_data):
    """Deleting Quote"""
    # 🧠 Make the session context
    session_context = make_session_context(user, "DeleteQuote", "quote_agent", session_data, user_message)

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
    # 🧠 Make the session context
    session_context = make_session_context(user, "ShowQuoteDetails", "quote_agent", session_data, user_message)
    try:
        logging.info("🔄 Showing quote details...")

        # Looking for active quote
        quote = get_active_quote(user_message, session_data)

        # ⚠️ Verify if function return an error
        if isinstance(quote, dict) and "message" in quote:
            session_context["item_index"] = 1
            session_context["extracted"] = "No extracted data, user just wants to show quote details."
            agent_response = f"No active quote was found, just save data and retry."
            save_or_update_conversation_context(session_context, agent_response)
            return quote

        # ✅ Format the response
        quote_details = get_quote_details(quote)

        # If quote document settings has not been created
        if isinstance(quote_details, dict) and "message" in quote_details and "error" in quote_details:
            if quote_details["message"] and quote_details["error"]:
                return {
                    "message": quote_details["message"]
                }


        set_active_quote_to_session_data(session_data, quote)

        return {"message": "Here are the quote details:", "quote_details": quote_details, "hiddenMessage": "True"}
    
    except Exception as e:
        session_context["item_index"] = 1
        session_context["extracted"] = "No extracted data, user just wants to show quote details."
        agent_response = f"Error: Something went wrong when trying to show quote details: {str(e)}."
        save_or_update_conversation_context(session_context, agent_response)
        return {"message": f"⚠️ Error: Something went wrong when trying to show quote details: {str(e)}."}

#< ----------------- SHOW QUOTE DETAILS -------------------- >

def show_quote_notes(user, user_message, session_data):
    """Showing Quote Notes"""
    # 🧠 Make the session context
    session_context = make_session_context(user, "ShowQuoteNotes", "quote_agent", session_data, user_message)
    response_message = ""
    try:
        #Looking for active quote
        quote = get_active_quote(user_message, session_data)

        # ⚠️ Verify if function return an error
        if isinstance(quote, dict) and "message" in quote:
            session_context["item_index"] = 1
            session_context["extracted"] = "No extracted data, user just wants to show quote notes."
            agent_response = f"No active quote was found, just save data and retry."
            save_or_update_conversation_context(session_context, agent_response)
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
    
    except Exception as e:
        logging.exception("An unexpected error occurred while showing the quote.")
        session_context["item_index"] = 1
        session_context["extracted"] = "No extracted data, user just wants to show quote notes."
        agent_response = f"An unexpected error occurred while trying to show quote notes: {str(e)}"
        save_or_update_conversation_context(session_context, agent_response)
        return {
            "message": f"❌ An unexpected error occurred: {str(e)}"
        }

#< ----------------- GENERATE QUOTE DOCUMENT -------------------- >

def generate_quote_pdf(user,user_message, session_data):
    # 🧠 Make the session context
    session_context = make_session_context(user, "GenerateQuoteDocument", "quote_agent", session_data, user_message)

    # Looking for active quote
    quote = get_active_quote(user_message, session_data)
    logger.info("📦 Starting PDF generation...")
    # logger.debug(f"Quote ID: {quote.id}, Tenant: {quote.account.tenant.id}")

    # ⚠️ Verify if function return an error
    if isinstance(quote, dict) and "message" in quote:
        session_context["item_index"] = 1
        session_context["extracted"] = "No extracted data, user just wants to generate quote document/pdf."
        agent_response = f"No active quote was found, just save data and retry."
        save_or_update_conversation_context(session_context, agent_response)
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
