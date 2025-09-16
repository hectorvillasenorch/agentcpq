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

# DB Helpers
from .db_helpers import find_product_and_normalize_variables, update_opportunity_net_amount

# General Helpers
from .general_helpers import normalize_term_for_product, get_quote_details, set_active_quote_to_session_data, copy_custom_fields_values_from_product_to_quote_line

#Rules Helpers
from ..admin_agent.rules_helpers import build_temp_quote_line, check_for_rules_quote_line_level, check_for_rules_quote_level

# Session Context Helpers
from ..orchestrator.context_handle_helpers import save_or_update_conversation_context


def save_quote_products(products, quote, response_message, session_context, allow_updates=False):
    """
    Creates QuoteLine records for a given quote using a list of already structured product dictionaries.

    Each product dictionary must contain at least:
    - 'sku' or 'name'
    - 'quantity'
    - 'discount_type'
    - 'discount_value'
    - 'term'

    Skips invalid entries and appends messages to the response.

    Returns:
    - The updated quote instance
    - A message string summarizing the result
    """
    logging.info(f"=>>>>>>>>>>>>>>>>>>>> 🛠️ Creating record for products 🛠️")

    # ✅ Add products to the quote if provided
    added_products = []

    for index, product_data in enumerate(products):
        # ✅ Set up variables
        sku = product_data.get("sku")
        name = product_data.get("name")
        discount_type = product_data.get("discount_type", None)
        term = product_data.get("term", None)

        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = product_data

        # - Validate quantity
        raw_quantity = product_data.get("quantity", 1)

        try:
            quantity = int(raw_quantity)
            if quantity <= 0:
                logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ Invalid quantity '{quantity}' for product {sku or name}. Request omitted.")
                response_message += f"⚠️ Invalid quantity '{quantity}' for product {sku or name}. Request omitted.<br>"
                agent_response = "Invalid quantity '{quantity}' for product {sku or name}."
                save_or_update_conversation_context(session_context, agent_response)
                continue
        except (ValueError, TypeError):
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ Quantity '{raw_quantity}' is not a valid integer for product {sku or name}. Request omitted.")
            response_message += f"⚠️ Quantity '{raw_quantity}' is not a valid integer for product {sku or name}. Request omitted.<br>"
            agent_response = "Quantity '{raw_quantity}' is not a valid integer for product {sku or name}."
            save_or_update_conversation_context(session_context, agent_response)
            continue

        # - Validate discount_value
        try:
            discount_value = Decimal(product_data.get("discount_value", 0))
            if discount_value < 0:
                response_message += f"⚠️ Discount '{discount_value}' cannot be less than 0. Please enter a valid discount.<br>"
                agent_response = "Discount '{discount_value}' cannot be less than 0. Please enter a valid discount.<br>"
                save_or_update_conversation_context(session_context, agent_response)
                continue
        except (TypeError, InvalidOperation):
            discount_value = Decimal(0)
        
        ################ FINAL SET UP VARIABLES ################

        # ✅ Check if the product exists and normalize sku and name variables 
        #    in case the LLM identified the sku as the name and vice versa
        product, sku, name = find_product_and_normalize_variables(sku, name)

        if not product:
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ Product `{sku if sku else name}` not found in the database. Request omitted.")
            response_message += f"⚠️ Product `{sku if sku else name}` not found. Request omitted.<br>"
            continue  # Skip this product and move to the next

        ################################################# ✅ Checkrules

        # Make a temporary quote line to check for rules
        temp_quote_line = build_temp_quote_line(quote, product, quantity, discount_type, Decimal(discount_value), term)

        # Validate validations rules
        validations = check_for_rules_quote_line_level("quote_line", ["validation"], quote, product, temp_quote_line)

        if validations:
            validations_message = ""
            for v in validations:
                validations_message += f"- {v}<br>"
            response_message += f"🛑 Product {product.name}/{product.sku} triggered one or more validation rules 🛑<br>{validations_message}"
            added_products.append(f"🛑 Product {product.name}/{product.sku} triggered one or more validation rules 🛑")
            print(f"\n\nValidation rule was triggered by product {product.name}/{product.sku}. Request omitted.\n\n")
            agent_response = f"Product {product.name}/{product.sku} triggered one or more validation rules: {validations_message}"
            save_or_update_conversation_context(session_context, agent_response)
            continue

        #################################################

        # ✅ Check if existing line
        existing_line = QuoteLine.objects.filter(quote=quote, product=product, is_bundle_child=False).first()

        # ✅ If the product already exists in the quote and updates are allowed,
        #    update the existing quote line instead of creating a new one
        if existing_line and allow_updates:

            logging.info(f"=>>>>>>>>>>>>>>>>>>>> 🔁 Product `{sku}/{name}` already in quote. Updating instead of creating.")

            # Update quantity (previous quantity + new quantity)
            new_quantity = existing_line.quantity + int(quantity)

            update_payload = [{
                "sku": sku,
                "field": "quantity",
                "value": new_quantity,
                "quote_line_id": str(existing_line.id),
                "hiddenMessage": True
            }]

            # Only add discount if discount is different than 0
            if Decimal(discount_value) != 0 and discount_type in ["percentage", "amount"]:
                update_payload.append({
                    "sku": sku,
                    "field": "discount_percentage" if discount_type == "percentage" else "discount_amount",
                    "value": str(discount_value),
                    "quote_line_id": str(existing_line.id),
                    "hiddenMessage": True
                })

            # Update term if is in the data
            if term and product.is_subscription:
                update_payload.append({
                    "sku": sku,
                    "field": "term",
                    "value": term,
                    "quote_line_id": str(existing_line.id),
                    "hiddenMessage": True
                })

            successful_fields = []
            failed_fields = []
            # Update session context with update information
            session_context["extracted"] = update_payload

            for update in update_payload:
                request = json.dumps(update)
                response = save_quote_line_update(request, quote)

                if response.get("success"):
                    successful_fields.append(update["field"])
                    response_message += f"✅ Updated `{update['field']}` to `{update['value']}` for product `{update['sku']}`.<br>"
                else:
                    failed_fields.append(update["field"])
                    response_message += (
                        f"⚠️ Error updating field `{update['field']}` for product `{update['sku']}` "
                        f"(details: {response.get('message')}).<br>"
                    )
                    agent_response = f"Update Failed for field {update['field']}: {response.get('message')}"
                    save_or_update_conversation_context(session_context, agent_response)

                    logging.warning(f"⚠️ Update Failed for field {update['field']}: {response.get('message')}")


            if successful_fields:
                added_products.append(f"{quantity}x {sku}/{name}.")
                 # ✅ Refresh quote to get new net_amount from database
                quote.refresh_from_db()
                existing_line.refresh_from_db()

            continue

        # ✅ If the product already exists in the quote, skip it during creation
        #    This avoids creating duplicate quote lines when the same SKU is mentioned multiple times
        elif existing_line and not allow_updates:
            logging.warning(f"⚠️ Product `{sku}` already exists in quote. Skipping creation.")
            response_message += f"⚠️ Product `{sku}` already exists in the quote. Request omitted.<br>"
            continue

        logging.info(f"=>>>>>>>>>>>>>>>>>>>> SKU: {sku}")

        # ✅ Normalize term if product is subscription or not
        term = normalize_term_for_product(product, term)


        # ✅ Set discount fields for every discount type
        discount_fields = {}

        if discount_type == "percentage":
            discount_fields["discount_type"] = discount_type
            discount_fields["discount_percentage"] = Decimal(str(discount_value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif discount_type == "amount":
            discount_fields["discount_type"] = discount_type
            discount_fields["discount_amount"] = Decimal(str(discount_value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            discount_fields["discount_type"] = "Null"
            discount_fields["discount_amount"] = Decimal("0.00")
            discount_fields["discount_percentage"] = Decimal("0.00")

        try:
            if product.is_bundle:
                print("Product is a bundle")
                try:
                    # Parent Quote Line
                    quote_line = QuoteLine.objects.create(
                        quote=quote,
                        product=product,
                        quantity=quantity,
                        term=term,
                        **discount_fields,
                        description=product.description,
                        is_subscription=product.is_subscription,
                        is_bundle_parent=True, #Asign true to bundle parent
                        parent_line=None, #This is the parent line
                    )

                    # Children Quote Line(s)
                    bundle_response_message = ""
                    for option in product.options.all():
                        if option.default_selected and option.product_option:
                            QuoteLine.objects.create(
                                quote=quote,
                                product=option.product_option,
                                quantity=int(option.quantity),
                                parent_line=quote_line, # Bundle parent quote line
                                is_bundle_parent=False,
                                is_bundle_child=True,
                                product_option=option,
                                is_subscription=option.product_option.is_subscription,
                                term=None,
                                discount_type=None,
                                discount_percentage=Decimal("0.00"),
                                discount_amount=Decimal("0.00"),
                                is_bundle_component_selected=True # Indicates that it is and option selected
                            )

                            bundle_response_message += f"&emsp;🔧 Added {option.quantity}x {option.product_option.sku}/{option.product_option.name} ({option.parent_product})<br>"
                        
                        elif option.default_selected == False and option.product_option:
                            QuoteLine.objects.create(
                                quote=quote,
                                product=option.product_option,
                                quantity=int(option.quantity),
                                parent_line=quote_line, # Bundle parent quote line
                                is_bundle_parent=False,
                                is_bundle_child=True,
                                product_option=option,
                                is_subscription=option.product_option.is_subscription,
                                term=None,
                                discount_type=None,
                                discount_percentage=Decimal("0.00"),
                                discount_amount=Decimal("0.00"),
                                is_bundle_component_selected=False # Indicates that it is and option selected
                            )

                            bundle_response_message += f"&emsp;🔘 Pending: {option.quantity}x {option.product_option.sku}/{option.product_option.name} - You can add this item to the quote.<br>"

                except Exception as e:
                    print(f"Error: {e}")

            else:
                bundle_response_message = "" #Restart variable for no bundle products
                quote_line = QuoteLine.objects.create(
                    quote=quote,
                    product=product,
                    quantity=quantity,
                    term=term,
                    **discount_fields,
                    description=product.description,
                    is_subscription=product.is_subscription,
                )

            # If Product has custom fields, then create custom fields to QuoteLine
            copy_custom_fields_values_from_product_to_quote_line(quote_line)


            # ✅ Force saving and reloading from DB to verify
            quote_line.refresh_from_db()
            logging.info(f"=>>>>>>>>>>>>>>>>>>>> Saved Total Price in DB: {quote_line.total_price}")

            added_products.append(f"{quantity}x {sku}/{name}.")
            
            if discount_type == "percentage":
                response_message += f"✅ Added {quantity}x {sku}/{name} to quote {quote.name} with a {discount_value}% discount.<br>"
            elif discount_type == "amount":
                response_message += f"✅ Added {quantity}x {sku}/{name} to quote {quote.name} with a ${discount_value} discount.<br>"
            else:
                response_message += f"✅ Added {quantity}x {sku}/{name} to quote {quote.name}.<br>"

            response_message += bundle_response_message
        except Exception as e:
            agent_response = f"Error adding product {sku}/{name}: {str(e)}"
            save_or_update_conversation_context(session_context, agent_response)
            logging.error(f"❌ Error adding product {sku}/{name}: {str(e)}")
            response_message += f"❌ Error adding product {sku}/{name} to quote {quote.name}.<br>"
    
    return quote, response_message, added_products

def handle_quote_line_update_request(extracted_updates, quote, response_message, session_context):

    logging.info(f"=>>>>>>>>>>>>>>>>>>>> 🛠️ Creating record for update products 🛠️")

    # ✅ Add products to the quote if provided
    updated_products = []

    for index, item in enumerate(extracted_updates, start=1):
            
        sku = item.get("sku", None)
        name = item.get("name", None)
        field = item.get("field", None)
        value = item.get("value", None)

        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = item

        field_labels = {
            "quantity": "Quantity",
            "discount_percentage": "Discount Percentage",
            "discount_amount": "Discount Amount",
            "term": "Term"
        }

        response_message += f"<b>🔄 <u>Line Item Update #{index} in quote {quote.name}</u> 🔄</b><br>"

        # General validations
        if sku is None and name is None:
            response_message += f"⚠️ Error: No SKU/Name was detected in your request. Please specify the product code(s) to update.<br><br>"
            continue

        if field is None:
            agent_response = "Missing fields: quantity, discount or term"
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Error: No field to update was detected in your request. Please specify which attribute (e.g., quantity, discount or term) you want to modify.<br><br>"
            continue

        if field not in field_labels:
            agent_response = f"Invalid field: `{field}` is not a recognized field. Valid fields are: {', '.join(field_labels.keys())}."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Error: No valid field to update was detected in your request. Please specify which attribute (e.g., quantity, discount or term) you want to modify.<br><br>"
            continue

        if value is None:
            agent_response = "No value was detected in your request"
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Error: No value was detected in your request. Please specify the new value for the update.<br><br>"
            continue
        
        try:
            numeric_value = Decimal(value)
        except (InvalidOperation, ValueError, TypeError):
            agent_response = f"Error: The value {value} is not a valid number. Please replace value with a valid numeric value."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Error: The value \"{value}\" is not a valid number. Please enter a valid numeric value.<br><br>"
            continue

        if field.startswith("discount") and Decimal(value) < 0:
            agent_response = f"Error: The value for discounts cannot be less than 0. Provide a valida number"
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Error: The value for discounts cannot be less than 0. Please provide a valid number.<br><br>"
            continue

        if field == "term" and int(value) < 0:
            agent_response = "Error: The value for terms cannot be less than 0. Please provide a valida number."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Error: The value for terms cannot be less than 0. Please provide a valid number.<br><br>"
            continue

        # After general validations
        # ✅ Check if the product exists and normalize sku and name variables 
        #    in case the LLM identified the sku as the name and vice versa
        product, sku, name = find_product_and_normalize_variables(sku, name)

        if not product:
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ Product `{sku if sku else name}` not found in the database. Request omitted.")
            response_message += f"⚠️ Product `{sku if sku else name}` not found. Request omitted.<br>"
            continue  # Skip this product and move to the next

        # ✅ Format response message
        response_message += f"🔢 SKU: {sku}<br>"
        response_message += f"🏷️ Field: {field_labels.get(field, field.capitalize())}<br>"
        response_message += f"✏️ Value: {value}<br><br>"


        #Validate if product exist in actual quote line item
        quote_line = QuoteLine.objects.filter(quote=quote, product=product).first()
        if not quote_line:
            agent_response = f"Error: The product {sku}/{name} is not in the current quote. Do not modify anything, just reply data."
            save_or_update_conversation_context(session_context, agent_response)
            response_message += f"⚠️ Error: The product `{sku}/{name}` is not in the current quote.<br><br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ Error: The product `{sku}/{name}` is not in the current quote.")
            continue

        update_payload = {
            "sku": sku,
            "field": field,
            "value": value,
            "quote_line_id": str(quote_line.id)
        }

        logging.warning(f"=>>>>>>>>>>>>>>>>>>>> Trying to update: {update_payload}")

        #Convert list to valid JSON
        item_json = json.dumps(update_payload)

        # Try to update quote line
        #logging.warning(f"=>>>>>>>>>>>>>>>>>>>> Entra a la function save_quote_line_update.")
        response = save_quote_line_update(item_json, quote)

        if response.get("success"):
            response_message += f"{response.get('message')}<br><br>"
            updated_products.append(update_payload)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            response_message += f"{error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return quote, response_message, updated_products


def save_quote_line_update(request, quote):
    try:
        update = json.loads(request)  # Extract JSON array

        sku = update["sku"]
        field = update["field"]
        new_value = update["value"]
        quote_line_id = update["quote_line_id"]

        
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
            
            # If product has custom fields, then create that custom fields to quote line
            copy_custom_fields_values_from_product_to_quote_line(quote_line)

            original_quote_line = deepcopy(quote_line)

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
            # Get product from quote line
            product = quote_line.product

            # Validate validations rules
            validations = check_for_rules_quote_line_level("quote_line", "validation", quote, product, temp_quote_line)

            if validations:
                validations_message = "".join(f"- {v}<br>" for v in validations)
                response_message = f"🛑 Product {product.name}/{product.sku} triggered one or more validation rules 🛑<br>{validations_message}"
                print(f"\n\n🛑 Validation rule was triggered by product {product.name}/{product.sku} 🛑. Request omitted.\n\n")

                raise ValueError(response_message)

            # Save the quote line to calculate general values of quote line (subtotal, discounts, etc.)
            quote_line.save()

            if quote_line.is_bundle_child:
                bundle = quote_line.parent_line
                bundle.save()

            # ✅ Update quote (subtotal, discounts fields and net amount)
            quote.save()
            update_opportunity_net_amount(quote.opportunity)
            #########################################################################################################

        
            response_message = "✅ Quote line updated successfully."

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
def handle_quote_update_request(extracted_updates, quote, response_message, session_context):

    logging.info(f"=>>>>>>>>>>>>>>>>>>>> 🛠️ Creating record for update quote 🛠️")

    # ✅ Add products to the quote if provided
    updated_quotes = []

    for index, item in enumerate(extracted_updates, start=1):
            
        quote_name = item.get("name", None)
        field = item.get("field", None)
        value = item.get("value", None)

        field_labels = {
            "status": "Status",
            "discount_percentage": "Discount Percentage",
            "discount_amount": "Discount Amount",
            "expiration_date": "Expiration Date",
            "notes": "Notes",
            "tax_percentage": "Tax Percentage"
        }

        # Add full item for session context
        session_context["item_index"] = index
        session_context["extracted"] = item

        response_message += f"<b>🔄 <u>Quote Update Request #{index}</u> 🔄</b><br>"

        # General validations
        # If quote name is not in the correct format
        if quote_name is not None:
            if not (isinstance(quote_name, str) and re.match(r"^Q-\d{5}$", quote_name)):
                logging.warning(f"⚠️ Invalid quote name format: {quote_name}. Skipping update.")
                response_message += f"⚠️ Invalid quote name format: {quote_name}."
                agent_response = f"Invalid quote name format: {quote_name}."
                save_or_update_conversation_context(session_context, agent_response)
                continue

        if field is None:
            agent_response = f"Error: No field to update was detected in user request. Please specify one of these: status, discount, expiration date or notes."
            save_or_update_conversation_context(session_context, agent_response)
            logging.warning(f"⚠️ Error: No field to update was detected in your request.")
            response_message += f"⚠️ Error: No field to update was detected in your request. Please specify which attribute (e.g., status, discount, expiration date or notes) you want to modify.<br><br>"
            continue

        if field not in field_labels:
            agent_response = f"Error: Field '{field}' is not a valid field to update was detected in your request."
            save_or_update_conversation_context(session_context, agent_response)
            logging.warning(f"⚠️ Error: Field '{field}' is not a valid field to update was detected in your request.")
            response_message += f"⚠️ Error: Field '{field}' is not a valid field to update was detected in your request. Please specify which attribute (e.g., status, discount, expiration date or notes) you want to modify.<br><br>"
            continue

        if value is None:
            agent_response = f"Error: No value was detected in your request. Please specify the new value for the update."
            save_or_update_conversation_context(session_context, agent_response)
            logging.warning(f"⚠️ Error: No value was detected in your request. Please specify the new value for the update.")
            response_message += f"⚠️ Error: No value was detected in your request. Please specify the new value for the update.<br><br>"
            continue

        if field.startswith("discount") and Decimal(value) <= 0:
            agent_response = f"Error: The value for discounts cannot be less than or equals 0. Please provide a valid number."
            save_or_update_conversation_context(session_context, agent_response)
            logging.warning("⚠️ Error: The value for discounts cannot be less than or equals 0. Please provide a valid number.")
            response_message += f"⚠️ Error: The value for discounts cannot be less than or equals 0. Please provide a valid number.<br><br>"
            continue

        allowed_status = ["Draft", "Pending Approval", "Approved", "Rejected", "Closed"]

        if field == "status" and value not in allowed_status:
            agent_response = f"Error: '{value}' is not a valid status. Please use one of: Draft, Pending Approval, Approved, Rejected, or Closed."
            save_or_update_conversation_context(session_context, agent_response)
            logging.warning(f"⚠️ Error: '{value}' is not a valid status. Please use one of: Draft, Pending Approval, Approved, Rejected, or Closed.")
            response_message += f"⚠️ Error: '{value}' is not a valid status. Please use one of: Draft, Pending Approval, Approved, Rejected, or Closed.<br><br>"
            continue

        formatted_date = None

        if field == "expiration_date":
            try:
                parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                agent_response = f"Error: '{value}' is not a valid date. Use the format YYYY-MM-DD (e.g., 2025-07-30)."
                save_or_update_conversation_context(session_context, agent_response)
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
                agent_response = f"Quote with name '{quote_name}' not found. Please enter a valid quote name."
                save_or_update_conversation_context(session_context, agent_response)
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
            agent_response = f"Something were wrong when trying to update quote. Error: {error_msg}"
            save_or_update_conversation_context(session_context, agent_response)
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
        
            response_message = "✅ Quote updated successfully."

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
