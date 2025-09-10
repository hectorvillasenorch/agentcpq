import json
import uuid
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User
from cpq.models import Lead, Tenant  # Adjust path as needed

# Orchestrator and Quote Agent
from agents.orchestrator import handle_user_request
from agents.quote_agent import quote_agent

@csrf_exempt
def receive_lead(request):
    # ✅ Validate method
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    # ✅ Extract and check API key
    api_key = request.headers.get("X-API-KEY")
    if not api_key:
        return JsonResponse({"error": "Missing X-API-KEY header"}, status=403)

    try:
        tenant = Tenant.objects.get(api_key=api_key)
    except Tenant.DoesNotExist:
        return JsonResponse({"error": "Invalid API key"}, status=403)

    # ✅ Parse JSON
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # ✅ Check required fields
    required_fields = ["first_name", "last_name", "email"]
    missing = [f for f in required_fields if not data.get(f)]
    if missing:
        return JsonResponse({"error": f"Missing required fields: {', '.join(missing)}"}, status=400)

    # ✅ Create lead
    try:
        lead = Lead.objects.create(
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data["email"],
            phone=data.get("phone", ""),
            source=data.get("source", "API"),
            notes=data.get("notes", ""),
            assigned_to=data.get("assigned_to", ""),
            status=data.get("status", "new"),
            created_at=timezone.now(),
            created_by_id=1,  # adjust if needed
        )
        return JsonResponse({"message": "Lead created", "leadId": lead.leadId}, status=201)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# -----------------------------
# API v1: Orchestrator + Quote Agent
# -----------------------------

def _auth_from_headers(request):
    """Validate X-API-KEY and resolve user from X-USER header.

    Returns (tenant, user) on success, or (None, JsonResponse) on error.
    """
    api_key = request.headers.get("X-API-KEY")
    if not api_key:
        return JsonResponse({"error": "Missing X-API-KEY header"}, status=403)
    try:
        tenant = Tenant.objects.get(api_key=api_key)
    except Tenant.DoesNotExist:
        return JsonResponse({"error": "Invalid API key"}, status=403)

    username = request.headers.get("X-USER")
    if not username:
        return JsonResponse({"error": "Missing X-USER header"}, status=400)
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return JsonResponse({"error": f"User '{username}' not found"}, status=404)

    return (tenant, user)


@csrf_exempt
def orchestrate_v1(request):
    """POST /api/v1/orchestrator/

    Body: { "message": str, "session_id"?: str, "session_data"?: object }
    Headers: X-API-KEY, X-USER

    Returns orchestrator response plus session data (stateless consumption).
    """
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    auth = _auth_from_headers(request)
    if isinstance(auth, JsonResponse):
        return auth
    tenant, user = auth

    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    message = (data.get("message") or "").strip()
    if not message:
        return JsonResponse({"error": "'message' is required"}, status=400)

    # Accept stateless session handoff from client
    session_data = data.get("session_data") or {}
    if not isinstance(session_data, dict):
        return JsonResponse({"error": "'session_data' must be an object"}, status=400)

    # Allow client-provided session_id to keep continuity
    if data.get("session_id"):
        session_data["session_id"] = data["session_id"]

    try:
        result = handle_user_request(user.username, message, session_data)
    except Exception as e:
        return JsonResponse({"error": f"Internal error: {str(e)}"}, status=500)

    # Return updated session data so callers can persist it client-side
    response = {
        "response": result,
        "session_data": session_data,
    }
    return JsonResponse(response, status=200)


@csrf_exempt
def quote_action_v1(request):
    """POST /api/v1/quote/action/

    Headers: X-API-KEY, X-USER
    Body: {
      "action": str,                  # e.g., CreateQuote, AddProduct, UpdateQuoteLine, UpdateQuote, ...
      "message"?: str,                 # natural-language command for agent
      "payload"?: object,              # structured payload used for UI-style actions
      "session_data"?: object,         # optional session continuity
      "session_id"?: str               # optional explicit session id
    }

    Behavior:
      - If action is UpdateQuoteLine or UpdateQuote and payload is provided, uses UI-optimized flows
        (Update Quote Line: {...}) / (Update Quote: {...}) to bypass LLM parsing.
      - Otherwise requires a 'message' to route through quote_agent as-is.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    auth = _auth_from_headers(request)
    if isinstance(auth, JsonResponse):
        return auth
    tenant, user = auth

    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    action = (data.get("action") or "").strip()
    if not action:
        return JsonResponse({"error": "'action' is required"}, status=400)

    session_data = data.get("session_data") or {}
    if not isinstance(session_data, dict):
        return JsonResponse({"error": "'session_data' must be an object"}, status=400)
    if data.get("session_id"):
        session_data["session_id"] = data["session_id"]

    payload = data.get("payload")
    message = data.get("message")

    # Normalize common aliases to the internal action labels
    aliases = {
        "create": "CreateQuote",
        "add": "AddProduct",
        "add-product": "AddProduct",
        "update-line": "UpdateQuoteLine",
        "update": "UpdateQuote",
        "delete-line": "DeleteQuoteLine",
        "delete": "DeleteQuote",
        "details": "ShowQuoteDetails",
        "notes": "ShowQuoteNotes",
        "generate-document": "GenerateQuoteDocument",
        "update-line-ui": "UpdateQuoteLineFromUI",
        "update-ui": "UpdateQuoteFromUI",
    }
    action = aliases.get(action.lower(), action)

    # For UI-style deterministic updates, expect payload and wrap as the agent expects
    if action in ("UpdateQuoteLineFromUI", "UpdateQuoteFromUI"):
        if not isinstance(payload, dict):
            return JsonResponse({"error": "'payload' object is required for UI update actions"}, status=400)
        prefix = "Update Quote Line: " if action == "UpdateQuoteLineFromUI" else "Update Quote: "
        message = prefix + json.dumps(payload)
    else:
        if not isinstance(message, str) or not message.strip():
            return JsonResponse({"error": "'message' is required for this action"}, status=400)

    try:
        result = quote_agent(user, action, message, session_data)
    except Exception as e:
        return JsonResponse({"error": f"Internal error: {str(e)}"}, status=500)

    return JsonResponse({
        "response": result,
        "session_data": session_data,
    }, status=200)
