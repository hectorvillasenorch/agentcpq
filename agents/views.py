import json
import logging
import os
import uuid

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.db import connection
from django.db.utils import OperationalError, ProgrammingError
from django.http import JsonResponse
from django.shortcuts import render
from django.template.context_processors import csrf
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt

from dotenv import load_dotenv

from agents.models import ChatSession, SingleRecordLayout
from agents.knowledge_agent import resolve_knowledge_video_request
from cpq.models import Quote, QuotePendingAttachment


from .orchestrator import handle_user_request  # or orchestrate_request if needed


ALLOWED_ATTACHMENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
}
MAX_ATTACHMENT_SIZE = 8 * 1024 * 1024  # 8 MB

logger = logging.getLogger(__name__)

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4"


@xframe_options_exempt
@login_required
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
            "message": f"✅ Opportunity `{user_message}` added. "
                        "Would you like to add products now?"
        }

    if pending_action == "confirm_product_addition":
        session_data["product_sku"] = user_message
        session_data["pending_action"] = None
        return {
            "message": f"✅ Product `{user_message}` added to the quote."
        }

    if pending_action == "delete_quote_confirmation":
        normalized_response = user_message.strip().lower()

        if normalized_response == "yes":
            session_data["pending_action"] = "delete_quote_confirmed"
            return {
                "message": "delete quote"
            }
        elif normalized_response == "no":
            session_data["pending_action"] = None
            return {
                "message": "🛑 Quote deletion cancelled. The quote was not deleted."
            }
        else:
            session_data["pending_action"] = None
            return {
                "message": "❌ Quote deletion process cancelled. Reason: The user did not respond with a valid answer (expected: 'yes' or 'no')"
            }

    if pending_action == "knowledge_video_follow_up":
        return resolve_knowledge_video_request(user_message, session_data)


    return None  # Unrecognized or no pending action to handle


@csrf_exempt
def chat_with_gpt(request):
    """API endpoint to process user messages and route them based on AI-determined intent."""

    # --- 1. Validate request method ---
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method. Use POST."}, status=405)

    # --- 2. Log basic info ---
    opportunity_id = request.GET.get("opportunity_id", "No Opportunity ID provided")
    #logger.info(f"🔹 DEBUG: Incoming request URL - {request.build_absolute_uri()}")
    #logger.info(f"🔹 DEBUG: Extracted Opportunity ID - {opportunity_id}")
    logger.info(f"USER LOGGED IN - {request.user.username}")

    # --- 3. Parse JSON body ---
    try:
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()
        custom_session_id = data.get("session_id")  # 👈 Get in from Frontend
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON format."}, status=400)

    if not user_message:
        return JsonResponse({"error": "Message cannot be empty."}, status=400)

    # --- 4. Load session data ---
    session_data = request.session.get("session_data", {})
    #logger.info(f"🔹 DEBUG: Session Data: {session_data}")

    # --- 4.1 Load custom session data if exist---
    if custom_session_id:
        session_data["session_id"] = custom_session_id

    #Debbug the session id if is custom or not
    logger.info(f"🔹 REQUEST: Session Data: {request.session.get('session_data', {})}")

    # --- 5. Handle pending actions (if any) ---
    pending_action = session_data.get("pending_action")
    if pending_action:
        logger.info(f"🔄 Resuming pending action: {pending_action}")
        result = _handle_pending_action(pending_action, user_message, session_data)
        if result:
            #If user confirmed deletion quote
            if session_data.get("pending_action") == "delete_quote_confirmed":
                user_message = result["message"]
            else:
                # If the pending action was fulfilled, update session and return immediately
                request.session["session_data"] = session_data
                logger.info(f"[Pending Action Resolved] Response: {result['message']}")
                return JsonResponse({"response": result})

    if "session_id" not in session_data:
        user_obj = User.objects.get(username=request.user.username)
        new_chat_session = ChatSession.objects.create(
            session_id=str(uuid.uuid4()),  # 🔹 Esto asegura que sea único
            user=user_obj,
            title=user_message[:30]
        )
        session_data["session_id"] = str(new_chat_session.session_id)
        request.session["session_data"] = session_data

        try:
            ai_response = handle_user_request(request.user.username, user_message, session_data)
        except Exception as e:
            logger.error(f"❌ Error in Orchestrator logic: {e}", exc_info=True)
            return JsonResponse({"error": "Internal server error."}, status=500)

        # --- 7. Save updated session data ---
        request.session["session_data"] = session_data

        return JsonResponse({
            "response": {
                "response": ai_response,
                "session_created": True,
                "redirect_url": f"/dashboard/?view=agents&session_id={new_chat_session.session_id}"
            }
        })

    # --- 6. No pending action -> Orchestrate new user request ---
    try:
        ai_response = handle_user_request(request.user.username, user_message, session_data)
    except Exception as e:
        logger.error(f"❌ Error in Orchestrator logic: {e}", exc_info=True)
        return JsonResponse({"error": "Internal server error."}, status=500)

    # --- 7. Save updated session data ---
    request.session["session_data"] = session_data

    #print("\n\nEsto es session_data:\n")
    #print(json.dumps(session_data["state"], indent=2, ensure_ascii=False))
    #print("\n\n")

    logger.info(f"\n\n > > > [Orchestrator] AI Response: {ai_response}\n\n")

    return JsonResponse({"response": ai_response})


