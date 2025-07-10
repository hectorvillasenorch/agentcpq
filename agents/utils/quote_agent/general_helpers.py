import logging
import json
from cpq.models import Quote, QuoteLine
from django.contrib.contenttypes.models import ContentType
from cpq.models import CustomFieldValue, CustomField, QuoteDocumentSettings

from .db_helpers import get_or_create_quote_ui_render

def normalize_term_for_product(product, term):
    if product.is_subscription:
        term = 1 if term is None else int(term)
    else:
        term = None

    return term

def get_quote_details(quote):
    # Set custom fields for quote line
    for quote_line in QuoteLine.objects.filter(quote=quote):
        # If Product has custom fields, then create custom fields to QuoteLine
        copy_custom_fields_values_from_product_to_quote_line(quote_line)

    # Add or delete Product Custom Fields into quote document settings
    set_custom_fields_into_quote_document_settings("Product")

    quote_details_settings = get_or_create_quote_ui_render()
    print(f"\nRendered fields on UI Quote Details: {quote_details_settings.rendered_fields}")
    print(f"\nOmitted fields on UI Quote Details: {quote_details_settings.omitted_fields}\n")

    default_fields = [
        'sku_product', 'quantity', 'unit_price', 'discount_percentage',
        'discount_amount', 'subscription', 'term', 'total_price'
    ]

    # Filtrar campos custom de rendered_fields
    custom_rendered_fields = [
        field for field in quote_details_settings.rendered_fields
        if field not in default_fields and '.' in field
    ]

    # Mapeo: "Product.UOM" ➞ { object_type: "Product", label: "UOM" }
    custom_field_labels = []
    for field in custom_rendered_fields:
        try:
            object_type, label = field.split('.', 1)
            custom_field_labels.append((object_type, label))
        except ValueError:
            continue

    # Buscar CustomFields que coincidan con object_type y label
    matched_custom_fields = CustomField.objects.filter(
        object_type__in=[t[0] for t in custom_field_labels],
        label__in=[t[1] for t in custom_field_labels]
    )

    # Crear un mapeo: (object_type, label) ➞ CustomField instance
    field_lookup = {(cf.object_type, cf.label): cf for cf in matched_custom_fields}

    # Obtener ContentType de QuoteLine
    quote_line_ct = ContentType.objects.get_for_model(QuoteLine)

    # Construir los line_items
    line_items = []
    for ql in QuoteLine.objects.filter(quote=quote):
        line_data = {
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

        # Agregar los campos custom
        for object_type, label in custom_field_labels:
            custom_field = field_lookup.get((object_type, label))
            if custom_field:
                cfv = CustomFieldValue.objects.filter(
                    content_type=quote_line_ct,
                    object_id=ql.id,
                    field=custom_field
                ).first()
                if cfv:
                    # Usa el label como clave
                    line_data[label] = cfv.value

        line_items.append(line_data)

    return {
        "rendered_fields": quote_details_settings.rendered_fields,
        "quote_id": quote.id,
        "quote_name": quote.name,
        "status": quote.status,
        "subtotal": str(quote.subtotal) if quote_details_settings.show_quote_subtotal else None,
        "net_amount": str(quote.net_amount) if quote_details_settings.show_quote_net_amount else None,
        "account": quote.account.name if quote_details_settings.show_quote_account and quote.account else None,
        "opportunity": quote.opportunity.name if quote_details_settings.show_quote_opportunity and quote.opportunity else None,
        "created_at": quote.created_at.isoformat() if quote_details_settings.show_quote_created_at and quote.created_at else None,
        "expiration_date": quote.expiration_date.isoformat() if quote_details_settings.show_quote_expires_at and quote.expiration_date else None,
        "discount_type": str(quote.discount_type) if quote_details_settings.show_quote_discount else None,
        "discount_amount": str(quote.discount_amount) if quote_details_settings.show_quote_discount else None,
        "discount_percentage": str(quote.discount_percentage) if quote_details_settings.show_quote_discount else None,
        "line_items": line_items
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

def set_active_quote_to_session_data(session_data, quote):
    session_data["active_quote"] = {
        "quote_id": quote.id,
        "quote_name": quote.name,
        "account": quote.account.name if quote.account else "N/A",
        "opportunity": quote.opportunity.name if quote.opportunity else "N/A"
    }

def extract_quote_name(user_message):
    """Extracts the quote name from user input."""
    import re
    match = re.search(r"\bQ-\d{4,}\b", user_message, re.IGNORECASE)
    return match.group(0) if match else None

def get_backup_value_from_quote_line(json_payload, quote):
    # Transform to valid JSON
    update_line = json.loads(json_payload)

    # Get quote line item from db
    quote_line = QuoteLine.objects.get(id=update_line["quote_line_id"], quote=quote)

    field = update_line["field"]

    if field in {"quantity", "term", "unit_price", "discount_percentage", "discount_amount"}:
        value = getattr(quote_line, field)

    return float(value)

def format_currency(value):
    """Formats a Decimal value into currency format with commas and two decimal places."""
    return f"{value:,.2f}"  # Example: 3,000.00 instead of 3000.0

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

def copy_custom_fields_values_from_product_to_quote_line(quote_line):
    product = quote_line.product
    product_ct = ContentType.objects.get_for_model(product)

    custom_fields = CustomFieldValue.objects.filter(
        content_type=product_ct,
        object_id=product.id
    )

    quote_line_ct = ContentType.objects.get_for_model(quote_line)

    for cf in custom_fields:
        cfv, created = CustomFieldValue.objects.get_or_create(
            field=cf.field,
            content_type=quote_line_ct,
            object_id=quote_line.id,
            defaults={
                "value": cf.value,
                "record": None
            }
        )

        if created:
            print(f"✅ Copy: {cf.field.name} = {cf.value}")
        else:
            if cfv.value != cf.value:
                old_value = cfv.value
                cfv.value = cf.value
                cfv.save()
                print(f"🔁 Updated: {cf.field.name} changed from '{old_value}' to '{cf.value}' for quote line {quote_line}")
            else:
                print(f"⚠️ Skipped: Custom field '{cf.field.name}' already up-to-date for quote line {quote_line}.")


def set_custom_fields_into_quote_document_settings(object_type):
    # 1. Obtener los CustomField válidos para ese object_type
    custom_fields = CustomField.objects.filter(object_type=object_type)
    valid_custom_field_labels = {f"{object_type}.{cf.label}" for cf in custom_fields}

    # 2. Obtener la configuración actual
    quote_document_settings = QuoteDocumentSettings.objects.first()
    if not quote_document_settings:
        return 

    rendered_fields = quote_document_settings.rendered_fields or []
    omitted_fields = quote_document_settings.omitted_fields or []

    # 3. Limpiar los campos obsoletos (que ya no están en CustomField)
    rendered_fields = [
        field for field in rendered_fields
        if not field.startswith(f"{object_type}.") or field in valid_custom_field_labels
    ]
    omitted_fields = [
        field for field in omitted_fields
        if not field.startswith(f"{object_type}.") or field in valid_custom_field_labels
    ]

    # 4. Agregar nuevos custom fields que no estén en ninguno de los dos
    for full_label in valid_custom_field_labels:
        if full_label not in rendered_fields and full_label not in omitted_fields:
            omitted_fields.append(full_label)

    # 5. Guardar
    quote_document_settings.rendered_fields = rendered_fields
    quote_document_settings.omitted_fields = omitted_fields
    quote_document_settings.save()