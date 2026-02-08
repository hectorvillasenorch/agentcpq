import json
import re
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.contrib.contenttypes.models import ContentType
from cpq.models import Lead, Tenant, CustomField, CustomFieldValue  # Adjust path as needed

# Orchestrator and Quote Agent
from agents.orchestrator import handle_user_request

def _normalize_key(key: str) -> str:
    if key is None:
        return ""
    return re.sub(r"\s+", " ", str(key).replace("_", " ").strip().lower())


def _infer_custom_data_type(value) -> str:
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, bool):
        return "boolean"
    return "text"


def _get_custom_field_map(object_name: str):
    qs = CustomField.objects.filter(custom_object__isnull=True, object_type=object_name)
    mapping = {}
    for cf in qs:
        for variant in [cf.name, cf.label]:
            if not variant:
                continue
            mapping[_normalize_key(variant)] = cf
    return mapping


def _ensure_custom_field(object_name: str, key: str, value):
    custom_map = _get_custom_field_map(object_name)
    normalized = _normalize_key(key)
    if normalized in custom_map:
        return custom_map[normalized]

    name_base = re.sub(r"[^a-zA-Z0-9_]", "_", key).strip("_")
    if not name_base:
        name_base = "custom_field"
    if not name_base.endswith("__c"):
        name_base = f"{name_base}__c"

    cf = CustomField.objects.create(
        label=key.replace("_", " ").strip().title(),
        name=name_base,
        crm="AgentCPQ",
        object_type=object_name,
        data_type=_infer_custom_data_type(value),
        required=False,
    )
    return cf


def _save_custom_fields(record, data, standard_fields, object_name="Lead"):
    extra_fields = {
        key: value
        for key, value in data.items()
        if key not in standard_fields
    }
    if not extra_fields:
        return []

    ct = ContentType.objects.get_for_model(record.__class__)
    saved = []
    for key, value in extra_fields.items():
        cf = _ensure_custom_field(object_name, key, value)
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        CustomFieldValue.objects.update_or_create(
            field=cf,
            content_type=ct,
            object_id=record.id,
            defaults={
                "value": "" if value is None else str(value),
                "record": None,
                "updated_by_user": record.created_by,
            },
        )
        saved.append(cf.name)
    return saved


@csrf_exempt
def receive_lead(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    api_key = request.headers.get("X-API-KEY")
    if not api_key:
        return JsonResponse({"error": "Missing X-API-KEY header"}, status=403)

    try:
        tenant = Tenant.objects.get(api_key=api_key)
    except Tenant.DoesNotExist:
        return JsonResponse({"error": "Invalid API key"}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    required_fields = ["first_name", "last_name", "email"]
    missing = [f for f in required_fields if not data.get(f)]
    if missing:
        return JsonResponse({"error": f"Missing required fields: {', '.join(missing)}"}, status=400)

    try:
        status_value = (data.get("status") or "new").strip()
        status_value = status_value.lower()
        if status_value not in dict(Lead.STATUS_CHOICES):
            status_value = "new"

        lead = Lead.objects.create(
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=data["email"],
            phone=data.get("phone", ""),
            source=data.get("source", "API"),
            notes=data.get("notes", ""),
            assigned_to=data.get("assigned_to", ""),
            status=status_value,
            external_id=data.get("external_id") or None,
            created_at=timezone.now(),
            created_by_id=1,  # adjust if needed
        )
        standard_fields = {
            "first_name",
            "last_name",
            "email",
            "phone",
            "source",
            "notes",
            "assigned_to",
            "status",
            "external_id",
        }
        saved_custom = _save_custom_fields(lead, data, standard_fields, object_name="Lead")
        return JsonResponse(
            {"message": "Lead created", "leadId": lead.leadId, "custom_fields_saved": saved_custom},
            status=201,
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# -----------------------------
# API v1: Orchestrator + Quote Agent
# -----------------------------

def _auth_from_headers(request):
    """Validate X-API-KEY and return tenant if valid."""
    api_key = request.headers.get("X-API-KEY")
    if not api_key:
        return JsonResponse({"error": "Missing X-API-KEY header"}, status=403)
    try:
        tenant = Tenant.objects.get(api_key=api_key)
    except Tenant.DoesNotExist:
        return JsonResponse({"error": "Invalid API key"}, status=403)
    return tenant


@csrf_exempt
def orchestrate_v1(request):
    """POST /api/v1/orchestrator/

    Headers: X-API-KEY
    Body: {
        "username": str,
        "message": str,
        "session_id"?: str,
        "session_data"?: object
    }
    """
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    auth = _auth_from_headers(request)
    if isinstance(auth, JsonResponse):
        return auth
    tenant = auth

    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # ✅ Required fields
    message = (data.get("message") or "").strip()
    username = (data.get("username") or "").strip()

    if not message:
        return JsonResponse({"error": "'message' is required"}, status=400)
    if not username:
        return JsonResponse({"error": "'username' is required in body"}, status=400)

    session_data = data.get("session_data") or {}
    if not isinstance(session_data, dict):
        return JsonResponse({"error": "'session_data' must be an object"}, status=400)

    if data.get("session_id"):
        session_data["session_id"] = data["session_id"]

    try:
        result = handle_user_request(username, message, session_data)
    except Exception as e:
        return JsonResponse({"error": f"Internal error: {str(e)}"}, status=500)

    return JsonResponse({
        "response": result,
        "session_data": session_data,
    }, status=200)
