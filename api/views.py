import json
import uuid
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User
from cpq.models import Lead, Tenant  # Adjust path as needed

# Orchestrator and Quote Agent
from agents.orchestrator import handle_user_request
"""API v1 views for external access.

Exposes the orchestrator endpoint only; all agent actions must flow
through the orchestrator. No direct quoting-agent API is provided.
"""

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
