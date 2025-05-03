import json
import os
import logging

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.template.context_processors import csrf
from dotenv import load_dotenv

from .orchestrator import handle_user_request  # or orchestrate_request if needed

logger = logging.getLogger(__name__)

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4"


def agents_chat(request):
    """Render the chat page with CSRF token."""
    context = {}
    context.update(csrf(request))
    return render(request, "agents.html", context)


def _handle_pending_action(pending_action, user_message, session_data):
 
    if pending_action == "confirm_opportunity":
        session_data["opportunity_name"] = user_message
        session_data["pending_action"] = None
        return {
            "response": f"✅ Opportunity `{user_message}` added. "
                        "Would you like to add products now?"
        }

    if pending_action == "confirm_product_addition":
        session_data["product_sku"] = user_message
        session_data["pending_action"] = None
        return {
            "response": f"✅ Product `{user_message}` added to the quote."
        }

    return None  # Unrecognized or no pending action to handle


@csrf_exempt
def chat_with_gpt(request):
    """API endpoint to process user messages and route them based on AI-determined intent."""
    # --- 1. Validate request method ---
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method. Use POST."}, status=405)

    # --- 2. Log basic info ---
    opportunity_id = request.GET.get("opportunity_id", "No Opportunity ID provided")
    logger.info(f"🔹 DEBUG: Incoming request URL - {request.build_absolute_uri()}")
    logger.info(f"🔹 DEBUG: Extracted Opportunity ID - {opportunity_id}")

    # --- 3. Parse JSON body ---
    try:
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON format."}, status=400)

    if not user_message:
        return JsonResponse({"error": "Message cannot be empty."}, status=400)

    # --- 4. Load session data ---
    session_data = request.session.get("session_data", {})
    logger.info(f"🔹 DEBUG: Session Data: {session_data}")

    # --- 5. Handle pending actions (if any) ---
    pending_action = session_data.get("pending_action")
    if pending_action:
        logger.info(f"🔄 Resuming pending action: {pending_action}")
        result = _handle_pending_action(pending_action, user_message, session_data)
        if result:
            # If the pending action was fulfilled, update session and return immediately
            request.session["session_data"] = session_data
            logger.info(f"[Pending Action Resolved] Response: {result['response']}")
            return JsonResponse(result)

    # --- 6. No pending action -> Orchestrate new user request ---
    try:
        ai_response = handle_user_request(user_message, session_data)
    except Exception as e:
        logger.error(f"❌ Error in Orchestrator logic: {e}", exc_info=True)
        return JsonResponse({"error": "Internal server error."}, status=500)

    # --- 7. Save updated session data ---
    request.session["session_data"] = session_data
    logger.info(f"[Orchestrator] AI Response: {ai_response}")

    return JsonResponse({"response": ai_response})