import openai
import json
import os
import logging
from agents.quote_agent import add_product_to_quote, quote_agent
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

def handle_user_request(user_message, session_data):
    """Handles user requests, checking for session reset before processing."""
    
    if should_reset_session(user_message):
        session_data.clear()
        return {"message": "🔄 Session cleared! Let's start fresh. What would you like to do?"}

    # ✅ Proceed with normal processing
    return orchestrate_request(user_message, session_data)


def orchestrate_request(user_message, session_data):
    """Dynamically determine next steps based on user request and session context."""
    
    # ✅ Ensure session data is serializable
    session_context = {k: str(v) for k, v in session_data.items() if isinstance(v, (str, int, float, list, dict))}
    
    prompt = f"""
    You are an AI assistant that classifies user requests into predefined actions.

    **User Request:** "{user_message}"

    **Current Session Data:** {json.dumps(session_context, indent=2)}

    **Return ONLY one of the following labels (do NOT add explanations):**
    - "CreateQuote"
    - "AddProduct"
    - "GenerateQuoteDocument"
    - "ApplyDiscount"
    - "ProvideDates"
    - "ShowQuoteDetails"
    - "UpdateQuoteLine"
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

    # ✅ Route all quote-related actions to the **quote_agent**
    if decision in ["CreateQuote", "AddProduct", "ApplyDiscount", "ProvideDates", "ShowQuoteDetails", "GenerateQuoteDocument","UpdateQuoteLine"]:
        return quote_agent(decision, user_message, session_data)  # ✅ Handles all quote interactions

    # ✅ Handle general queries
    if decision == "GeneralQuery":
        return query_gpt_for_general_response(user_message)

    logging.warning(f"⚠️ AI returned an unknown intent: {decision}")
    return {"message": "🤖 Sorry, I couldn’t understand your request. From Orchestrator"}

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
    
def should_reset_session(user_message):
    """Use GPT to determine if the user intends to reset the session."""
    prompt = f"""
    Determine if the user message indicates a request to reset the session.

    **User Message:** "{user_message}"

    If the user wants to reset the session, return **ONLY** "RESET".
    Otherwise, return **ONLY** "CONTINUE".
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Determine if the user wants to reset the session."},
                {"role": "user", "content": prompt}
            ]
        )

        decision = response.choices[0].message.content.strip().upper()
        return decision == "RESET"

    except Exception as e:
        logging.error(f"❌ Error in GPT session reset detection: {e}")
        return False  # Default to not resetting if GPT fails

