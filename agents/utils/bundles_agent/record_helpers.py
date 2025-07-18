import logging
import json
from cpq.models import Product, Option, QuoteLine
from django.db.models import Q
from django.db import transaction

def handle_bundle_components(extracted_components, response_message):
    logging.info(f"=>>>>>>>>>>>>>>>>>>>> 🛠️ Creating record for bundle components (model option) 🛠️")

    components_created = [] #Model option

    for bundle_index, bundle_item in enumerate(extracted_components, start=1):
        response_message += f"<b>📦 <u>Bundle Request #{bundle_index}</u> 📦</b><br>"

        # Before anything, confirm if bundle exists
        product_bundle_sku = bundle_item.get("bundle_sku", None)
        product_bundle_name = bundle_item.get("bundle_name", None)

        if product_bundle_sku is None and product_bundle_name is None:
            logging.warning(f"⚠️ No bundle product was found in your message. Please provide a bundle SKU or name. Skipping...")
            response_message += f"⚠️ No bundle product was found in your message. Please provide a bundle SKU or name.<br><br>"
            continue

        try:
            bundle = Product.objects.get(Q(is_bundle=True) & (Q(sku=product_bundle_sku) | Q(sku=product_bundle_name) | Q(name=product_bundle_sku) | Q(name=product_bundle_name)))
            logging.info(f"🔍 Parent product (bundle) was found - {bundle.name}")
        except Product.DoesNotExist:
            logging.warning("⚠️ No matching bundle product was found. Skipping...")
            response_message += f"⚠️ No matching bundle product was found for <b>'{product_bundle_sku if product_bundle_sku is not None else product_bundle_name}'</b>. Please verify the name or SKU and try again.<br><br>"
            continue


        bundle_components = bundle_item.get("components", [])

        if not bundle_components:
            logging.warning("⚠️ No components were extracted for this bundle. Skipping...")
            response_message += f"⚠️ No components were extracted for this bundle <b>'{product_bundle_sku if product_bundle_sku is not None else product_bundle_name}'</b>. Please provide at least one product to add (SKU or name). Skipping...</b><br><br>"
            continue

        for index, component in enumerate(bundle_components, start=1):
            response_message += f"<b>🔧 <u>Bundle component #{index} for {bundle.name} bundle</u> 🔧</b><br>"

            product_sku = component.get("product_sku", None)
            product_name = component.get("product_name", None)
            quantity = component.get("quantity", None)
            is_required = component.get("is_required", None)
            min_quantity = component.get("min_quantity", None)
            max_quantity = component.get("max_quantity", None)
            default_selected = component.get("default_selected", None)
            group_name = component.get("group_name", None)

            if product_sku is None and product_name is None:
                logging.warning(f"⚠️ No product component was found in your message. Please provide a product component SKU or name. Skipping...")
                response_message += f"⚠️ No product component was found in your message. Please provide a product component SKU or name. Skipping...</b><br><br>"
                continue

            # Validate if product component exists in database
            try:
                product_component = Product.objects.get(Q(sku=product_sku) | Q(sku=product_name) | Q(name=product_sku) | Q(name=product_name))
                logging.info(f"🔍 Product (component) was found - {product_component.name}")
            except Product.DoesNotExist:
                logging.warning("⚠️ No matching product component was found. Skipping...")
                response_message += f"⚠️ No matching product component was found. Verify your name or sku product component. Skipping...</b><br><br>"
                continue

            # Validate if product component exists in actual bundle
            try:
                product_component_exists = Option.objects.get(parent_product=bundle, product_option=product_component)
            except Option.DoesNotExist:
                product_component_exists = None

            if product_component_exists:
                logging.info(f"=>>>>>>>>>>>>>>>>>>>> 🔁 Product `{product_component.sku}/{product_component.name}` already in bundle. Updating instead of creating.")
                response_message += f"🔁 Product {product_component.sku}/{product_component.name} already in bundle. Updating:<br>"

                # Update quantity (previous quantity + new quantity)
                new_quantity = product_component_exists.quantity + int(quantity)

                # Update quantity
                product_component_exists.quantity = new_quantity
                logging.info(f"☑️ Quantity of {product_component_exists.product_option.name} updated in bundle {bundle.name}")
                response_message += f"☑️ Quantity: {new_quantity}<br>"

                if is_required is not None and is_required != product_component_exists.is_required:
                    product_component_exists.is_required = is_required
                    logging.info(f"☑️ Required of {product_component_exists.product_option.name} updated in bundle {bundle.name}")
                    response_message += f"☑️ Required: {is_required}<br>"

                if min_quantity is not None and min_quantity != product_component_exists.min_quantity:
                    product_component_exists.min_quantity = min_quantity
                    logging.info(f"☑️ Min Quantity of {product_component_exists.product_option.name} updated in bundle {bundle.name}")
                    response_message += f"☑️ Min Quantity: {min_quantity}<br>"
                
                if max_quantity is not None and max_quantity != product_component_exists.max_quantity:
                    product_component_exists.max_quantity = max_quantity
                    logging.info(f"☑️ Max Quantity of {product_component_exists.product_option.name} updated in bundle {bundle.name}")
                    response_message += f"☑️ Max Quantity: {max_quantity}<br>"

                if default_selected is not None and default_selected != product_component_exists.default_selected:
                    product_component_exists.default_selected = default_selected
                    logging.info(f"☑️ Default Selected of {product_component_exists.product_option.name} updated in bundle {bundle.name}")
                    response_message += f"☑️ Default Selected: {default_selected}<br>"

                if group_name is not None and group_name != product_component_exists.group_name:
                    product_component_exists.group_name = group_name
                    logging.info(f"☑️ Group Name of {product_component_exists.product_option.name} updated in bundle {bundle.name}")
                    response_message += f"☑️ Group Name: {group_name}<br>"

                response_message += "<br>"

                product_component_exists.save()

                components_created.append(product_component_exists)

                continue


            response_message += f"🧩 Product: {product_component.name}<br>"
            response_message += f"📦 Bundle: {bundle.name}<br>"

            # ✅ Format response message

            fields = {
                "quantity": quantity,
                "is_required": is_required,
                "min_quantity": min_quantity,
                "max_quantity": max_quantity,
                "default_selected": default_selected,
                "group_name": group_name
            }

            field_emojis = {
                "quantity": "🔢",
                "is_required": "✅",
                "min_quantity": "➖",
                "max_quantity": "➕",
                "default_selected": "☑️",
                "group_name": "🏷️"
            }

            response_message += "<br>"
            for field, value in fields.items():
                if value is not None:
                    field_label = field.replace("_", " ").capitalize()
                    emoji = field_emojis.get(field, "ℹ️")
                    response_message += f"{emoji} {field_label}: {value}<br>"

            # Set default values if no fields are founded
            option = {
                "parent_product_id" : bundle.id,
                "product_option_id" : product_component.id,
                "quantity" : quantity if quantity is not None else 1,
                "is_required" : is_required if is_required is not None else False,
                "min_quantity" : min_quantity if min_quantity is not None else 1,
                "max_quantity" : max_quantity if max_quantity is not None else 10,
                "default_selected" : default_selected if default_selected is not None else True,
                "group_name" : group_name
            }

            logging.warning(f"Trying to create product component (option) for bundle {bundle.name}: {option}")

            #Convert list to valid JSON
            item_json = json.dumps(option)

            response = save_option(item_json)

            if response.get("success"):
                response_message += f"{response.get('message')}<br><br>"
                components_created.append(option)
                logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
            else:
                error_msg = response.get("message", "Unknown error.")
                response_message += f"Error creating option: {error_msg}<br>"
                logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")
        
        bundle.save()

    if components_created:
        return response_message, components_created
    else:
        return response_message, None



