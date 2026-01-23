import logging
import json
import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from cpq.models import Product, Opportunity, Account, QuoteLine, Quote, CustomFieldValue, ContentType
from django.db.models import Q, Sum
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from copy import deepcopy
from datetime import datetime
from .date_utils import parse_user_date
from django.forms.models import model_to_dict

# DB Helpers
from .db_helpers import find_product_and_normalize_variables, update_opportunity_net_amount

# General Helpers
from .general_helpers import clean_inline_html, normalize_term_for_product, get_quote_details, set_active_quote_to_session_data, copy_custom_fields_values_from_product_to_quote_line
from ..message_formatters import SUCCESS_ICON

#Rules Helpers
from ..admin_agent.rules_helpers import build_temp_quote_line, check_for_rules_quote_line_level, check_inclusion_rules_for_quote_level, check_exclusion_rules_for_quote_level, check_for_rules_quote_level

# Session Context Helpers
from ..orchestrator.context_handle_helpers import save_or_update_conversation_context


# SAVE QUOTE LINE ITEM ON DATABASE (UPDATE_QUOTE_LINE)
def update_quote_line_record(user, update_payload, line_item, quote):
    try:
        quantity = update_payload.get("quantity", None)
        discount_type = update_payload.get("discount_type", None)
        discount_percentage = update_payload.get("discount_percentage", None)
        discount_amount = update_payload.get("discount_amount", None)
        term = update_payload.get("term", None)
        # If product has custom fields, then create that custom fields to quote line
        copy_custom_fields_values_from_product_to_quote_line(line_item)
        # Update values
        if quantity is not None:
            line_item.quantity = quantity
        if discount_type is not None:
            line_item.discount_type = discount_type
        if discount_percentage is not None:
            line_item.discount_percentage = discount_percentage
        if discount_amount is not None:
            line_item.discount_amount = discount_amount
        if term is not None:
            line_item.term = term
        line_item.save()
        try:
            quote.refresh_from_db()
            quote.save()
            update_opportunity_net_amount(quote.opportunity)
        except Exception as exc:
            logging.warning("⚠️ Quote recalculation failed after quote line update: %s", exc)

        return {
            "success": True
        }
    except Exception as e:
        print(f"Error trying yo save update quote line: {str(e)}")
        return {
            "message": f"⚠️ Error updating line item: {str(e)}",
            "success": False
        }

def save_quote_line_update(request, quote):
    try:
        update = json.loads(request)  # Extract JSON array

        sku = update["sku"]
        field = update["field"]
        new_value = update["value"]
        quote_line_id = update["quote_line_id"]


        bundle_parent_id = None
        with transaction.atomic():
            try:
                quote_line = QuoteLine.objects.get(id=quote_line_id, quote=quote, product__sku=sku)
            except QuoteLine.DoesNotExist:
                return {
                    "message": f"⚠️ Error: No line item found for SKU {sku} in this quote.",
                    "success": False
                }

            if field == "term" and not quote_line.is_subscription:
                return {
                    "message": "⚠️ Error: A term cannot be assigned to a product that is not a subscription.",
                    "success": False
                }

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

            # Get values from quote line to temporary quote line
            product = quote_line.product
            quantity = quote_line.quantity
            discount_type = quote_line.discount_type
            if discount_type not in ["percentage", "amount"]:
                discount_value = Decimal("0.00")
            else:
                discount_value = quote_line.discount_percentage if discount_type == "percentage" else quote_line.discount_amount
            term = quote_line.term

            # Make a temporary quote line to check for rules
            temp_quote_line = build_temp_quote_line(quote, product, quantity, discount_type, Decimal(discount_value), term)

            ##################### ✅ Checkrules
            # Validate validations rules
            validations = check_for_rules_quote_line_level("quote_line", "validation", quote, product, temp_quote_line)

            if validations:
                validations_message = "".join(f"- {v}<br>" for v in validations)
                response_message = f"🛑 Product {product.name}/{product.sku} triggered one or more validation rules 🛑<br>{validations_message}"
                print(f"\n\n🛑 Validation rule was triggered by product {product.name}/{product.sku} 🛑. Request omitted.\n\n")

                raise ValueError(response_message)

            # Save the quote line to calculate general values of quote line (subtotal, discounts, etc.)
            quote_line.save()

            if quote_line.is_bundle_child and quote_line.parent_line_id:
                bundle_parent_id = quote_line.parent_line_id

        try:
            copy_custom_fields_values_from_product_to_quote_line(quote_line)
        except Exception as exc:
            logging.warning("⚠️ Unable to sync custom fields for quote line %s: %s", quote_line_id, exc)

        if bundle_parent_id:
            try:
                bundle = QuoteLine.objects.filter(pk=bundle_parent_id).first()
                if bundle:
                    bundle.save()
            except Exception as exc:
                logging.warning("⚠️ Unable to update bundle parent %s: %s", bundle_parent_id, exc)

        # ✅ Update quote (subtotal, discounts fields and net amount)
        quote_update_warning = None
        try:
            quote.refresh_from_db()
            quote.save()
            update_opportunity_net_amount(quote.opportunity)
        except Exception as exc:
            logging.warning("⚠️ Quote recalculation failed after quote line update: %s", exc)
            quote_update_warning = exc
        response_message = f"{SUCCESS_ICON} Quote line updated successfully."
        if quote_update_warning:
            response_message = (
                f"{SUCCESS_ICON} Quote line updated. Totals may take a moment to refresh."
            )

        return {
            "message": response_message,
            "success": True
        }

    except ValueError as ve:
        return {
            "message": str(ve),
            "success": False
        }

    except Exception as e:
        logging.warning(f"⚠️ Error updating quote line: {str(e)}")
        return {
            "message": f"Error updating quote line: {str(e)}",
            "success": False
        }


