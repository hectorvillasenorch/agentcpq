import json
import uuid
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from cpq.models import Lead  # Adjust path as needed

@csrf_exempt
def receive_lead(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # ✅ Required fields
    required_fields = ["first_name", "last_name", "email"]
    missing = [f for f in required_fields if not data.get(f)]
    if missing:
        return JsonResponse({"error": f"Missing required fields: {', '.join(missing)}"}, status=400)

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
            created_by_id=1,
        )
        return JsonResponse({"message": "Lead created", "leadId": lead.leadId}, status=201)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)