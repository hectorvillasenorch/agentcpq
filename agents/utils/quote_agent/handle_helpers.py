import logging, json
from decimal import Decimal
from .db_helpers import find_product_and_normalize_variables
from cpq.models import QuoteLine, Option
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from django.forms.models import model_to_dict

#
from .record_helpers import update_quote_line_record, save_quote_line_update

from .general_helpers import normalize_term_for_product, copy_custom_fields_values_from_product_to_quote_line

#Rules Helpers
from ..admin_agent.rules_helpers import check_exclusion_rules_for_quote_level, build_temp_quote_line, check_for_rules_quote_line_level, check_inclusion_rules_for_quote_level, check_for_rules_quote_line_level

logger = logging.getLogger(__name__)

# ----------- UPDATE QUOTE LINE ----------- #

def handle_products_to_add(user, completed_products, quote, allow_updates=False, parent_line=None):
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
    logging.info(f"=>>>>>>>>>>>>>>>>>>>> 🛠️ Adding products to quote 🛠️ ")

    # ✅ Add products to the quote if provided
    result = []

    for index, product_data in enumerate(completed_products):
        result_payload = {
            "product": product_data,
            "status": "fail",
            "error": None
        }

        #print(f"\n\nProduct Data: {product_data}\n\n")

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
                logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {sku if sku else name} Error: Quantity can not be less than 0.")
                result_payload["error"] = f"Error: Quantity can not be less than 0."
                result.append(result_payload)
                continue
        except (ValueError, TypeError):
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ Quantity '{raw_quantity}' is not a valid integer for product {sku or name}. Request omitted.")
            result_payload["error"] = f"Error: Quantity must to be an integer."
            result.append(result_payload)
            continue

        # - Validate discount_value
        try:
            discount_value = Decimal(product_data.get("discount_value", 0))
            if discount_value < 0:
                result_payload["error"] = f"Error: Discount cannot be less than 0."
                result.append(result_payload)
                continue
        except (TypeError, InvalidOperation):
            discount_value = Decimal(0)

        ################ FINAL SET UP VARIABLES ################

        #print(f"\n\nEsto es sku: {sku} y name: {name}\n\n")

        # ✅ Check if the product exists and normalize sku and name variables
        #    in case the LLM identified the sku as the name and vice versa
        product, sku, name = find_product_and_normalize_variables(sku, name)

        if not product:
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ Product `{sku if sku else name}` not found in the database.")
            result_payload["error"] = "Product not found in the database."
            result.append(result_payload)
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

            print(f"\n\nValidation rule was triggered by product {product.name}/{product.sku}. Request omitted.\n\n")
            result_payload["error"] = f"🛑 Product {product.name}/{product.sku} triggered one or more validation rules 🛑<br>{validations_message}"
            result.append(result_payload)
            continue

        # Run inclusion rules unless this is a bundle (bundles are handled after parent is created) or a child add
        if parent_line is None and not product.is_bundle:
            inclusions = check_inclusion_rules_for_quote_level(user, "quote_line", "inclusion", quote, product)
            if inclusions:
                result_payload["inclusion_message"] = inclusions

        # Validate exclusion rules
        exclusions = check_exclusion_rules_for_quote_level(user, quote, product)

        if exclusions:
            # 🚫 Exclusion rule triggered — do NOT add the product
            logging.warning(f"🚫 Exclusion rule triggered for product {product.sku or product.name}. Skipping addition.")
            result_payload["error"] = f"🛑 Exclusion rule triggered for product {product.sku}/{product.name}:<br>{exclusions}<br>"
            result.append(result_payload)
            continue  # ⛔ Skip this product and move to the next one

        #################################################

        # ✅ Check if existing line (only when not forcing child creation)
        existing_line = QuoteLine.objects.filter(quote=quote, product=product, is_bundle_child=False).first()

        # ✅ If the product already exists in the quote and updates are allowed,
        #    update the existing quote line instead of creating a new one
        if parent_line is None and existing_line and allow_updates:

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

            updated_message = ""
            for update in update_payload:
                request = json.dumps(update)
                response = save_quote_line_update(request, quote)

                if response.get("success"):
                    successful_fields.append(update["field"])
                    updated_message += f"✅ Updated '{update['field']}' to '{update['value']}' for product '{name}'."
                else:
                    failed_fields.append(update["field"])
                    result_payload["error"] = (
                        f"⚠️ Error updating field `{update['field']}` for product `{update['sku']}` "
                        f"(details: {response.get('message')}).<br>"
                    )

                    logging.warning(f"⚠️ Update Failed for field {update['field']}: {response.get('message')}")


            if successful_fields:
                result_payload['status'] = "success"
                result_payload['updated_message'] = updated_message
                result.append(result_payload)
                 # ✅ Refresh quote to get new net_amount from database
                quote.refresh_from_db()
                existing_line.refresh_from_db()

            continue

        # ✅ If the product already exists in the quote, skip it during creation
        #    This avoids creating duplicate quote lines when the same SKU is mentioned multiple times
        elif parent_line is None and existing_line and not allow_updates:
            # Dejar aqui asi hasta modificar como manejamos el QUOTE
            logging.warning(f"⚠️ Product `{sku}` already exists in quote. Skipping creation.")
            result_payload['error'] = f"⚠️ Product `{sku or name}` already exists in quote. Skipping creation."
            result.append(result_payload)
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
            if product.is_bundle and parent_line is None:
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
                        if not option.product_option:
                            continue

                        # Only auto-create lines for required or default-selected options
                        if option.is_required or option.default_selected:
                            logging.info(
                                "################################# Evaluating bundle auto-select option parent=%s option=%s required=%s default=%s",
                                product.sku,
                                option.product_option.sku,
                                option.is_required,
                                option.default_selected,
                            )
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
                                is_bundle_component_selected=True # Indicates that it is an option selected
                            )

                            bundle_response_message += f"&emsp;🔧 Added {option.quantity}x {option.product_option.sku}/{option.product_option.name} ({option.parent_product})<br>"

                    # Run inclusion rules for this bundle with proper parent linkage
                    try:
                        check_inclusion_rules_for_quote_level(
                            user,
                            "quote_line",
                            "inclusion",
                            quote,
                            product,
                            skip_existing=True,
                            quote_line=quote_line,
                        )
                    except Exception as exc:
                        logging.warning("Inclusion rules during bundle add failed: %s", exc)

                except Exception as e:
                    print(f"Error: {e}")

            else:
                bundle_response_message = "" #Restart variable for no bundle products
                if parent_line is not None:
                    opts = list(
                        Option.objects.filter(parent_product=parent_line.product)
                        .values(
                            "id",
                            "parent_product__sku",
                            "product_option__sku",
                            "product_option__name",
                            "is_required",
                            "default_selected",
                        )
                    )
                    logger.warning("Bundle options for parent %s => %s", parent_line.product.sku, opts)

                    logger.warning("QL Product OPTION %s => %s",  opts)

                    # Strict match by child SKU under the same parent
                    option_obj = Option.objects.filter(
                        parent_product=parent_line.product,
                        product_option__sku__iexact=product.sku
                    ).first()
                    logger.warning(
                        "Selected option for child %s under parent %s => %s",
                        product.sku,
                        parent_line.product.sku,
                        option_obj.id if option_obj else None,
                    )
                    quote_line = QuoteLine.objects.create(
                        quote=quote,
                        product=product,
                        quantity=quantity,
                        term=parent_line.term if parent_line.term is not None else term,
                        **discount_fields,
                        description=product.description,
                        is_subscription=product.is_subscription,
                        parent_line=parent_line,
                        is_bundle_parent=False,
                        is_bundle_child=True,
                        is_bundle_component_selected=True,
                        product_option=option_obj,
                    )
                else:
                    quote_line = QuoteLine.objects.create(
                        quote=quote,
                        product=product,
                        quantity=quantity,
                        term=term,
                        **discount_fields,
                        description=product.description,
                        is_subscription=product.is_subscription,
                    )

                #print(f"\n\n1 | Esto es quote line: {json.dumps(model_to_dict(quote_line), indent=4, default=str)}\n1 | Esto es quote: {json.dumps(model_to_dict(quote), indent=4, default=str)}\n\n")

            #print(f"\n\n1.5 | Esto es quote line: {json.dumps(model_to_dict(quote_line), indent=4, default=str)}\n1.5 | Esto es quote: {json.dumps(model_to_dict(quote), indent=4, default=str)}\n\n")
            # If Product has custom fields, then create custom fields to QuoteLine
            copy_custom_fields_values_from_product_to_quote_line(quote_line)


            # ✅ Force saving and reloading from DB to verify
            quote_line.refresh_from_db()
            #print(f"\n\n2 | Esto es quote line despues del refresh from db: {json.dumps(model_to_dict(quote_line), indent=4, default=str)}\n2 | Esto es quote: {json.dumps(model_to_dict(quote), indent=4, default=str)}\n\n")
            
            quote_line.save()
            #print(f"\n\n3 | Esto es quote line despues del save: {json.dumps(model_to_dict(quote_line), indent=4, default=str)}\n3 | Esto es quote: {json.dumps(model_to_dict(quote), indent=4, default=str)}\n\n")
            
            logging.info(f"=>>>>>>>>>>>>>>>>>>>> Saved Total Price in DB11111: {quote_line.total_price}")

            if discount_type == "percentage":
                discount_message = f"✅ Added {quantity}x {sku}/{name} to quote {quote.name} with a {discount_value}% discount.<br>"
            elif discount_type == "amount":
                discount_message = f"✅ Added {quantity}x {sku}/{name} to quote {quote.name} with a ${discount_value} discount.<br>"
            else:
                discount_message = f"✅ Added {quantity}x {sku}/{name} to quote {quote.name}.<br>"

            discount_message += bundle_response_message

            result_payload["updated_message"] = discount_message
            result_payload["status"] = "success"
            result.append(result_payload)
        except Exception as e:
            result_payload["error"] = f"Error adding product {sku}/{name}: {str(e)}"
            logging.error(f"❌ Error adding product {sku}/{name}: {str(e)}")
            result.append(result_payload)

    return result

