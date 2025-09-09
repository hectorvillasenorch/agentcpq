def add_product_to_quote(user, user_message, session_data):
    

    added_products = []
    response_message = ""

    # ✅ Save quote products
    quote, response_message, added_products = save_quote_products(extracted_products, quote, response_message, session_context, allow_updates=True)
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
        response_message += f"{approval_suggestion['message']}"
    else:
        response_message += "⚠️ No approval suggestion."
    
        
    return {
        "message": response_message,
        "update_details": get_quote_details(quote),
        "temporaryMessage": True
    }
