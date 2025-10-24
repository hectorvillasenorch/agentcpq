import openai
import re
import json
import os
import logging
from agents.quote_agent import quote_agent
from agents.product_agent import product_agent
from agents.bundles_agent import bundles_agent
from agents.admin_agent import admin_agent
from agents.approvals_agent import approval_agent
from agents.custom_object_agent import custom_object_agent
from agents.analytics_agent import analytics_agent
from agents.knowledge_agent import knowledge_agent
from agents.action_trigger_agent import action_trigger_agent
from dotenv import load_dotenv
from agents.models import ChatSession, ChatMessage


def _decode_chat_text(text: str) -> str:
    if not text:
        return ""

    decoded = text
    if "\\u" in decoded or "\\U" in decoded:
        try:
            decoded = decoded.encode("utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            pass
    return decoded
from django.contrib.auth.models import User
from uuid import uuid4
logger = logging.getLogger(__name__)

from cpq.models import CustomObject

# TDOO STOP Call to GPT
# Pything to understand request, and catch before hitting LLM

# Context Session Helpers
from .utils.orchestrator.context_handle_helpers import estimate_cost, get_recent_messages
from .utils.orchestrator.general_helpers import run_agent_async
from .utils.orchestrator.context_handle_helpers import update_message_history, update_summary


load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"
client = openai.OpenAI(api_key=OPENAI_API_KEY)
logging.basicConfig(level=logging.DEBUG)
openai.log = "warning"


def _safe_serialize(value):
    if isinstance(value, dict):
        return {k: _safe_serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_serialize(v) for v in value]
    if hasattr(value, "__dict__") and not isinstance(value, (str, bytes)):
        return str(value)
    return value


def handle_user_request(user,user_message, session_data):
    user = User.objects.get(username=user)
    logger.info(f"USER LOGGED IN - {user}")

    if should_reset_session(user_message):
        session_data.clear()
        return {
            "message": "🔄 Session cleared! Let's start fresh. What would you like to do?",
            "session_reset": True,
            "chat_sessions": list(ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at"))
        }

    # 🧠 Shortcut manual
    message = user_message.lower()

    trigger_phrases = get_trigger_phrases()

    # 🧠 Shortcut manual: "show quote details for <quote_id>"
    if user_message.lower().startswith("show quote details for "):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user,user_message, session_data, decision="ShowQuoteDetails")

    # 🧠 Shortcut manual: "Update Quote Line:"
    elif user_message.startswith("Update Quote Line:"):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, user_message, session_data, decision="UpdateQuoteLineFromUI")

    elif user_message.startswith("Update Quote:"):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, user_message, session_data, decision="UpdateQuoteFromUI")

    # 🧠 Shortcut manual: "generate pdf"
    elif any(message.startswith(trigger) for trigger in trigger_phrases):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, message, session_data, decision="GenerateQuoteDocument")

    else:
        logging.info("USE GPT\n")
        response = orchestrate_request(user, user_message, session_data)

    response["chat_sessions"] = list(ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at"))
    return response

def orchestrate_request(user, user_message, session_data):
    session_context = {
        k: str(v) for k, v in session_data.items()
        if isinstance(v, (str, int, float, list, dict))
    }

    session_id = session_data.get("session_id")

    user = User.objects.get(username=user)

    # Robust session handling: create if missing or absent
    if not session_id:
        chat_session = ChatSession.objects.create(
            user=user,
            session_id=str(uuid4()),
            title=user_message[:30]
        )
        session_data["session_id"] = chat_session.session_id
    else:
        try:
            chat_session = ChatSession.objects.get(session_id=session_id)
        except ChatSession.DoesNotExist:
            chat_session = ChatSession.objects.create(
                user=user,
                session_id=session_id,
                title=user_message[:30]
            )
            session_data["session_id"] = chat_session.session_id

    # Save user message
    decoded_initial_user_message = _decode_chat_text(user_message)
    ChatMessage.objects.create(
        session=chat_session,
        sender="user",
        content=decoded_initial_user_message
    )


    session_data.setdefault("state", {})
    # For debug
    print(f"\n\nCurrent session state: {session_data['state']}\n\n")

    # 🔹 Get or create message history on session_data
    session_data.setdefault("message_history", [])

    # 🔹 Shortcut for clear how-to requests before hitting the LLM
    if _should_shortcut_to_knowledge(user_message):
        logging.info("🔀 Shortcutting to KnowledgeLookup based on heuristic match")
        return orchestrate_request_trigger(user, user_message, session_data, decision="KnowledgeLookup")

    # 🔹 Build message history
    message_history = session_data.get("message_history", [])

    # 🔹 Trim the last MAX_HISTORY messages
    recent_history = get_recent_messages(message_history, max_messages=6)


    # 🔹 Build history in roles format
    messages = [
        {
            "role": "system",
            "content": """
            You are an AI assistant that classifies user requests into predefined actions.
            Only answer with ONE label from the list provided, no explanations, no emojis, do not use this emoji: ✅.
            If the user's current message is exactly the same as the previous one, it is possible that what you decided earlier was not the correct action.
            Consider changing it for this new attempt, or ask the user what they want to do.
            """
        }
    ]

    # 🔹 Add the trimmed history
    for msg in recent_history:
        role = "assistant" if msg["sender"] == "agent" else "user"
        messages.append({"role": role, "content": msg["message"]})

    # 🔹 New user message
    messages.append({"role": "user", "content": user_message})

    # 🔹 List of labels
    custom_objects = CustomObject.objects.all()
    custom_objects_list = [co.label for co in custom_objects]

    messages.append({
        "role": "system",
        "content": f"""
        Possible labels:
        - "CreateQuote"
        - "AddProductToQuote"
        - "GenerateQuoteDocument"
        - "ProvideDates"
        - "UpdateQuoteLine"
        - "UpdateQuote"
        - "ShowQuoteNotes"
        - "DeleteQuoteLine"
        - "DeleteQuote"
        - "CreateProductRecord"
        - "UpdateProductRecord"
        - "SubmitForApproval"
        - "CheckApprovalStatus"
        - "ApproveQuote"
        - "RejectQuote"
        - "RecallQuote"
        - "ShowAccountDetails"
        - "GeneralQuery"
        - "CreateValidationRule"
        - "CreateInclusionRule"
        - "ShowRules"
        - "UpdateRule"
        - "DeleteRule"
        - "AddProductToBundle"
        - "UpdateBundleOption"
        - "DeleteBundleOption"
        - "DeleteBundleComponentFromQuote"
        - "CreateCustomObject"
        - "UpdateCustomObject"
        - "DeleteCustomObject"
        - "CreateCustomField"
        - "UpdateCustomField"
        - "DeleteCustomField"
        - "CreateCustomRecord" (for {custom_objects_list})
        - "UpdateCustomRecord" (for {custom_objects_list})
        - "DeleteCustomRecord" (for {custom_objects_list})
        - "CreateEmailAlert"
        - "UpdateEmailAlert"
        - "DeleteEmailAlert"
        - "ShowQuoteDetails" → Use when the user requests to view or open a single quote — 
                either a specific one (by ID or name) **or the active quote in the current session**.  
                This label should also be used for messages like:
                    - "Show quote"
                    - "Show details"
                    - "Display the current quote"
                    - "Open quote Q-2024-001"
                    - "Show the quote for ACPQ-TEAM"
                Do NOT use this label when the user requests multiple quotes, lists, or filtered results.
        - "ShowMetrics" → Use when the user requests listings, summaries, or filtered searches 
                involving multiple records (quotes, products, accounts, etc.).  
                This includes plural forms ("quotes", "products"), date filters ("last 3 days", "this month"),
                or numerical filters ("top 5", "all", "recent").  
                Examples:
                    - "Show me my quotes created in the last 3 days"
                    - "List all quotes pending approval"
                    - "Show my last 5 quotes"
                    - "Display all products in the catalog"
        - "KnowledgeLookup" → Use when the user asks for how-to instructions, FAQs, or training guidance (e.g. "how do I create a quote", "teach me about approvals").
        - "CreateActionTrigger"
        - "CreateExclusionRule"
        """
    })

    messages.append({
        "role": "system",
        "content": f"""
        
        """
    })

    tokens, est_cost = estimate_cost(messages, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 ORCHESTRATOR - Estimated tokens: {tokens}, approx cost: ${est_cost:.6f}\n\n")

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0
        )

        decision = response.choices[0].message.content.strip().replace('"', '')
        #decision = re.sub(r'[^\w\s\-\_\.\,]', '', decision)
        logging.info(f"\n🟢 AI Decision Received: {decision} \n")

    except Exception as e:
        logging.error(f"❌ Error in OpenAI call: {e}")
        return {"message": "⚠️ Sorry, an error occurred while processing your request."}

    action_map = get_action_map()

    if decision in action_map:
        result = run_agent_async(action_map[decision], user, decision, user_message, session_data)

        if result is None:
            logging.error(f"❌ Agent function for '{decision}' returned None.")
            return {"message": f"⚠️ Error: Agent function for '{decision}' returned nothing."}

        agent_message = result.get("message", "")
        hiddenMessage = result.get("hiddenMessage", False)

        session_summary = result.get("session_summary", None)

        if session_data and session_summary:
            update_summary(session_data, session_summary)


        for key, value in result.items():
            if key not in (
                "message", "session_id", "hiddenMessage", "temporaryMessage",
                "update_details", "iterations", "success", "quote_id", "notes",
                "tokens", "cost", "session_summary", "rules_created"
            ):
                agent_message += f"\n\n{key}:\n{json.dumps(_safe_serialize(value), indent=2, ensure_ascii=False)}"

        decoded_agent_message = _decode_chat_text(agent_message)

        if session_data and decoded_initial_user_message and decoded_agent_message:
            update_message_history(session_data, decoded_initial_user_message, decoded_agent_message)

        ChatMessage.objects.create(
            session=chat_session,
            sender="agent",
            content=decoded_agent_message,
            hiddenMessage=hiddenMessage
        )

        sanitized_result = {key: _safe_serialize(value) for key, value in result.items()}
        sanitized_result["message"] = decoded_agent_message
        sanitized_result["session_id"] = session_data["session_id"]

        return sanitized_result

    logging.warning(f"⚠️ AI returned an unknown intent: {decision}")
    return {"message": "Sorry, I couldn’t understand your request. From Orchestrator"}


def orchestrate_request_trigger(user, user_message, session_data, decision):
    logging.info(f"\n🟢 AI Decision Trigger: {decision} \n")
    session_id = session_data.get("session_id")
    
    user = User.objects.get(username=user)

    if not session_id:
        chat_session = ChatSession.objects.create(
            user=user,
            session_id=str(uuid4()),
            title=user_message[:30]
        )
        session_data["session_id"] = chat_session.session_id
    else:
        try:
            chat_session = ChatSession.objects.get(session_id=session_id)
        except ChatSession.DoesNotExist:
            chat_session = ChatSession.objects.create(
                user=user,
                session_id=session_id,
                title=user_message[:30]
            )
            session_data["session_id"] = chat_session.session_id

    #Extract the JSON to give the hidden field (Only for update message)
    if user_message.startswith("Update Quote Line:"):
        try:
            json_str = user_message.replace("Update Quote Line:", "")
            update_data = json.loads(json_str)
            hiddenMessage = update_data.get("hiddenMessage", False)
            decoded_message = _decode_chat_text(user_message)
            ChatMessage.objects.create(
                session=chat_session,
                sender="user",
                content=decoded_message,
                hiddenMessage = hiddenMessage
            )
        except json.JSONDecodeError as e:
            logging.error(f" Error decoding JSON: {e}")
    elif user_message.startswith("Update Quote:"):
        try:
            json_str = user_message.replace("Update Quote:", "")
            update_data = json.loads(json_str)
            hiddenMessage = update_data.get("hiddenMessage", False)
            decoded_message = _decode_chat_text(user_message)
            ChatMessage.objects.create(
                session=chat_session,
                sender="user",
                content=decoded_message,
                hiddenMessage = hiddenMessage
            )
        except json.JSONDecodeError as e:
            logging.error(f" Error decoding JSON: {e}")
    else:
        decoded_message = _decode_chat_text(user_message)
        ChatMessage.objects.create(
            session=chat_session,
            sender="user",
            content=decoded_message
        )

    action_map = get_action_map()

    if decision in action_map:
        result = action_map[decision](user,decision, user_message, session_data)

        agent_message = result.get("message", "")

        hiddenMessage = result.get("hiddenMessage", False)

        for key, value in result.items():
            if key not in ("message", "session_id", "hiddenMessage", "original_value"):
                agent_message += f"\n\n📦 {key}:\n{json.dumps(_safe_serialize(value), indent=2, ensure_ascii=False)}"

        agent_message = _decode_chat_text(agent_message)

        ChatMessage.objects.create(
            session=chat_session,
            sender="agent",
            content=agent_message,
            hiddenMessage = hiddenMessage
        )

        sanitized_result = {key: _safe_serialize(value) for key, value in result.items()}
        sanitized_result["message"] = agent_message
        sanitized_result["session_id"] = session_data["session_id"]

        return sanitized_result

    logging.warning(f"⚠️ AI returned an unknown intent: {decision}")
    return {"message": "Sorry, I couldn’t understand your request. From Orchestrator"}


def _should_shortcut_to_knowledge(user_message: str) -> bool:
    if not user_message:
        return False

    lowered = user_message.lower()

    knowledge_phrases = (
        "teach me",
        "how do i",
        "how to",
        "show me how",
        "guide me",
        "explain",
        "what is",
        "walk me through",
        "steps to",
        "instructions",
        "training on",
    )

    return any(phrase in lowered for phrase in knowledge_phrases)


def handle_general_query(user,decision, user_message, session_data):
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
            model="gpt-4o-mini",
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
        "AddProductToQuote": quote_agent,
        "UpdateQuoteLine": quote_agent,
        "UpdateQuote": quote_agent,
        "DeleteQuoteLine": quote_agent,
        "DeleteQuote": quote_agent,
        "ShowQuoteDetails": quote_agent,
        "ShowQuoteNotes": quote_agent,
        "GenerateQuoteDocument": quote_agent,
        #"ProvideDates": quote_agent,

        # Only for triggered messages
        "UpdateQuoteLineFromUI": quote_agent,
        "UpdateQuoteFromUI": quote_agent,

        # Product-related actions handled by product_agent
        "CreateProductRecord": product_agent,
        "UpdateProductRecord": product_agent,

        # Bundles-related actions handled by bundles_agent
        "AddProductToBundle": bundles_agent,
        "UpdateBundleOption": bundles_agent,
        "DeleteBundleOption": bundles_agent,
        "DeleteBundleComponentFromQuote": bundles_agent,

        # Approval-related actions handled by approval_agent
        "SubmitForApproval": approval_agent,
        "CheckApprovalStatus": approval_agent,
        "ApproveQuote": approval_agent,
        "RejectQuote": approval_agent,
        "RecallQuote": approval_agent,

        # General query handling
        "GeneralQuery": handle_general_query,

        # Rules
        "CreateValidationRule": admin_agent,
        "CreateInclusionRule": admin_agent,
        "ShowRules": admin_agent,
        "UpdateRule": admin_agent,
        "DeleteRule": admin_agent,

        # Custom Objects
        "CreateCustomObject": custom_object_agent,
        "UpdateCustomObject": custom_object_agent,
        "DeleteCustomObject": custom_object_agent,
        "CreateCustomField": custom_object_agent,
        "UpdateCustomField": custom_object_agent,
        "DeleteCustomField": custom_object_agent,
        "CreateCustomRecord": custom_object_agent,
        "UpdateCustomRecord": custom_object_agent,
        "DeleteCustomRecord": custom_object_agent,
        # EmailAlerts
        "CreateEmailAlert": admin_agent,
        "CreateExclusionRule": admin_agent,
        "UpdateEmailAlert": admin_agent,
        "DeleteEmailAlert": admin_agent,
        # Metrics Agent
        "ShowMetrics": analytics_agent,
        # Knowledge Agent
        "KnowledgeLookup": knowledge_agent,
        # Action Trigger Agent
        "CreateActionTrigger": action_trigger_agent,
    }


def get_trigger_phrases():
    return [
        "generate doc",
        "generate document",
        "generate pdf",
        "create quote pdf",
    ]
