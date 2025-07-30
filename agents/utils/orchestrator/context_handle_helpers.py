from agents.models import SessionState
from django.utils.timezone import now
import logging, json

def save_or_update_conversation_context(session_context, agent_response):
    user = session_context.get("user")
    intent = session_context.get("intent")
    agent_name = session_context.get("agent_name")
    session_data = session_context.get("session_data")
    user_message = session_context.get("user_message")
    item_index = session_context.get("item_index")
    extracted = session_context.get("extracted")
    session_data = session_context.get("session_data")


    session_id = session_data.get("session_id")
    filtered_extracted = extract_non_null_fields(extracted or {})

    session, created = SessionState.objects.get_or_create(
        user=user,
        intent=intent,
        agent_name=agent_name,
        session_id=session_id,
        defaults={"data": []}
    )

    entry = {
        "item_index": item_index,
        "extracted_data": filtered_extracted,
        "agent_response": agent_response
    }

    session.data.append(entry)
    session.updated_at = now()
    session.save()

    if created:
        logging.info(f"✅ Agent Session Created: {session}")
    else:
        logging.info(f"📍 Agent Session Founded: {session}")

def extract_non_null_fields(data):
    if not isinstance(data, dict):
        # If data is not a dictionary, just return
        return data
    result = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, dict):
            nested = extract_non_null_fields(value)
            if nested:
                result[key] = nested
        else:
            result[key] = value
    return result

# Helper: Get current conversation context

def get_existing_context(user, session_data):
    session_id = session_data.get("session_id")
    try:
        session = SessionState.objects.get(
            user=user,
            session_id=session_id
        )
        return session
    except SessionState.DoesNotExist:
        return []
    
# Merge prior + current user messages

def build_context_prompt(data_entries, intention, new_user_message):
    messages = []

    messages.append("Intention: " + intention)
    messages.append("Previous data extracted:")

    for data in data_entries:
        item_index = data.get("item_index")
        response = data.get("agent_response", "")
        extracted = data.get("extracted_data", {})
        extracted_str = json.dumps(extracted, ensure_ascii=False)  # lo hace legible

        messages.append(f"- [{item_index}] Extracted: {extracted_str} | Agent_response: {response}")

    messages.append("New user message: " + new_user_message)
    return "\n".join(messages)


def make_session_context(user, intention, agent_name, session_data, user_message):
    # 🧠 Make the session context
    session_context = {
        "user": user,
        "intent": intention,
        "agent_name": agent_name,
        "session_data": session_data,
        "user_message": user_message,
        "extracted": None
    }

    return session_context