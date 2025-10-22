import openai
import os
import json
import logging

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"
client = openai.OpenAI(api_key=OPENAI_API_KEY)

from ..orchestrator.context_handle_helpers import estimate_cost


def extract_product_data_with_llm(user_message, current_state, previous_summary=None):
    """
    Uses LLM to extract structured product data from user input.
    Returns JSON, tokens used, and estimated cost.
    """
    system_prompt = """
    You are a helpful AI assistant that extracts product data from user messages.
    Always return JSON with structure:
    {
      "create_product": [
        {
          "data": {
            "name": null,
            "sku": null,
            "price": null,
            "description": null,
            "is_bundle": null,
            "is_subscription": null,
            "term": null,
            "family": null
          },
          "completed": false
        }
      ],
      "agent_message": "string",
      "summary": "string"
    }
    Rules:
    - Required fields: name, sku and price.
    - Optional: description, is_subscription, term, family.
    - Assume that the product will not be a subscription or a bundle unless the user indicates otherwise.
    - If product is bundle (is_bundle = True, the required fields would now be name and sku, price is not necessary and you can mark completed as True if they are already configured.)
    - If product is bundle (is_bundle =  True) set price as 0, and if name and sku are provided by the user, mark completed as true.
    - completed=true only if required fields are present.
    - agent_message should be short, friendly, professional, emoji-rich, ask follow-ups.
    - This message is a continuation of an ongoing conversation. Do NOT start with greetings like 'Hello' or 'Hi'. Just continue naturally.
    - The message is sensitive to HTML tags, so if you want to make line breaks use the <br> tag.
    - Do NOT use emojis for message.
    - Create a short, detailed summary with the previous summary + the changes you made in this iteration.
    """

    user_prompt = f"""
    User message: "{user_message}"

    Current state:
    {json.dumps(current_state, indent=2)}

    Previous summary:
    {previous_summary if previous_summary else "None"}

    Return JSON as described above.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 FIRST LLM - Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=1
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

    try:
        result_json = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
        return None, tokens_used, cost_est

    # Normalize structure
    normalized_products = []
    for prod in result_json.get("create_product", []):
        normalized_products.append({
            "data": {
                "name": prod.get("data", {}).get("name") or prod.get("name"),
                "sku": prod.get("data", {}).get("sku") or prod.get("sku"),
                "price": prod.get("data", {}).get("price") or prod.get("price"),
                "description": prod.get("data", {}).get("description"),
                "is_bundle": prod.get("data", {}).get("is_bundle"),
                "is_subscription": prod.get("data", {}).get("is_subscription"),
                "term": prod.get("data", {}).get("term"),
                "family": prod.get("data", {}).get("family")
            },
            "completed": prod.get("data", {}).get("completed", prod.get("completed", False))
        })
    result_json["create_product"] = normalized_products

    return result_json, tokens_used, cost_est


def generate_final_product_message(completed_products, db_results, remaining_products, previous_summary):
    """
    Generates in ONE LLM call:
    1) A concise, professional, emoji-rich message for the user.
    2) An updated short summary that extends the previous summary with changes from this iteration.
    Returns (message_text, updated_summary, tokens_used, cost_est).
    """

    successful = [r['product'] for r in db_results if r['status'] == 'success']
    failed = [(r['product'], r['error']) for r in db_results if r['status'] == 'fail']

    final_prompt = f"""
    This is an ongoing conversation about product creation.
    The assistant should return a JSON with two fields only: "message" and "summary".

    Context:
    - User initially wanted to create these products: {completed_products}.
    - Products successfully saved: {successful}.
    - Products failed to save (with errors): {failed}.
    - Products still incomplete: {remaining_products}.
    - Previous summary: {previous_summary}.

    Instructions for "message":
    - Be should be short friendly, professional, emoji-rich, ask follow-ups, concise but specific and friendly.
    - For successful products, do NOT list them one by one. Instead, summarize them in ONE short sentence.
    - For failed products, mention the product and its error, but only if there are any.
    - For incomplete products, list the fields you already have and those that are missing for each product.
    - Omit entire sections if there are no products in that category.
    - End by asking a short, natural follow-up question about next steps.
    - The message is sensitive to HTML tags, so if you want to make line breaks use the <br> tag.
    - Keep it user-facing.

    Instructions for "summary":
    - Write a short but detailed summary that continues the previous summary with the new changes.
    - Summarize successes, failures, and incompletes in 2–4 sentences max.
    - The summary is NOT for the user directly, it's for keeping track of progress across iterations.

    ⚠️ IMPORTANT: Return ONLY valid JSON in this format:
    {{
        "message": "...",
        "summary": "..."
    }}
    """

    messages_for_llm = [
        {"role": "system", "content": "You are a concise and friendly AI assistant for CPQ product creation."},
        {"role": "user", "content": final_prompt}
    ]

    tokens_used, cost_est = estimate_cost(messages_for_llm, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages_for_llm,
        temperature=0.7,
        response_format={"type": "json_object"}  # fuerza JSON válido (si usas GPT-4.1 / GPT-4o / GPT-5)
    )

    raw_output = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT JSON Response Final Product Message: {raw_output}\n\n")

    try:
        parsed = json.loads(raw_output)
        message = parsed.get("message", "").strip()
        updated_summary = parsed.get("summary", "").strip()
    except Exception as e:
        logging.error(f"❌ Error parsing LLM JSON output: {e}")
        message = raw_output
        updated_summary = previous_summary

    return message, updated_summary, tokens_used, cost_est
