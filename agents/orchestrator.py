import openai
import json
import os
import logging
from agents.quote_agent import quote_agent
from agents.product_agent import product_agent
from agents.bundles_agent import bundles_agent
from agents.admin_agent import admin_agent
from agents.approvals_agent import approval_agent
from agents.custom_object_agent import custom_object_agent
from dotenv import load_dotenv
from agents.models import ChatSession, ChatMessage
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

    if not session_id:
        chat_session = ChatSession.objects.create(
            user=user,
            session_id=str(uuid4()),
            title=user_message[:30]
        )
        session_data["session_id"] = chat_session.session_id
    else:
        chat_session = ChatSession.objects.get(session_id=session_id)

    # Save user message
    ChatMessage.objects.create(
        session=chat_session,
        sender="user",
        content=user_message
    )

    # Solo para debug
    session_data.setdefault("state", {})
    print(f"\n\nCurrent session state: {session_data["state"]}\n\n")

    # Get or create message history on session_data
    session_data.setdefault("message_history", [])

    # 🔹 Construir historial de mensajes
    message_history = session_data.get("message_history", [])

    # Recortar los últimos MAX_HISTORY mensajes
    recent_history = get_recent_messages(message_history, max_messages=6)


    # Construir historial en formato roles
    messages = [
        {
            "role": "system",
            "content": """
            You are an AI assistant that classifies user requests into predefined actions.
            Only answer with ONE label from the list provided, no explanations, no emojis.
            """
        }
    ]

    # Agregar el historial recortado
    for msg in recent_history:
        role = "assistant" if msg["sender"] == "agent" else "user"
        messages.append({"role": role, "content": msg["message"]})
        # 👇 debug: imprimir msg con índice y saltos de línea
        print(f"\n\nIndex {recent_history.index(msg)} -> msg:\n{msg}\n\n")

    # Nuevo mensaje del usuario
    messages.append({"role": "user", "content": user_message})

    # Lista de labels
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
        - "ShowQuoteDetails"
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

        if session_data and user_message and agent_message:
            update_message_history(session_data, user_message, agent_message)

        session_summary = result.get("session_summary", None)

        if session_data and session_summary:
            update_summary(session_data, session_summary)


        for key, value in result.items():
            if key not in (
                "message", "session_id", "hiddenMessage", "temporaryMessage",
                "update_details", "iterations", "success", "quote_id", "notes", "tokens", "cost", "session_summary"
            ):
                agent_message += f"\n\n{key}:\n{json.dumps(value, indent=2)}"

        ChatMessage.objects.create(
            session=chat_session,
            sender="agent",
            content=agent_message,
            hiddenMessage=hiddenMessage
        )

        result["message"] = agent_message
        result["session_id"] = session_data["session_id"]

        return result

    logging.warning(f"⚠️ AI returned an unknown intent: {decision}")
    return {"message": "Sorry, I couldn’t understand your request. From Orchestrator"}

