import logging
import json
import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from datetime import datetime
from reportlab.lib.colors import HexColor, red
from io import BytesIO
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from cpq.models import CustomFieldValue, CustomField, QuoteDocumentSettings, Tenant, Quote, QuoteLine, QuoteDocument
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
# DB Helpers
from .db_helpers import get_or_create_quote_ui_render, log_action_usage
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

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
            "description": ql.description,
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
                for quote_line in QuoteLine.objects.filter(quote=quote):
                    # If Product has custom fields, then create custom fields to QuoteLine
                    copy_custom_fields_values_from_product_to_quote_line(quote_line)
                return quote
            except Quote.DoesNotExist:
                return {"message": f"⚠️ Session references a non-existent quote. Please provide a valid quote name."}
    else:
        # ✅ Search for the quote by name
        try:
            quote = Quote.objects.get(name=quote_name)
            logging.info(f"🟢 Found and set active quote: {quote.name}")
            for quote_line in QuoteLine.objects.filter(quote=quote):
                # If Product has custom fields, then create custom fields to QuoteLine
                copy_custom_fields_values_from_product_to_quote_line(quote_line)
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

def get_document_pdf(quote):
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
        # pdf_path = os.path.join(settings.MEDIA_ROOT, "quote_documents", pdf_filename)

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

            # Configuramos el espacio para cada columna de 512 (tamaño del espacio) / la cantidad de columnas a imprimir (MAX 6)
            column_spacing = 512 / len(template.rendered_fields)
            print(f"Column Spacing: {column_spacing}")

            # Renderizamos los encabezados de la tabla
            for index, field in enumerate(template.rendered_fields):
                # Imprimimos los encabezados de las columnas
                # 🔤 Si es un campo compuesto como "Product.UOM", mostramos solo "UOM"
                display_field = field.split(".")[1] if "." in field else field
                # Obtenemos la posición en la que va a iniciar el texto de la columna
                column_x_position = x_position + index * column_spacing
                # Calculamos el ancho real del texto del encabezado
                text_width = pdf.stringWidth(display_field, "Helvetica-Bold", 10)
                last_index = len(template.rendered_fields) - 1

                # Alineaciones
                if index == 0:
                    aligned_x = column_x_position
                elif index == last_index:
                    aligned_x = column_x_position + column_spacing - text_width
                else:
                    aligned_x = column_x_position + (column_spacing - text_width) / 2

                # Imprimir el texto del encabezado
                pdf.drawString(aligned_x, y_position, display_field)

                ##########################################################
                # Descomenta las siguientes lineas para mostrar el limite horizontal de cada encabezado de columna
                #pdf.setStrokeColor(HexColor("#2d14ff"))
                #pdf.setLineWidth(1)
                #pdf.line(column_x_position, y_position - 5, column_x_position, y_position + 5)
                #pdf.line(column_x_position + column_spacing, y_position - 5, column_x_position + column_spacing, y_position + 5)
                ##########################################################

            # Le quitamos 15 puntos a Y para imprimir la linea divisora
            y_position -= 15
            # ------------------------------------ Imprimimos la linea divisora
            pdf.setStrokeColor(HexColor(SCOLOR))
            pdf.setLineWidth(2)
            pdf.line(50, y_position, 562, y_position)
            # Restamos 27 puntos para comenzar a imprimir los elementos de la tabla
            y_position -= 27

            FIELD_MAP = {
                "Product And SKU": lambda line: max([line.product_name or "", line.sku or ""], key=len),
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

            for line in quote_lines.all():
                if y_position < 70:  # Si nos acercamos al final de la hoja reseteamos los encabezados
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

                    # Renderizamos los encabezados de la tabla
                    for index, field in enumerate(template.rendered_fields):
                        # 🔤 Si es un campo compuesto como "Product.UOM", mostramos solo "UOM"
                        display_field = field.split(".")[1] if "." in field else field

                        # Obtenemos la posición en la que va a iniciar el texto de la columna
                        column_x_position = x_position + index * column_spacing
                        # Calculamos el ancho real del texto del encabezado
                        text_width = pdf.stringWidth(display_field, "Helvetica-Bold", 10)
                        last_index = len(template.rendered_fields) - 1

                        # Alineaciones
                        if index == 0:
                            aligned_x = column_x_position
                        elif index == last_index:
                            aligned_x = column_x_position + column_spacing - text_width
                        else:
                            aligned_x = column_x_position + (column_spacing - text_width) / 2

                        # Imprimir el texto del encabezado
                        pdf.drawString(aligned_x, y_position, display_field)
                    
                    y_position -= 15
                    # ------------------------------------
                    pdf.setStrokeColor(HexColor(SCOLOR))
                    pdf.setLineWidth(2)
                    pdf.line(50, y_position, 562, y_position) 
                    y_position -= 27
            
                # Configuramos una variable para saber el tamaño maximo en el eje Y del texto mas grande de la linea
                max_text_height = 0
                for index, field_title in enumerate(template.rendered_fields):
                    column_x = x_position + index * column_spacing # Inicio del valor de la columna correspondiente
                    #print(f"Col X: {column_x}")
                    last_index = len(template.rendered_fields) - 1 # Para saber si es el ultimo valor

                    ########################################################
                    # Descomenta las siguientes lineas para mostrar el limite horizontal de cada columna
                    #pdf.setStrokeColor(HexColor("#2d14ff"))
                    #pdf.setLineWidth(1)
                    #pdf.line(column_x, y_position - 5, column_x, y_position + 5)
                    #pdf.line(column_x + column_spacing, y_position - 5, column_x + column_spacing, y_position + 5)
                    ########################################################

                    # Imprimimos diferente para Product And SKU porque se van a imprimir ambos valores (SKU y Product Name)
                    if field_title == "Product And SKU":
                        sku = line.sku or ""
                        product = line.product_name or ""

                        max_width = column_spacing - 5 # Definimos el tamaño maximo que puede ocupar el texto
                        sku_font_size = 10 # Tamaño de fuente del texto SKU
                        product_font_size = 9 # Tamaño de fuente del texto Product Name

                        # Comparamos que el valor del texto SKU no sea mas grande que el tamaño maximo de la columna
                        sku_text_width = pdf.stringWidth(sku, "Helvetica-Bold", sku_font_size)
                        if sku_text_width > max_width:
                            sku_font_size = max(6, int(sku_font_size * max_width / sku_text_width))
                            sku_text_width = pdf.stringWidth(sku, "Helvetica-Bold", sku_font_size)

                        # Comparamos que el valor del texto Product Name no sea mas grande que el tamaño maximo de la columna
                        product_text_width = pdf.stringWidth(product, "Helvetica", product_font_size)
                        if product_text_width > max_width:
                            product_font_size = max(6, int(product_font_size * max_width / product_text_width))
                            product_text_width = pdf.stringWidth(product, "Helvetica", product_font_size)

                        # Si Product And SKU está al inicio
                        if index == 0:
                            aligned_x = column_x
                            pdf.setFont("Helvetica-Bold", sku_font_size)
                            pdf.setFillColor(HexColor("#000000"))
                            pdf.drawString(aligned_x, y_position, sku)
                            pdf.setFont("Helvetica", product_font_size)
                            pdf.setFillColor(HexColor("#666666"))  
                            pdf.drawString(aligned_x, y_position - 10, product)

                        # Si Product And SKU está al final
                        elif index == last_index:
                            sku_aligned_x = column_x + column_spacing - sku_text_width
                            pdf.setFont("Helvetica-Bold", sku_font_size)
                            pdf.setFillColor(HexColor("#000000"))
                            pdf.drawString(sku_aligned_x, y_position, sku)

                            name_aligned_x = column_x + column_spacing - product_text_width
                            pdf.setFont("Helvetica", product_font_size)
                            pdf.setFillColor(HexColor("#666666"))  
                            pdf.drawString(name_aligned_x, y_position - 10, product)
                        
                        # Si Product And SKU está en medio
                        else:
                            sku_aligned_x = column_x + (column_spacing - sku_text_width) / 2
                            pdf.setFont("Helvetica-Bold", sku_font_size)
                            pdf.setFillColor(HexColor("#000000"))
                            pdf.drawString(sku_aligned_x, y_position, sku)
                            name_aligned_x = column_x + (column_spacing - product_text_width) / 2
                            pdf.setFont("Helvetica", product_font_size)
                            pdf.setFillColor(HexColor("#666666"))  
                            pdf.drawString(name_aligned_x, y_position - 10, product)
                    else:
                        # Se imprime para el resto de campos
                        # 🔍 Obtener el contenido dinámicamente desde el FIELD_MAP
                        if field_title in FIELD_MAP:
                            field_value = FIELD_MAP[field_title](line)

                        # 🔍 Caso: campos personalizados tipo "Model.Label"
                        elif "." in field_title:
                            model_name, field_label = field_title.split(".", 1)
                            try:
                                # Buscar el CustomField correspondiente
                                custom_field = CustomField.objects.get(object_type=model_name, label=field_label)
                                
                                # Buscar el CustomFieldValue en la línea de cotización
                                ct = ContentType.objects.get_for_model(line)
                                custom_value = CustomFieldValue.objects.get(
                                    content_type=ct,
                                    object_id=line.id,
                                    field=custom_field
                                )
                                field_value = custom_value.value
                            except CustomField.DoesNotExist:
                                field_value = f"[Missing field: {model_name}.{field_label}]"
                            except CustomFieldValue.DoesNotExist:
                                field_value = "---"
                        else:
                            field_value = "---"

                        # 🧱 Configuración base
                        font_name = "Helvetica"
                        max_font_size = 9
                        min_font_size = 9
                        max_width = column_spacing - 5
                        line_spacing = 10  # Espacio entre líneas
                        is_short = field_title == "Description" and template.line_description_detail_level == 'short'
                        max_lines = 3 if is_short else 100

                        # 🔁 Ajuste dinámico de fuente y envoltura
                        font_size = max_font_size
                        wrapped_lines = []

                        while font_size >= min_font_size:
                            words = field_value.split()
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

                        # ✂️ Agregar puntos suspensivos si se pasa del límite
                        if is_short and len(wrapped_lines) > max_lines:
                            wrapped_lines = wrapped_lines[:max_lines]
                            last_line = wrapped_lines[-1]
                            ellipsis = "..."
                            while pdf.stringWidth(last_line + ellipsis, font_name, font_size) > max_width and len(last_line) > 0:
                                last_line = last_line[:-1]
                            wrapped_lines[-1] = last_line.strip() + ellipsis

                        # 🖊️ Dibujar cada línea alineada
                        pdf.setFont(font_name, font_size)
                        pdf.setFillColor(HexColor("#000000"))
                        for i, wrapped_line in enumerate(wrapped_lines):
                            y = y_position - i * line_spacing

                            # Alineación horizontal
                            text_width = pdf.stringWidth(wrapped_line, font_name, font_size)
                            if index == 0:
                                aligned_x = column_x
                            elif index == last_index:
                                aligned_x = column_x + column_spacing - text_width
                            else:
                                aligned_x = column_x + (column_spacing - text_width) / 2

                            pdf.drawString(aligned_x, y, wrapped_line)

                        text_height = len(wrapped_lines) * line_spacing + 5
                        
                        # Imprimir term y discount en caso que el campo sea Total Price
                        #print(f"Field: {field_title}")
                        if field_title == "Total Price":
                            total_price_description_font_size = 8
                            if template.show_subscription_term and line.term is not None:
                                #print(f"Si entra a term")
                                y = y_position - text_height + 3
                                pdf.setFillColor(HexColor("#666666"))

                                # Get term text
                                monthly_total = f"${(line.subtotal * line.quantity):,.2f} /mo"
                                term_text = f"for {line.term} months"

                                montly_text_width = pdf.stringWidth(monthly_total, "Helvetica", total_price_description_font_size)
                                term_text_width = pdf.stringWidth(term_text, "Helvetica", total_price_description_font_size)

                                # Align depending last field
                                if index == 0:
                                    term_x = column_x
                                    monthly_x = column_x
                                elif index == last_index:
                                    term_x = column_x + column_spacing - term_text_width  # Right align
                                    monthly_x = column_x + column_spacing - montly_text_width
                                else:
                                    term_x = column_x + (column_spacing - term_text_width) / 2  # Centered
                                    monthly_x = column_x + (column_spacing - montly_text_width) / 2

                                pdf.setFont("Helvetica", total_price_description_font_size)
                                # Imprimir cantidad al mes
                                pdf.drawString(monthly_x, y, monthly_total)
                                # Imprimir el termino
                                pdf.drawString(term_x, y - line_spacing, term_text)

                                text_height += (line_spacing * 2)

                            if template.show_line_discount and (line.discount_percentage > 0 and line.discount_amount > 0):
                                y = y_position - text_height + 3
                                pdf.setFillColor(HexColor("#666666"))

                                # Get discount text
                                discount_text = (
                                    f"after a {line.discount_percentage:.2f}% discount"
                                    if line.discount_type == "percentage"
                                    else f"after a ${line.discount_amount:,.2f} discount"
                                )

                                # Text's width
                                discount_text_width = pdf.stringWidth(discount_text, "Helvetica", total_price_description_font_size)

                                # Align depending last field
                                if index == 0:
                                    discount_x = column_x
                                elif index == last_index:
                                    discount_x = column_x + column_spacing - discount_text_width  # Right align
                                else:
                                    discount_x = column_x + (column_spacing - discount_text_width) / 2  # Centered

                                pdf.setFont("Helvetica", total_price_description_font_size)
                                pdf.drawString(discount_x, y, discount_text)

                                text_height += line_spacing

                        # Guardar el texto mas largo en el eje Y para despues dejar el espacio para la siguiente fila
                        if text_height > max_text_height:
                            max_text_height = text_height

                y_position -= max_text_height + 15

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

        # 2. Create ContentFile
        buffer.seek(0)
        file_content = ContentFile(buffer.read())

        # 3. Define storage path (e.g., tenant_abc123/quote_documents/quote_42_v1.pdf)
        storage_path = f"tenant_{company.id}/quote_documents/{pdf_filename}"

        # 4. Save to R2
        saved_path = default_storage.save(storage_path, file_content)

        # Save QuoteDocument record
        document_record = QuoteDocument.objects.create(
            quote=quote,
            version=next_version,
            name=pdf_filename,
            file=saved_path,  
            generated_by="system"
        )
        logger.debug(f"Saved to R2: {saved_path}")
        logger.debug(f"File size: {file_content.size} bytes")
        return {
            "message": f"📄 Quote PDF (v{next_version}) generated successfully!",
            "download_url": f"{storage_path}",
            "document_version": next_version,
            "success": True,
            }
    except Exception as e:
        return {
            "message": f"⚠️ Error generating PDF: {str(e)}",
            "success": False
            }