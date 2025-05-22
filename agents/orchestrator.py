import openai
import json
import os
import logging
from agents.quote_agent import add_product_to_quote, quote_agent
from agents.product_agent import product_agent
from agents.approvals_agent import approval_agent
from dotenv import load_dotenv
from agents.models import ChatSession, ChatMessage
from django.contrib.auth.models import User
from uuid import uuid4


# TDOO STOP Call to GPT 
# Pything to understand request, and catch before hitting LLM


load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4"
client = openai.OpenAI(api_key=OPENAI_API_KEY)
logging.basicConfig(level=logging.DEBUG)
openai.log = "warning"

def handle_user_request(user_message, session_data):
    user = User.objects.get(username="hvillasenor") 

    if should_reset_session(user_message):
        session_data.clear()
        return {
            "message": "🔄 Session cleared! Let's start fresh. What would you like to do?",
            "session_reset": True,
            "chat_sessions": list(ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at"))
        }
    
    response = orchestrate_request(user_message, session_data)

    response["chat_sessions"] = list(ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at"))
    return response

def orchestrate_request(user_message, session_data):
    
    session_context = {k: str(v) for k, v in session_data.items() if isinstance(v, (str, int, float, list, dict))}
    
    session_id = session_data.get("session_id")
    # ⚠️ Use a real user later; hardcode for now
    user = User.objects.get(username="hvillasenor")

    if not session_id:
        chat_session = ChatSession.objects.create(
            user=user,
            session_id=str(uuid4()),
            title=user_message[:30]  # Optionally use part of the first message
        )
        session_data["session_id"] = chat_session.session_id
    else:
        chat_session = ChatSession.objects.get(session_id=session_id)

    ChatMessage.objects.create(
        session=chat_session,
        sender="You",
        content=user_message
    )

    action_prompt = f"""
    You are an AI assistant that classifies user requests into predefined actions.
    **User Request:** "{user_message}"
    **Current Session Data:** {json.dumps(session_context, indent=2)}
    **Return ONLY one of the following labels (no explanations):**
    - "CreateQuote"
    - "AddProduct"
    - "GenerateQuoteDocument"
    - "ApplyDiscount"
    - "ProvideDates"
    - "ShowQuoteDetails"
    - "UpdateQuoteLine"
    - "CreateProductRecord"
    - "UpdateProductRecord"
    - "SubmitForApproval" 
    - "CheckApprovalStatus"
    - "ApproveQuote"
    - "RejectQuote"
    - "RecallQuote"
    - "ShowAccountDetails"
    - "GeneralQuery"
    """
    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "Analyze the request and determine next action."},
                {"role": "user", "content": action_prompt}
            ]
        )
        decision = response.choices[0].message.content.strip().replace('"', '')
        logging.info(f"🟢 AI Decision Received: {decision}")

    except Exception as e:
        logging.error(f"❌ Error in OpenAI call: {e}")
        return {"message": "⚠️ Sorry, an error occurred while processing your request."}

    action_map = get_action_map()

    if decision in action_map:
        result = action_map[decision](decision, user_message, session_data)
        
        agent_message = result.get("message", "")

        for key, value in result.items():
            if key not in ("message", "session_id"):
                agent_message += f"\n\n📦 {key}:\n{json.dumps(value, indent=2)}"

        ChatMessage.objects.create(
            session=chat_session,
            sender="agent",
            content=agent_message
        )

        result["message"] = agent_message
        result["session_id"] = session_data["session_id"]

        return result
    
    logging.warning(f"⚠️ AI returned an unknown intent: {decision}")
    return {"message": "Sorry, I couldn’t understand your request. From Orchestrator"}


def handle_general_query(decision, user_message, session_data):
    """Handles general inquiries about CPQ, pricing rules, approvals, etc."""
    try:
        # ✅ Initialize OpenAI client
        client = openai.OpenAI()

        # ✅ Construct GPT prompt
        system_prompt = """
        You are an AI assistant that specializes in Configure, Price, Quote (CPQ) systems.
        You help users understand CPQ workflows, approval processes, pricing rules, and best practices.
        Your responses should be clear, accurate, and professional.

        Example Queries:
        - "How does CPQ approval work?"
        - "What is the best way to structure discount rules?"
        - "How can I optimize my quote approvals?"
        - "What are common CPQ pricing strategies?"

        Answer concisely and professionally.
        """

        # ✅ Send request to OpenAI GPT
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.2
        )

        # ✅ Extract AI-generated response
        ai_response = response.choices[0].message.content.strip()

        # ✅ Return as a structured JSON response
        return {
            "success": True,
            "message": ai_response  
        }


    except Exception as e:
        logging.error(f"❌ Error handling general query: {str(e)}")
        return {
            "success": False,
            "response": {
                "message": "⚠️ Error processing your request. Please try again later."
            }
        }
    
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

def get_action_map():
    return {
        # Quote-related actions handled by quote_agent
        "CreateQuote": quote_agent,
        "AddProduct": quote_agent,
        "GenerateQuoteDocument": quote_agent,
        "ApplyDiscount": quote_agent,
        "ProvideDates": quote_agent,
        "ShowQuoteDetails": quote_agent,
        "UpdateQuoteLine": quote_agent,

        # Product-related actions handled by product_agent
        "CreateProductRecord": product_agent,
        "UpdateProductRecord": product_agent,

        # Approval-related actions handled by approval_agent
        "SubmitForApproval": approval_agent,
        "CheckApprovalStatus": approval_agent,
        "ApproveQuote": approval_agent,
        "RejectQuote": approval_agent,
        "RecallQuote": approval_agent,

        # General query handling
        "GeneralQuery": handle_general_query
    }