# ----------- UPDATE QUOTE LINE ----------- #

def handle_quote_line_update_request(extracted_updates, quote, response_message):

    logging.info(f"=>>>>>>>>>>>>>>>>>>>> 🛠️ Creating record for update products 🛠️")

    # ✅ Add products to the quote if provided
    updated_products = []

    for index, item in enumerate(extracted_updates, start=1):

        sku = item.get("sku", None)
        name = item.get("name", None)
        field = item.get("field", None)
        value = item.get("value", None)


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
            response_message += f"⚠️ Error: No field to update was detected in your request. Please specify which attribute (e.g., quantity, discount or term) you want to modify.<br><br>"
            continue

        if field not in field_labels:
            response_message += f"⚠️ Error: No valid field to update was detected in your request. Please specify which attribute (e.g., quantity, discount or term) you want to modify.<br><br>"
            continue

        if value is None:
            response_message += f"⚠️ Error: No value was detected in your request. Please specify the new value for the update.<br><br>"
            continue

        try:
            numeric_value = Decimal(value)
        except (InvalidOperation, ValueError, TypeError):
            response_message += f"⚠️ Error: The value \"{value}\" is not a valid number. Please enter a valid numeric value.<br><br>"
            continue

        if field.startswith("discount") and Decimal(value) < 0:
            response_message += f"⚠️ Error: The value for discounts cannot be less than 0. Please provide a valid number.<br><br>"
            continue

        if field == "term" and int(value) < 0:
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

