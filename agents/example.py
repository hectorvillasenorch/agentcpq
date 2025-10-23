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







def extract_quote_line_updates_with_llm(user_message, current_state, previous_summary=None, line_items_on_user_message=None):
    """
    Uses LLM to extract structured quote line updates from user input.
    Returns JSON, tokens used, and estimated cost.
    """

    allowed_fields_str = '", "'.join(["quantity", "discount_amount", "discount_percentage", "term"])

    system_prompt = """
    You are a helpful AI assistant that updates quote line items from user messages.
    Always return JSON with structure:
    {
    "update_quote_line": [
        {
            "data": {
                "sku": null,
                "name": null,
                "field": null,
                "value": null
            },
            "completed": false
        }
    ],
    "agent_message": "string",
    "summary": "string"
    }


    Rules:
    1. I will provide you with a list of dictionaries containing the line items mentioned by the user in their message under "Current line items mentioned." Your task is to modify only the field the user specifies with the values they provide.

    2. If the user attempts to modify a line item that is not found in "Current line items mentioned," indicate in the agent_message that the product is not in the quote.

    """

    system_prompt += f"""
    3. Modify only the field mentioned by the user, the only fields can be updated are: {allowed_fields_str}
    """

    system_prompt += """
    4. If the user attempts to do anything other than update a line item, do not modify any data and indicate in the agent_message that this agent can only update a line item/quote_lines.

    5. For discounts, if the user specifies a percentage (e.g., "15% discount"), return field: "discount_percentage" and value: 15. If the user specifies a dollar amount (e.g., "$150 off" or "150 dollars discount"), return field: "discount_amount" and value: 150. Always extract only the numeric value - remove symbols like % or $, and ignore words like "off", "discount" or "dollars".

    6. Always normalize discount values to plain numbers.

    7. If the user's intention is to delete the value of a field, set that value to 0.


    9. Mark "completed" as true if a line item receives an update, provided it is within the following parameters:
    - quantity: integer >= 0
    - term: integer between 1 and 12
    - discount_percentage: between 0 and 100
    - discount_amount: >= 0 and <= unit_price (if unit_price is provided)

    10. Support flexible update actions: add, remove, delete, multiply, double, divide, among others.

    11. When the user provides multiple updates (e.g., apply a discount and change a quantity),
        you MUST return one entry per update in the array `update_quote_line`.

    - Only update the fields explicitly mentioned by the user.
    - Do not include unchanged information in the agent_message.
    - Only include line items in "update_quote_line" if at least one field is actually modified. Do not include line items where no changes were applied.
    - If a line item has no changes, do not include it in update_quote_line


    Agent message:
    - Interpret this as an attempt, therefore do not say things like 'has been successfully updated'.
    - If no products or quote lines are mentioned in "Current line items mentioned", respond naturally asking the user which products they want to update. Use language that a regular user would understand, without emphasizing technical or internal terms. It's okay to mention 'quote lines' if it helps clarity, but keep the message user-friendly.
    - Generate a natural response for the user explaining what happened: updates, errors, missing information, questions for the user, requests for data, etc.
    - Short, professional, natural.
    - Don't be technical.
    - Continue naturally (do NOT start with 'Hello' or 'Hi')
    - Use <br> for line breaks
    - Include information if the user tried to update a product that does not exist.
    - Do not explain if there are no failed or incomplete quote lines.
    - If the user requests to modify a field but the value would be the same as the existing one, explain naturally that no changes were applied because the value is already the same.

    Summary:
    - Create a short summary combining previous summary + this iteration.
    """


    user_prompt = f"""
    User message: "{user_message}"

    Current line items mentioned:
    {json.dumps(line_items_on_user_message, indent=2)}

    Previous summary:
    {previous_summary if previous_summary else "None"}

    Return JSON as described above.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 LLM - Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.8
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

    # 🔹 Use the reusable cleaning function
    result_json = clean_llm_json(raw_response)
    if result_json is None:
        logging.error("❌ Failed to clean/parse LLM JSON response.")
        return None, tokens_used, cost_est

    # Normalize structure
    normalized_updates = []
    for item in result_json.get("update_quote_line", []):
        data = item.get("data", {})

        # Si 'data' es lista, tomamos el primer dict
        if isinstance(data, list) and data:
            data = data[0]

        normalized_updates.append({
            "data": {
                "sku": data.get("sku"),
                "name": data.get("name"),
                "field": data.get("field"),
                "value": data.get("value")
            },
            "completed": item.get("completed", False)
        })

    result_json["update_quote_line"] = normalized_updates

    return result_json, tokens_used, cost_est