# Handle quote update request
def handle_quote_update_request(extracted_updates, quote, response_message):

    logging.info(f"=>>>>>>>>>>>>>>>>>>>> 🛠️ Creating record for update quote 🛠️")

    # ✅ Add products to the quote if provided
    updated_quotes = []

    for index, item in enumerate(extracted_updates, start=1):

        quote_name = item.get("name", None)
        field = item.get("field", None)
        value = item.get("value", None)

        print(f"\n\nField: {field}\n\nValue: {value}\n\n")

        field_labels = {
            "status": "Status",
            "discount_percentage": "Discount Percentage",
            "discount_amount": "Discount Amount",
            "expiration_date": "Expiration Date",
            "notes": "Notes",
            "tax_percentage": "Tax Percentage"
        }


        response_message += f"<b>🔄 <u>Quote Update Request #{index}</u> 🔄</b><br>"

        # General validations
        # If quote name is not in the correct format
        if quote_name is not None:
            if not (isinstance(quote_name, str) and re.match(r"^Q-\d{5}$", quote_name)):
                logging.warning(f"⚠️ Invalid quote name format: {quote_name}. Skipping update.")
                response_message += f"⚠️ Invalid quote name format: {quote_name}."
                continue

        if field is None:
            logging.warning(f"⚠️ Error: No field to update was detected in your request.")
            response_message += f"⚠️ Error: No field to update was detected in your request. Please specify which attribute (e.g., status, discount, expiration date or notes) you want to modify.<br><br>"
            continue

        if field not in field_labels:
            logging.warning(f"⚠️ Error: Field '{field}' is not a valid field to update was detected in your request.")
            response_message += f"⚠️ Error: Field '{field}' is not a valid field to update was detected in your request. Please specify which attribute (e.g., status, discount, expiration date or notes) you want to modify.<br><br>"
            continue

        if value is None:
            logging.warning(f"⚠️ Error: No value was detected in your request. Please specify the new value for the update.")
            response_message += f"⚠️ Error: No value was detected in your request. Please specify the new value for the update.<br><br>"
            continue

        if field.startswith("discount") and Decimal(value) < 0:
            logging.warning("⚠️ Error: The value for discounts cannot be less than or equals 0. Please provide a valid number.")
            response_message += f"⚠️ Error: The value for discounts cannot be less than or equals 0. Please provide a valid number.<br><br>"
            continue

        allowed_status = ["Draft", "Pending Approval", "Approved", "Rejected", "Closed"]

        if field == "status" and value not in allowed_status:
            logging.warning(f"⚠️ Error: '{value}' is not a valid status. Please use one of: Draft, Pending Approval, Approved, Rejected, or Closed.")
            response_message += f"⚠️ Error: '{value}' is not a valid status. Please use one of: Draft, Pending Approval, Approved, Rejected, or Closed.<br><br>"
            continue

        formatted_date = None

        if field == "expiration_date":
            try:
                parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                logging.warning(f"⚠️ Error: '{value}' is not a valid date. Use the format YYYY-MM-DD (e.g., 2025-07-30).")
                response_message += f"⚠️ Error: '{value}' is not a valid date. Use the format YYYY-MM-DD (e.g., 2025-07-30).<br><br>"
                continue
            formatted_date = parsed_date.strftime("%m/%d/%Y")

        # After general validations
        # If user specifies the name of a quote, set that quote name to current quote
        if quote_name is not None:
            try:
                current_quote = Quote.objects.get(name=quote_name)
            except Quote.DoesNotExist:
                logging.warning(f"⚠️ Quote with name '{quote_name}' not found. Skipping update.")
                response_message += f"⚠️ Quote with name '{quote_name}' not found."
                continue
        # If not, set the current quote as session active quote
        else:
            current_quote = quote

        # ✅ Format response message
        response_message += f"🧾 Quote: {current_quote.name}<br>"
        response_message += f"🏷️ Field: {field_labels.get(field, field.capitalize())}<br>"
        response_message += f"✏️ Value: {formatted_date if field == 'expiration_date' else value}<br><br>"


        update_payload = {
            "quote_id": current_quote.id,
            "field": field,
            "value": value
        }

        logging.warning(f"=>>>>>>>>>>>>>>>>>>>> Trying to update quote: {update_payload}")

        #Convert list to valid JSON
        item_json = json.dumps(update_payload)

        # Try to update quote line
        #logging.warning(f"=>>>>>>>>>>>>>>>>>>>> Entra a la function save_quote_line_update.")
        response = save_quote_update(item_json)

        if response.get("success"):
            response_message += f"{response.get('message')}<br><br>"
            updated_quotes.append(update_payload)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            response_message += f"{error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return quote, response_message, updated_quotes


