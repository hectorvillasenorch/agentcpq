import logging
import json
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from cpq.models import Product, Opportunity, Account, QuoteLine
from django.db.models import Q, Sum
from agents.admin_agent import check_for_rules

from .db_helpers import find_product_and_normalize_variables, update_opportunity_net_amount
from .general_helpers import normalize_term_for_product, get_quote_details, build_temp_quote_line, set_active_quote_to_session_data


def save_quote_products(products, quote, response_message, allow_updates=False):
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

    for product_data in products:
        # ✅ Set up variables
        sku = product_data.get("sku")
        name = product_data.get("name")
        discount_type = product_data.get("discount_type", None)
        term = product_data.get("term", None)

        # - Validate quantity
        raw_quantity = product_data.get("quantity", 1)

        try:
            quantity = int(raw_quantity)
            if quantity <= 0:
                logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ Invalid quantity '{quantity}' for product {sku or name}. Skipping...")
                response_message += f"⚠️ Invalid quantity '{quantity}' for product {sku or name}. Skipping...<br>"
                continue
        except (ValueError, TypeError):
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ Quantity '{raw_quantity}' is not a valid integer for product {sku or name}. Skipping...")
            response_message += f"⚠️ Quantity '{raw_quantity}' is not a valid integer for product {sku or name}. Skipping...<br>"
            continue

        # - Validate discount_value
        try:
            discount_value = Decimal(product_data.get("discount_value", 0))
            if discount_value < 0:
                response_message += f"⚠️ Discount '{discount_value}' cannot be less than 0. Please enter a valid discount.<br>"
                continue
        except (TypeError, InvalidOperation):
            discount_value = Decimal(0)
        
        ################ FINAL SET UP VARIABLES ################



        # ✅ Check if the product exists and normalize sku and name variables 
        #    in case the LLM identified the sku as the name and vice versa
        product, sku, name = find_product_and_normalize_variables(sku, name)

        if not product:
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ Product `{sku if sku else name}` not found in the database. Skipping...")
            response_message += f"⚠️ Product `{sku if sku else name}` not found. Skipping...<br>"
            continue  # Skip this product and move to the next

        ################################################# ✅ Checkrules

        temp_quote_line = build_temp_quote_line(quote, product, quantity, discount_type, Decimal(discount_value), term)

        validations = check_for_rules("quote_line", quote, product, temp_quote_line)
        #print(f"\n\nViolations: {violations}")

        if validations:
            validations_message = ""
            for v in validations:
                validations_message += f"- {v}<br>"
            response_message += f"\n\n🛑 Product {product.name}/{product.sku} violated one or more validation rules 🛑<br>{validations_message}"
            added_products.append(f"🛑 Product {product.name}/{product.sku} violated one or more validation rules 🛑")
            print(f"\n\nViolation with product {product.name}/{product.sku}. Skipping...\n\n")
            continue

        #################################################

        # ✅ Check if existing line
        existing_line = QuoteLine.objects.filter(quote=quote, product=product).first()

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

            user_message = f"Update Quote Line: {json.dumps(update_payload)}"

            
            response = save_quote_line_updates(user_message, quote)

            if (
                response.get("message") == "✅ Quote line(s) updated successfully." and
                "quote_details" in response and
                "line_items" in response["quote_details"]
            ):
                added_products.append(f"{quantity}x {sku}/{name}.")
        
                if discount_type == "percentage":
                    response_message += f"✅ Updated {quantity}x {sku}/{name} with a {discount_value}% discount.<br>"
                elif discount_type == "amount":
                    response_message += f"✅ Updated {quantity}x {sku}/{name} to quote {quote.name} with a ${discount_value} discount.<br>"
                else:
                    response_message += f"✅ Updated {quantity}x {sku}/{name}.<br>"
            else:
                response_message+= "⚠️ Error: While updating quote line {sku}/{name} (Error details: ).<br><br>"
                logging.warning("⚠️ Update Failed")


            # ✅ Refresh quote to get new net_amount from database
            quote.refresh_from_db()
            existing_line.refresh_from_db()

            continue

        # ✅ If the product already exists in the quote, skip it during creation
        #    This avoids creating duplicate quote lines when the same SKU is mentioned multiple times
        elif existing_line and not allow_updates:
            logging.warning(f"⚠️ Product `{sku}` already exists in quote. Skipping creation.")
            response_message += f"⚠️ Product `{sku}` already exists in the quote. Skipping...<br>"
            continue

        logging.info(f"=>>>>>>>>>>>>>>>>>>>> SKU: {sku}")

        # ✅ Normalize term if product is subscription or not
        term = normalize_term_for_product(product, term)


        # ✅ Set discount fields for every discount type
        discount_fields = {}

        if discount_type == "percentage":
            discount_fields["discount_type"] = discount_type
            discount_fields["discount_percentage"] = Decimal(discount_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif discount_type == "amount":
            discount_fields["discount_type"] = discount_type
            discount_fields["discount_amount"] = Decimal(discount_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            discount_fields["discount_type"] = "Null"
            discount_fields["discount_amount"] = Decimal("0.00")
            discount_fields["discount_percentage"] = Decimal("0.00")

        try:
            quote_line = QuoteLine.objects.create(
                quote=quote,
                product=product,
                quantity=quantity,
                term=term,
                **discount_fields,
                description=product.description,
                is_subscription=product.is_subscription,
            )

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
        except Exception as e:
            logging.error(f"❌ Error adding product {sku}/{name}: {str(e)}")
            response_message += f"❌ Error adding product {sku}/{name} to quote {quote.name}.<br>"
    
    return quote, response_message, added_products

def handle_quote_line_update_request(extracted_updates, quote, response_message):

    logging.info(f"=>>>>>>>>>>>>>>>>>>>> 🛠️ Creating record for update products 🛠️")

    # ✅ Add products to the quote if provided
    updated_products = []

    for index, item in enumerate(extracted_updates, start=1):
            
        sku = item.get("sku", None)
        name = item.get("name", None)
        field = item.get("field", None)
        value = item.get("term", None)

        field_labels = {
            "quantity": "Quantity",
            "discount_percentage": "Discount Percentage",
            "discount_amount": "Discount Amount",
            "term": "Term"
        }

        # General validations
        if sku is None:
            response_message += f"⚠️ Error: No SKU/Name was detected in your request. Please specify the product code(s) to update.<br><br>"
            continue

        if field is None:
            response_message += f"⚠️ Error: No field to update was detected in your request. Please specify which attribute (e.g., quantity, discount or term) you want to modify.<br><br>"
            continue

        if field not in field_labels:
            response_message += f"⚠️ Error: No valid field to update was detected in your request. Please specify which attribute (e.g., quantity, discount or term) you want to modify.<br><br>"
            continue

        if value is None or value == 0:
            response_message += f"⚠️ Error: No value was detected in your request. Please specify the new value for the update.<br><br>"
            continue
        
        try:
            numeric_value = Decimal(value)
        except (InvalidOperation, ValueError, TypeError):
            response_message += f"⚠️ Error: The value \"{value}\" is not a valid number. Please enter a valid numeric value.<br><br>"

        if field.startswith("discount") and Decimal(value) <= 0:
            response_message += f"⚠️ Error: The value for discounts cannot be less than or equals 0. Please provide a valid number.<br><br>"

        if field == "term" and int(value) < 0:
            response_message += f"⚠️ Error: The value for terms cannot be less than 0. Please provide a valid number.<br><br>"


        item_field = field_labels.get(field, field.capitalize())
        response_message += f"<b>🔄 <u>Update Request #{index} in quote {quote.name}</u> 🔄</b><br>"

        # ✅ Check if the product exists and normalize sku and name variables 
        #    in case the LLM identified the sku as the name and vice versa
        product, sku, name = find_product_and_normalize_variables(sku, name)

        if not product:
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ Product `{sku if sku else name}` not found in the database. Skipping...")
            response_message += f"⚠️ Product `{sku if sku else name}` not found. Skipping...<br>"
            continue  # Skip this product and move to the next

        response_message += f"🔢 SKU: {sku}<br>"
        response_message += f"🏷️ Field: {field}<br>"
        response_message += f"✏️ Value: {value}<br><br>"


        #Validate if product exist in actual quote line item
        quote_line = QuoteLine.objects.filter(quote=quote, product=product).first()
        if not quote_line:
            response_message += f"⚠️ Error: The product `{sku}/{name}` is not in the current quote.<br><br>"
            continue

        # Add quote_line_id to item
        item['quote_line_id'] = quote_line.id

        #Convert list to valid JSON
        item_json = json.dumps([item])  
        request_message = f"Update Quote Line: {item_json}"

        logging.warning(f"=>>>>>>>>>>>>>>>>>>>> Trying to update: {item}")

        # Try to update quote line
        response = save_quote_line_updates(request_message, quote)

        if (
            response.get("message") == "✅ Quote line(s) updated successfully." and
            "quote_details" in response and
            "line_items" in response["quote_details"]
        ):
            response_message += "✅ Quote line updated successfully.<br><br>"
            updated_products.append(item)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ✅ Quote line updated successfully.")
        else:
            error_msg = response.get("message", "Unknown error.")
            response_message += f"⚠️ {error_msg}<br>"
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return quote, response_message, updated_products


def save_quote_line_updates(user_message, quote):
    try:
        updates = json.loads(user_message.replace("Update Quote Line: ", ""))  # Extract JSON array

        response_message = ""

        for update in updates:
            sku = update["sku"]
            field = update["field"]
            new_value = update["value"]
            quote_line_id = update["quote_line_id"]

            try:
                quote_line = QuoteLine.objects.get(id=quote_line_id, quote=quote, product__sku=sku)
            except QuoteLine.DoesNotExist:
                return {
                    "message": f"⚠️ Error: No line item found for SKU {sku} in this quote."
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

            quote_line.save()

        # ✅ Update quote (subtotal, discounts fields and net amount)
        quote.save()
        update_opportunity_net_amount(quote.opportunity)
        
        return {
            "message": "✅ Quote line(s) updated successfully.",
            "quote_details": get_quote_details(quote),
            "hiddenMessage": "True"
        }
    except Exception as e:
        logging.warning(f"⚠️ Error updating quote line: {str(e)}")
        return {"message": f"⚠️ Error updating quote line: {str(e)}"}