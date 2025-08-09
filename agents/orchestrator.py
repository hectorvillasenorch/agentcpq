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
from .utils.orchestrator.context_handle_helpers import get_existing_context, build_context_prompt_json


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
    
    session_context = {k: str(v) for k, v in session_data.items() if isinstance(v, (str, int, float, list, dict))}
    
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

    
    ChatMessage.objects.create(
        session=chat_session,
        sender="user",
        content=user_message
    )

    # 🧠🧠 Check if any context exist for this user and this session id
    conversation_context = get_existing_context(user, session_data)
    if conversation_context:
        context_data = conversation_context.data
        intention = conversation_context.intent

        if context_data and is_continuation_prompt(context_data, user_message, intention):
            user_message = build_context_prompt_json(context_data, intention, user_message)
            conversation_context.delete()

    print(f"\n\nThis is the new user message: {user_message}\n\n")

    #return {"message": user_message}

    custom_objects = CustomObject.objects.all()
    custom_objects_list = []

    for co in custom_objects:
        custom_objects_list.append(co.label)


    action_prompt = f"""
    You are an AI assistant that classifies user requests into predefined actions.
    **User Request:** "{user_message}"
    **Current Session Data:** {json.dumps(session_context, indent=2)}
    **Return ONLY one of the following labels (no explanations):**
    - "CreateQuote"
    - "AddProduct"
    - "GenerateQuoteDocument"
    - "ProvideDates"
    - "ShowQuoteDetails"
    - "UpdateQuoteLine" (Use this when the user wants to update a quote line item. The fields that can be updated at the quote line level are: quantity, discount_amount, discount_percentage, and term.)
    - "UpdateQuote" (Use this when the user wants to update any quote. The fields that can be updated at the quote level are: status, discount_percentage, discount_amount, expiration_date, notes)
    - "ShowQuoteNotes"
    - "DeleteQuoteLine"
    - "DeleteQuote" (Use this ONLY for messages that not includes SKU or product's names)
    - "CreateProductRecord" (Use this when the user wants to create a new product record, not add a product to quote)
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
    - "UpdateRule" (Use this when the user wants to update a rule)
    - "DeleteRule" (Use this when the user wants to delete a rule)
    - "AddProductToBundle" (Use this when the user wants to add any product to bundle)
    - "UpdateBundleOption" (Use this when the user wants to update any bundle option)
    - "DeleteBundleOption" (Use this when the user wants to delete any bundle option)
    - "DeleteBundleComponentFromQuote" (Use this when the user wants to delete any bundle option from quote)
    - "CreateCustomObject" (Use this when the user wants to create a new custom object)
    - "UpdateCustomObject" (Use this when the user wants to update any custom object, an example of user message is: update custom object)
    - "DeleteCustomObject" (Use this when the user wants to delete any custom object)
    - "CreateCustomField" (Use this when the user wants to create a new custom field)
    - "UpdateCustomField" (Use this when the user wants to update any custom field)
    - "DeleteCustomField" (Use this when the user wants to delete any custom field)
    - "CreateCustomRecord" (Use this when the user wants to create a record for an existing custom object like {custom_objects_list})
    - "UpdateCustomRecord" (Use this when the user wants to update any record for an existing custom object like {custom_objects_list})
    - "DeleteCustomRecord" (Use this when the user wants to delete any record for an existing custom object like {custom_objects_list})
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
        logging.info(f"\n🟢 AI Decision Received: {decision} \n")

    except Exception as e:
        logging.error(f"❌ Error in OpenAI call: {e}")
        return {"message": "⚠️ Sorry, an error occurred while processing your request."}

    action_map = get_action_map()

    if decision in action_map:
        result = action_map[decision](user,decision, user_message, session_data)

        if result is None:
            logging.error(f"❌ Agent function for '{decision}' returned None.")
            return {"message": f"⚠️ Error: Agent function for '{decision}' returned nothing."}
        
        agent_message = result.get("message", "")

        hiddenMessage = result.get("hiddenMessage", False)

        for key, value in result.items():
            if key not in ("message", "session_id", "hiddenMessage", "temporaryMessage", "update_details", "iterations", "success", "quote_id", "notes"):
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
        "AddProduct": quote_agent,
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
        "DeleteCustomRecord": custom_object_agent
    }


def get_trigger_phrases():
    return [
        "generate doc",
        "generate document",
        "generate pdf",
        "create quote pdf",
    ]

# Check if new message is continuation

def is_continuation_prompt(previous_data, new_user_message, intention):
    conversation_history = ""

    conversation_history += f"""
        Intention: "{intention}"
        Data extracted: "{previous_data}"
        """

    prompt = f"""
    You are determining whether a user's new message is a continuation of the previous conversation or a new, unrelated request.

    Take into account the following rules:
    - If the new message contains words like "update", "update quote line", "create", "add", or any other indication that it refers to creating or modifying data (like a new quote line), then it should be treated as a NEW request, even if the intent is similar to the previous one.
    - Otherwise, if the message logically continues the last request or depends on previous information, then it is a continuation.

    Conversation history:
    {conversation_history}
    New message: "{new_user_message}"

    Return YES if it is a continuation. Return NO if it's a new, unrelated request.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Determine continuation status"},
                {"role": "user", "content": prompt}
            ]
        )
        return "YES" in response.choices[0].message.content.upper()
    except:
        return False