def handle_line_items_updates(user, completed_updates, quote):

    logging.info(f"=>>>>>>>>>>>>>>>>>>>> 🛠️ Handling line items updates 🛠️")

    result = []

    for index, item in enumerate(completed_updates, start=1):

        result_payload = {
            "product": item,
            "status": "fail",
            "error": None
        }

        print(f"Este es el item: {item}")

        sku = item.get("sku", None)
        name = item.get("name", None)
        fields = item.get("fields", None)

        quantity = fields.get("quantity", None)
        discount_type = fields.get("discount_type", None)
        discount_percentage = fields.get("discount_percentage", None)
        discount_amount = fields.get("discount_amount", None)
        term = fields.get("term", None)

        # ------------------------
        # General field validations
        # ------------------------
        if sku is None and name is None:
            result_payload["error"] = "Error: No SKU/Name was detected in your request. Please specify the product code(s) to update."
            result.append(result_payload)
            continue

        # Check if at least one field to update is provided
        if all(v is None for v in [quantity, discount_percentage, discount_amount, term]):
            result_payload["error"] = "Error: None of the fields (quantity, discount_percentage, discount_amount, term) have a value to update."
            result.append(result_payload)
            continue

        # Quantity validations
        if quantity is not None:
            if not isinstance(quantity, int):
                result_payload["error"] = "Error: Quantity must be an integer."
                result.append(result_payload)
                continue
            if quantity == 0:
                result_payload["error"] = "Error: Quantity cannot be 0."
                result.append(result_payload)
                continue
            if quantity < 0:
                result_payload["error"] = "Error: Quantity cannot be negative."
                result.append(result_payload)
                continue

        # Discount validations
        if discount_percentage is not None:
            if not isinstance(discount_percentage, (int, float, Decimal)):
                result_payload["error"] = "Error: Discount percentage must be a number."
                result.append(result_payload)
                continue
            if discount_percentage < 0:
                result_payload["error"] = "Error: Discount percentage cannot be negative."
                result.append(result_payload)
                continue
            if discount_percentage > 100:
                result_payload["error"] = "Error: Discount percentage cannot exceed 100%."
                result.append(result_payload)
                continue

        if discount_amount is not None:
            if not isinstance(discount_amount, (int, float, Decimal)):
                result_payload["error"] = "Error: Discount amount must be a number."
                result.append(result_payload)
                continue
            if discount_amount < 0:
                result_payload["error"] = "Error: Discount amount cannot be negative."
                result.append(result_payload)
                continue

        # Term validations
        if term is not None:
            if not isinstance(term, (int, float, Decimal)):
                result_payload["error"] = "Error: Term must be a number."
                result.append(result_payload)
                continue
            if term < 0 or term > 12:
                result_payload["error"] = "Error: Term must be between 0 and 12 months."
                result.append(result_payload)
                continue

        # --------------------------------------------
        # Check if product exists and normalize fields
        # --------------------------------------------
        product, sku, name = find_product_and_normalize_variables(sku, name)
        if product is None:
            result_payload["error"] = "Error: Product not found in the catalog."
            result.append(result_payload)
            continue

        # --------------------------------------------
        # Check if product exists in the current quote
        # --------------------------------------------
        try:
            line_item = quote.quote_lines.get(product=product)
        except QuoteLine.DoesNotExist:
            result_payload["error"] = "Error: Product not found in the current quote."
            result.append(result_payload)
            continue

        # Discount amount cannot exceed unit_price
        if discount_amount is not None and discount_amount > line_item.unit_price:
            result_payload["error"] = f"Error: Discount amount cannot exceed the unit price ({line_item.unit_price})."
            result.append(result_payload)
            continue

        if term and not line_item.is_subscription:
            result_payload["error"] = f"Error: You cannot add a term to a product that is not a subscription."
            result.append(result_payload)
            continue

        # Subscription-specific term validations
        if line_item.is_subscription:
            # If term is not provided, default to 12
            if term is None:
                term = 12

            if term < 0 or term > 12:
                result_payload["error"] = "Error: Term for subscription must be between 1 and 12 months."
                result.append(result_payload)
                continue

        update_payload = {
            "quantity": quantity,
            "discount_percentage": discount_percentage,
            "discount_amount": discount_amount,
            "term": term
        }

        # ✅ Create product record
        response = update_quote_line_record(user, update_payload, line_item, quote)

        if response["success"]:
            result_payload["status"] = "success"
        else:
            result_payload["error"] = response["message"]

        result.append(result_payload)

    return result