def save_option(request):
    try:
        option = json.loads(request)  # Extract JSON array

        parent_product_id = option.get("parent_product_id")
        product_option_id = option.get("product_option_id")
        quantity = option.get("quantity")
        is_required = option.get("is_required")
        min_quantity = option.get("min_quantity")
        max_quantity = option.get("max_quantity")
        default_selected = option.get("default_selected")
        group_name = option.get("group_name")

        try:
            parent_product = Product.objects.get(id=parent_product_id)
        except Product.DoesNotExist:
            return {
            "message": f"Parent product with ID {parent_product_id} was not found in the database.",
            "success": False
        }

        try:
            product_option = Product.objects.get(id=product_option_id)
        except Product.DoesNotExist:
            return {
            "message": f"Product component with ID {product_option_id} was not found in the database.",
            "success": False
        }

        Option.objects.create(
            parent_product=parent_product,
            product_option=product_option,
            quantity=quantity,
            is_required=is_required,
            min_quantity=min_quantity,
            max_quantity=max_quantity,
            default_selected=default_selected,
            group_name=group_name
        )

        response_message = "✅ Product component was successfully added to the bundle."

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
        logging.warning(f"⚠️ Error saving option: {str(e)}")
        return {
            "message": f"Error saving option: {str(e)}",
            "success": False
        }
    