@csrf_exempt
@login_required
def single_record_layout(request):
    """Persist and return per-user single-record layout preferences."""

    if request.method == "GET":
        object_name = request.GET.get("object")
        if not object_name:
            return JsonResponse({"error": "object is required"}, status=400)

        layout_obj = SingleRecordLayout.objects.filter(user=request.user, object_name=object_name).first()
        layout_data = layout_obj.layout if layout_obj and isinstance(layout_obj.layout, dict) else {}
        return JsonResponse({
            "order": layout_data.get("order", []),
            "hidden": layout_data.get("hidden", []),
        })

    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON."}, status=400)

        object_name = data.get("object")
        if not object_name:
            return JsonResponse({"error": "object is required"}, status=400)

        order = data.get("order") if isinstance(data.get("order"), list) else []
        hidden = data.get("hidden") if isinstance(data.get("hidden"), list) else []

        SingleRecordLayout.objects.update_or_create(
            user=request.user,
            object_name=object_name,
            defaults={"layout": {"order": order, "hidden": hidden}},
        )

        return JsonResponse({"order": order, "hidden": hidden})

    return JsonResponse({"error": "Method not allowed"}, status=405)


@csrf_exempt
@login_required
def upload_quote_attachment(request):
    def attachment_table_ready() -> bool:
        try:
            return QuotePendingAttachment._meta.db_table in connection.introspection.table_names()
        except (ProgrammingError, OperationalError) as exc:
            logger.warning("Skipping attachment operation; table check failed: %s", exc)
            return False

    session_data = request.session.get("session_data", {})
    active_quote = session_data.get("active_quote")

    if not active_quote or not active_quote.get("quote_id"):
        return JsonResponse({
            "error": "No active quote found. Open or create a quote before uploading attachments."
        }, status=400)

    try:
        quote = Quote.objects.get(id=active_quote["quote_id"])
    except Quote.DoesNotExist:
        return JsonResponse({
            "error": "The quote linked to this session no longer exists."
        }, status=404)

    table_available = attachment_table_ready()
    session_pending = session_data.setdefault("session_pending_attachments", {})
    quote_key = str(quote.id)

    if request.method == "GET":
        if table_available:
            try:
                attachments = QuotePendingAttachment.objects.filter(quote=quote, consumed=False)
            except (ProgrammingError, OperationalError) as exc:
                logger.warning("Failed to load pending attachments for quote %s: %s", quote.id, exc)
                attachments = []
            payload = [
                {
                    "id": attachment.id,
                    "original_name": attachment.original_name or os.path.basename(attachment.file.name),
                    "mime_type": attachment.mime_type,
                    "uploaded_at": attachment.uploaded_at.isoformat(),
                }
                for attachment in attachments
            ]
        else:
            payload = [
                {
                    "id": entry["id"],
                    "original_name": entry.get("original_name", os.path.basename(entry.get("stored_path", ""))),
                    "mime_type": entry.get("mime_type", ""),
                    "uploaded_at": entry.get("uploaded_at"),
                }
                for entry in session_pending.get(quote_key, [])
            ]
        request.session["session_data"] = session_data
        return JsonResponse({"attachments": payload})

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)

    upload = request.FILES.get("file")
    if not upload:
        return JsonResponse({"error": "No file provided."}, status=400)

    if upload.size > MAX_ATTACHMENT_SIZE:
        return JsonResponse({
            "error": "File too large. Limit attachments to 8 MB."
        }, status=400)

    content_type = (upload.content_type or "").lower()
    if content_type not in ALLOWED_ATTACHMENT_TYPES:
        return JsonResponse({
            "error": "Unsupported file type. Please upload a PNG, JPG, GIF, or WEBP image."
        }, status=400)

    tenant_id = quote.account.tenant_id or "shared"
    _, extension = os.path.splitext(upload.name)
    safe_extension = extension.lower() or ""
    storage_dir = f"tenant_{tenant_id}/quote_uploads/{quote.id}"
    storage_name = f"{uuid.uuid4().hex}{safe_extension}"
    storage_path = os.path.join(storage_dir, storage_name)

    saved_path = default_storage.save(storage_path, upload)

    if table_available:
        attachment = QuotePendingAttachment(
            quote=quote,
            uploaded_by=request.user,
            original_name=upload.name,
            mime_type=content_type,
        )
        attachment.file.name = saved_path
        attachment.save()

        response_attachment = {
            "id": attachment.id,
            "original_name": attachment.original_name,
            "mime_type": attachment.mime_type,
            "uploaded_at": attachment.uploaded_at.isoformat(),
        }
    else:
        entry_id = uuid.uuid4().hex
        now_iso = timezone.now().isoformat()
        entry = {
            "id": entry_id,
            "stored_path": saved_path,
            "original_name": upload.name,
            "mime_type": content_type,
            "uploaded_at": now_iso,
        }
        session_pending.setdefault(quote_key, []).append(entry)
        request.session["session_data"] = session_data
        response_attachment = {
            "id": entry_id,
            "original_name": upload.name,
            "mime_type": content_type,
            "uploaded_at": now_iso,
        }

    return JsonResponse({
        "message": "Attachment uploaded successfully.",
        "attachment": response_attachment,
    }, status=201)
