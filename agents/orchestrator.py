import openai
import json
import os
import logging
from agents.quote_agent import create_quote_agent, add_product_to_quote
# from agents.product_agent import product_agent
# from agents.bundles_agent import configure_bundle_agent
# from agents.pricing_agent import apply_discount_agent
# from agents.approvals_agent import submit_for_approval
from dotenv import load_dotenv

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(level=logging.DEBUG)

openai.log = "warning"

def orchestrate_request(user_message, session_data):
    """Dynamically determine next steps based on user request and session context."""
    
    # ✅ Ensure session data is serializable
    session_context = {k: str(v) for k, v in session_data.items() if isinstance(v, (str, int, float, list, dict))}
    
    # ✅ Handle pending actions first
    pending_action = session_data.get("pending_action")

    if pending_action and user_message.strip():
        logging.info(f"🟡 Pending Action Detected: {pending_action}")

        if pending_action == "confirm_opportunity":
          session_data["opportunity"] = user_message.strip()  # Ensure clean input
          session_data["pending_action"] = "add_product"  # ✅ Move to adding products
          return {"message": f"✅ Opportunity `{session_data['opportunity']}` added. Would you like to add products now?"}

        elif pending_action == "add_product":
            return add_product_to_quote(user_message, session_data)  # Add product to existing quote

        # elif pending_action == "apply_discount":
        #     return apply_discount_to_quote(user_message, session_data)  # Apply discount to quote

        # elif pending_action == "provide_dates":
        #     return provide_dates_for_subscription(user_message, session_data)  # Handle subscription dates

    # ✅ No pending actions → Determine new action
    prompt = f"""
    You are an AI assistant that classifies user requests into predefined actions.

    **User Request:** "{user_message}"

    **Current Session Data:** {json.dumps(session_context, indent=2)}

    **Return ONLY one of the following labels (do NOT add explanations):**
    - "CreateQuote"
    - "AddProduct"
    - "ApplyDiscount"
    - "ProvideDates"
    - "GeneralQuery"

    If the request is unclear, return "GeneralQuery".
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Analyze the request and determine next action."},
                {"role": "user", "content": prompt}
            ]
        )

        decision = response.choices[0].message.content.strip().replace('"', '')
        logging.info(f"🟢 AI Decision Received: {decision} (Type: {type(decision)})")

    except Exception as e:
        logging.error(f"❌ Error in OpenAI call: {e}")
        return {"message": "⚠️ Sorry, an error occurred while processing your request."}

    # ✅ Route all quote-related actions to the Quote Agent
    if decision == "CreateQuote":
      return create_quote_agent(user_message, session_data)

    if decision == "AddProduct":
        return add_product_to_quote(user_message, session_data)  # ✅ Separate AddProduct logic

    # if decision in ["ApplyDiscount", "ProvideDates"]:
    #     return modify_quote_details(user_message, session_data)  # ✅ Placeholder function

    # ✅ Handle general queries
    if decision == "GeneralQuery":
        return query_gpt_for_general_response(user_message)

    logging.warning(f"⚠️ AI returned an unknown intent: {decision}")
    return {"message": "🤖 Sorry, I couldn’t understand your request."}

def query_gpt_for_general_response(user_message):
    """Send open-ended queries to GPT."""
    
    prompt = f"""
    The user has asked a general question or provided a greeting.
    Respond naturally and conversationally. Be helpful.
    
    User Request: "{user_message}"
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "system", "content": "You are an AI assistant that helps users with CPQ and general questions."},
                      {"role": "user", "content": prompt}]
        )
        
        return response.choices[0].message.content.strip()
          

    except Exception as e:
        logging.error(f"❌ Error processing general query: {e}")
        return "⚠️ I had trouble processing that. Can you ask differently?"