def handle_delete_options_from_quote(extracted_delete_options, response_message, quote):
    logging.info(f"=>>>>>>>>>>>>>>>>>>>> 🗑️ Deleting options from bundle 🗑️")

    options_deleted = [] #Model option

    for bundle_index, bundle_item in enumerate(extracted_delete_options, start=1):
        response_message += f"<b>📦 <u>Bundle Option Removal #{bundle_index}</u> 📦</b><br>"

        # Before anything, confirm if bundle exists
        product_bundle_sku = bundle_item.get("bundle_sku", None)
        product_bundle_name = bundle_item.get("bundle_name", None)

        if product_bundle_sku is None and product_bundle_name is None:
            logging.warning(f"⚠️ No bundle product was found in your message. Please provide a bundle SKU or name. Skipping...")
            response_message += f"⚠️ No bundle product was found in your message. Please provide a bundle SKU or name.<br><br>"
            continue

        try:
            bundle = Product.objects.get(Q(is_bundle=True) & (Q(sku=product_bundle_sku) | Q(sku=product_bundle_name) | Q(name=product_bundle_sku) | Q(name=product_bundle_name)))
            logging.info(f"🔍 Parent product (bundle) was found - {bundle.name}")
        except Product.DoesNotExist:
            logging.warning("⚠️ No matching bundle product was found. Skipping...")
            response_message += f"⚠️ No matching bundle product was found for <b>'{product_bundle_sku if product_bundle_sku is not None else product_bundle_name}'</b>. Please verify the name or SKU and try again.<br><br>"
            continue


        options = bundle_item.get("options", [])

        if not options:
            logging.warning("⚠️ No options were extracted for this bundle. Skipping...")
            response_message += f"⚠️ No options were extracted to delete for this bundle <b>'{product_bundle_sku if product_bundle_sku is not None else product_bundle_name}'</b>. Please provide at least one product to add (SKU or name). Skipping...</b><br><br>"
            continue

        for index, option in enumerate(options, start=1):
            response_message += f"<b>🗑️ <u>Bundle option #{index}</u> 🗑️</b><br>"

            product_sku = option.get("product_sku", None)
            product_name = option.get("product_name", None)

            if product_sku is None and product_name is None:
                logging.warning(f"⚠️ No product option was found in your message. Please provide a product option SKU or name. Skipping...")
                response_message += f"⚠️ No product option was found in your message. Please provide a product option SKU or name. Skipping...</b><br><br>"
                continue

            # Validate if product exists
            try:
                product = Product.objects.get(Q(sku=product_sku) | Q(sku=product_name) | Q(name=product_sku) | Q(name=product_name))
                logging.info(f"🔍 Product was found - {product.name}")
            except Product.DoesNotExist:
                logging.warning("⚠️ No matching product was found. Skipping...")
                response_message += f"⚠️ No matching product was found. Verify your name or sku product. Skipping...</b><br><br>"
                continue

            # Validate if exists a relation between product and bundle
            try:
                option_record = Option.objects.get(parent_product=bundle, product_option=product)
                logging.info(f"🔍 Option has been found between {bundle} and {product}")
            except Option.DoesNotExist:
                logging.warning(f"⚠️ No matching option was found between {bundle} and {product}. Skipping...")
                response_message += f"⚠️ No matching option was found between {bundle} and {product}. Verify your bundle and/or product option. Skipping...</b><br><br>"
                continue

            # Validate if exists any quote line with the product
            try:
                bundle_child_line = QuoteLine.objects.get(product_option=option_record, quote=quote, is_bundle_child=True)
                logging.info(f"🔍 Quote Line has been found. Line: {bundle_child_line}")
            except QuoteLine.DoesNotExist:
                logging.warning(f"⚠️ No quote line was found in quote {quote.name} with the relation between {bundle} and {product}.")
                response_message += f"⚠️ No quote line was found in quote <b>{quote.name}</b> with the relation between <b>{bundle}</b> and <b>{product}</b>. Please verify your bundle and/or product option. Skipping...<br><br>"
                continue

            try:
                if bundle_child_line.product_option.is_required == False:
                    bundle_parent = bundle_child_line.parent_line

                    bundle_child_line.delete()

                    bundle_parent.save()

                    response_message += f"✅ The bundle component was successfully deleted from quote '{quote.name}'.<br>"
                    options_deleted.append(bundle_child_line)
                    continue
                else:
                    response_message += f"🔒 You cannot delete a bundle component if it is marked as required in the bundle.<br>"
                    continue
            except Exception as e:
                response_message += f"⚠️ Something went wrong when triying to delete bundle component. Please try again. Error: {e}"
                continue

    if options_deleted:
        return response_message, options_deleted
    else:
        return response_message, None