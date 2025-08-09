from agents.models import SessionState
from django.utils.timezone import now
import logging, json

def save_or_update_conversation_context(session_context, agent_response):
    print(f"For the future, this is the session context: {session_context}")


# Change the name to save_or_update_conversation_context when session context is ready
def save_or_update_conversation_context2(session_context, agent_response):
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

def build_context_prompt_json(data_entries, intention, new_user_message):
    previous_data_extracted = []

    for data in data_entries:
        item_index = data.get("item_index")
        response = data.get("agent_response", "")
        extracted = data.get("extracted_data", {})
        # No es necesario convertir extracted a string, lo dejamos como dict
        previous_data_extracted.append({
            "item_index": item_index,
            "extracted_data": extracted,
            "agent_response": response
        })

    context = {
        "previous_intention": intention,
        "previous_data_extracted": previous_data_extracted,
        "new_user_message": new_user_message
    }

    return json.dumps(context, ensure_ascii=False, indent=2)


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