def save_quote_update(request):
    try:
        update = json.loads(request)  # Extract JSON array

        quote_id = update["quote_id"]
        field = update["field"]
        new_value = update["value"]

        try:
            quote = Quote.objects.get(id=quote_id)
        except Quote.DoesNotExist:
            return {
                "message": f"Quote with ID {quote.id} was not found in the database.",
                "success": False
            }

        with transaction.atomic():

            original_quote = deepcopy(quote)

            # ✅ Update based on the field dynamically
            fields = ["status", "expiration_date", "notes"]

            if field in fields:
                if field == "expiration_date" and isinstance(new_value, str):
                    new_value = parse_user_date(new_value)
                if field == "notes" and isinstance(new_value, str):
                    # Normalize common rich-text wrappers (execCommand tends to produce <div>)
                    normalized = re.sub(r"</div\s*>", "</p>", new_value, flags=re.IGNORECASE)
                    normalized = re.sub(r"<div[^>]*>", "<p>", normalized, flags=re.IGNORECASE)
                    new_value = clean_inline_html(normalized)
                setattr(quote, field, new_value)
            elif field == "tax_percentage":
                quote.tax_percentage = Decimal(str(new_value))
            else:
                if field == "discount_percentage":
                    quote.discount_type = "percentage"
                    quote.discount_percentage = new_value
                elif field == "discount_amount":
                    quote.discount_type = "amount"
                    quote.discount_amount = new_value


            ##################### ✅ Checkrules

            quote.subtotal = quote.get_subtotal_amount()
            quote.update_discount_fields()
            quote.update_net_amount()

            # Validate validations rules
            triggered_rules = check_for_rules_quote_level("quote", "validation", quote)

            if triggered_rules:
                validations_message = "".join(f"- {v}<br>" for v in triggered_rules)
                response_message = f"🛑 Quote {quote.name} triggered one or more validation rules 🛑<br>{validations_message}"
                print(f"\n\n🛑 Validation rule was triggered by quote {quote.name} 🛑. Request omitted.\n\n")

                raise ValueError(response_message)

            # ✅ Update quote (subtotal, discounts fields and net amount)
            quote.save()
            update_opportunity_net_amount(quote.opportunity)
            #########################################################################################################

            response_message = f"{SUCCESS_ICON} Quote updated successfully."

            return {
                "message": response_message,
                "success": True
            }

    except ValueError as ve:
        return {
            "message": str(ve),
            "success": False
        }

    except Exception as e:
        logging.warning(f"⚠️ Error updating quote: {str(e)}")
        return {
            "message": f"Error updating quote: {str(e)}",
            "success": False
        }
