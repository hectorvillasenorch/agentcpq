import logging
from cpq.models import Quote, QuoteLine

def normalize_term_for_product(product, term):
    if product.is_subscription:
        term = 1 if term is None else int(term)
    else:
        term = None

    return term

def get_quote_details(quote):

    return {
        "quote_id": quote.id,
        "quote_name": quote.name,
        "subtotal": str(quote.subtotal),
        "net_amount": str(quote.net_amount),
        "status": quote.status,
        "account": quote.account.name if quote.account else "N/A",
        "opportunity": quote.opportunity.name if quote.opportunity else "N/A",
        "created_at": quote.created_at.isoformat() if quote.created_at else '',
        "expiration_date": quote.expiration_date.isoformat() if quote.expiration_date else '',
        "discount_type": str(quote.discount_type),
        "discount_amount": str(quote.discount_amount),
        "discount_percentage": str(quote.discount_percentage),
        "line_items": [
            {
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
            for ql in QuoteLine.objects.filter(quote=quote)
        ]
    }


def build_temp_quote_line(quote, product, quantity, discount_type, discount_amount, term):
    """
    Builds a temporary instance of QuoteLine without saving it to the database.
    Used to validate rules before creating it.
    """
    temp_line = QuoteLine(
        quote=quote,
        product=product,
        quantity=quantity,
        discount_type=discount_type,
        discount_percentage=discount_amount if discount_type == "percentage" else 0,
        discount_amount=discount_amount if discount_type == "amount" else 0,
        unit_price=product.price,
        is_subscription=product.is_subscription,
        term=term
    )

    if not temp_line.product_name:
        temp_line.product_name = product.name
    if not temp_line.sku:
        temp_line.sku = product.sku

    # Aplica los cálculos de descuento, subtotal y total
    temp_line.update_discount_fields()
    temp_line.update_subtotal()
    temp_line.update_total_price()

    return temp_line

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