def orchestrate_request2(user, user_message, session_data):
    session_context = {
        k: str(v) for k, v in session_data.items()
        if isinstance(v, (str, int, float, list, dict))
    }

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
        chat_session = ChatSession.objects.get(session_id=session_id)

    # Save user message
    ChatMessage.objects.create(
        session=chat_session,
        sender="user",
        content=user_message
    )

    session_data.setdefault("state", {})

    session_data.setdefault("message_history", [])
    message_history = session_data.get("message_history", [])

    recent_history = get_recent_messages(session_data.get("message_history", []), max_messages=6)

    # Labels dinámicos de Custom Objects
    custom_objects = CustomObject.objects.all()
    custom_objects_list = [co.label for co in custom_objects]

    # 🔹 Nueva instrucción en formato JSON
    system_prompt = f"""
        You are an AI assistant that classifies user requests into one or more predefined actions.

        STRICT RULES:
        - Classify ONLY the content inside <LAST_USER_MESSAGE>…</LAST_USER_MESSAGE>.
        - Conversation history is for CONTEXT ONLY. DO NOT classify anything from it.
        - Always return a JSON array of objects.
        - Each object must have:
        - "action": one label from the list below
        - "message": the exact fragment of the LAST user message related to that action
        - If the LAST user message implies multiple actions, split it into multiple objects.
        - Do not explain, do not add extra text, do not add emojis. Only return the JSON array.
        - If the LAST user message implies multiple requests of the SAME action type, do not split them into multiple objects.
        - Always return a single object per action type.
        - In that object, include all relevant parts of the user message inside "message".
        - Do not send multiple separate objects for the same action.

        Example:
        User: "remove discount from PRODUCT-001 and add PRODUCT-002 to quote"
        Response:
        [
        {{
            "action": "UpdateQuoteLine",
            "message": "remove discount from PRODUCT-001"
        }},
        {{
            "action": "AddProductToQuote",
            "message": "add PRODUCT-002 to quote"
        }}
        ]

        Possible labels:
        - "CreateQuote"
        - "AddProductToQuote"
        - "GenerateQuoteDocument"
        - "ProvideDates"
        - "ShowQuoteDetails"
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
        """
    
    # Construye un texto de historial SOLO para contexto (puedes formatearlo como bullets)
    history_lines = []
    for msg in recent_history:
        who = "assistant" if msg["sender"] == "agent" else "user"
        history_lines.append(f"{who}: {msg['message']}")
        print(f"\n\nMensaje: {msg["message"]}\n\n")
    history_text = "\n".join(history_lines) if history_lines else "No prior messages."

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "system",
            "content": f"CONTEXT ONLY (DO NOT CLASSIFY THIS):\n{history_text}"
        },
        {
            "role": "user",
            "content": f"<LAST_USER_MESSAGE>\n{user_message}\n</LAST_USER_MESSAGE>"
        },
    ]

    tokens, est_cost = estimate_cost(messages, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 ORCHESTRATOR - Estimated tokens: {tokens}, approx cost: ${est_cost:.6f}\n\n")

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0
        )

        raw_decision = response.choices[0].message.content.strip()
        logging.info(f"\n🟢 AI Decision Raw: {raw_decision}\n")

        try:
            decisions = json.loads(raw_decision)  # 👈 Ahora es un array
        except json.JSONDecodeError as e:
            logging.error(f"❌ JSON parse error: {e}")
            return {"message": "⚠️ Sorry, AI response was not valid JSON."}

    except Exception as e:
        logging.error(f"❌ Error in OpenAI call: {e}")
        return {"message": "⚠️ Sorry, an error occurred while processing your request."}

    action_map = get_action_map()
    final_results = []

    for item in decisions:
        action = item.get("action")
        fragment = item.get("message", "")

        if action not in action_map:
            logging.warning(f"⚠️ Unknown action: {action}")
            continue

        result = run_agent_async(action_map[action], user, action, fragment, session_data)

        if not result:
            logging.error(f"❌ Agent for '{action}' returned None.")
            continue

        agent_message = result.get("message", "")
        hiddenMessage = result.get("hiddenMessage", False)

        if session_data and fragment and agent_message:
            update_message_history(session_data, fragment, agent_message)

        session_summary = result.get("session_summary", None)
        if session_data and session_summary:
            update_summary(session_data, session_summary)

        ChatMessage.objects.create(
            session=chat_session,
            sender="agent",
            content=agent_message,
            hiddenMessage=hiddenMessage
        )

        final_results.append(result)

    if not final_results:
        return {"message": "⚠️ No valid actions executed."}

    # 🔹 Combinar mensajes si hay varios
    combined_message = "<br><br>".join([res.get("message", "") for res in final_results])
    return {
        "message": combined_message,
        "session_id": session_data["session_id"],
        "results": final_results
    }



def orchestrate_request_trigger(user, user_message, session_data, decision):
    logging.info(f"\n🟢 AI Decision Trigger: {decision} \n")
    session_id = session_data.get("session_id")
    # ⚠️ Use a real user later; hardcode for now
    user = User.objects.get(username=user)

    if not session_id:
        chat_session = ChatSession.objects.create(
            user=user,
            session_id=str(uuid4()),
            title=user_message[:30]  # Optionally use part of the first message
        )
        session_data["session_id"] = chat_session.session_id
    else:
        chat_session = ChatSession.objects.get(session_id=session_id)

    #Extract the JSON to give the hidden field (Only for update message)
    if user_message.startswith("Update Quote Line:"):
        try:
            json_str = user_message.replace("Update Quote Line:", "")
            update_data = json.loads(json_str)
            hiddenMessage = update_data.get("hiddenMessage", False)
            ChatMessage.objects.create(
                session=chat_session,
                sender="user",
                content=user_message,
                hiddenMessage = hiddenMessage
            )
        except json.JSONDecodeError as e:
            logging.error(f" Error decoding JSON: {e}")
    elif user_message.startswith("Update Quote:"):
        try:
            json_str = user_message.replace("Update Quote:", "")
            update_data = json.loads(json_str)
            hiddenMessage = update_data.get("hiddenMessage", False)
            ChatMessage.objects.create(
                session=chat_session,
                sender="user",
                content=user_message,
                hiddenMessage = hiddenMessage
            )
        except json.JSONDecodeError as e:
            logging.error(f" Error decoding JSON: {e}")
    else:
        ChatMessage.objects.create(
            session=chat_session,
            sender="user",
            content=user_message
        )

    action_map = get_action_map()

    if decision in action_map:
        result = action_map[decision](user,decision, user_message, session_data)
        
        agent_message = result.get("message", "")

        hiddenMessage = result.get("hiddenMessage", False)

        for key, value in result.items():
            if key not in ("message", "session_id", "hiddenMessage", "original_value"):
                agent_message += f"\n\n📦 {key}:\n{json.dumps(value, indent=2)}"

        ChatMessage.objects.create(
            session=chat_session,
            sender="agent",
            content=agent_message,
            hiddenMessage = hiddenMessage
        )

        result["message"] = agent_message
        result["session_id"] = session_data["session_id"]

        return result
    
    logging.warning(f"⚠️ AI returned an unknown intent: {decision}")
    return {"message": "Sorry, I couldn’t understand your request. From Orchestrator"}



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
        "UpdateEmailAlert": admin_agent,
        "DeleteEmailAlert": admin_agent
    }


def get_trigger_phrases():
    return [
        "generate doc",
        "generate document",
        "generate pdf",
        "create quote pdf",
    ]


