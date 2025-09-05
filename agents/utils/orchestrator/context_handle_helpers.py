import redis
import json
import logging
import tiktoken
from agents.models import SessionState

logger = logging.getLogger(__name__)

# Conexión a Redis
#r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

# No borrar esta function para no romper el codigo hasta adaptar todas las functions al nuevo LLM
def save_or_update_conversation_context(session_context, agent_response):
    print(session_context, agent_response)

# No borrar esta function para no romper el codigo hasta adaptar todas las functions al nuevo LLM
def make_session_context(user, intention, agent_name, session_data, user_message):
    session_context = {
        "user": user,
        "intent": intention,
        "agent_name": agent_name,
        "session_data": session_data,
        "user_message": user_message,
        "extracted": None
    }

    return session_context

# No borrar esta function para no romper el codigo hasta adaptar todas las functions al nuevo LLM
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


def estimate_cost(messages, model="gpt-4o-mini"):
    """
    Estima los tokens y costo aproximado de una llamada chat.completions.
    messages: lista de dicts {"role": "user"/"assistant"/"system", "content": "texto"}
    """
    # Seleccionar codificador del modelo
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")

    total_tokens = 0
    for msg in messages:
        total_tokens += len(enc.encode(msg["content"])) + 4  # +4 tokens aproximado por role/meta
    total_tokens += 2  # tokens extra de la llamada

    # Precios aproximados USD / 1,000 tokens
    model_prices = {
        "gpt-4o-mini": 0.00125,
        "gpt-4o": 0.03,
        "gpt-3.5-turbo": 0.0002
    }

    price_per_1k = model_prices.get(model, 0.00125)
    cost = total_tokens / 1000 * price_per_1k

    return total_tokens, cost

def get_recent_messages(message_history, max_messages=4):
    """
    Devuelve los últimos `max_messages` del historial en formato FIFO,
    conservando el orden original (del más antiguo al más reciente).
    """
    # Recorta los últimos max_messages
    recent = message_history[-max_messages:]
    return recent

# update message history on session_data
def update_message_history(session_data, user_message, agent_message):
    """
    Guarda los mensajes del usuario y del agente en session_data.
    Si user_message o agent_message no son strings, agrega un mensaje por defecto.
    """
    session_data.setdefault("message_history", [])

    # Verificar user_message
    if not isinstance(user_message, str):
        user_message = "[Could not extract user message: not a valid string]"

    # Verificar agent_message
    if not isinstance(agent_message, str):
        agent_message = "[Could not extract agent message: not a valid string]"

    session_data["message_history"].append({
        "sender": "user",
        "message": user_message
    })
    session_data["message_history"].append({
        "sender": "agent",
        "message": agent_message
    })

# update summary on session_data
def update_summary(session_data, new_summary):
    """
    Actualiza el resumen de la sesión.
    """
    session_data.setdefault("state", {})
    session_data["state"]["summary"] = new_summary
