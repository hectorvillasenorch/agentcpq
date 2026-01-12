import json
import logging
import os
import uuid
import openai

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

from agents.models import ChatMessage, ChatSession, SingleRecordLayout
from cpq.action_trigger.signal_controls import set_skip_signals
from agents.standard_record_agent import MODEL_MAP, EXTRA_FIELDS, _refresh_allowed_fields
from cpq.models import CustomField, CustomObject
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
OPENAI_BATCH_MODEL = os.getenv("OPENAI_BATCH_MODEL", "gpt-4o-mini")


def _build_batch_schema_objects():
    _refresh_allowed_fields()

    objects = []

    def _humanize(value):
        text = str(value or "").replace("_", " ").strip()
        return text.title() if text else ""

    def _collect_headers(field_names):
        headers = set()
        for name in field_names:
            if not name:
                continue
            headers.add(str(name))
            human = _humanize(name)
            if human:
                headers.add(human)
        return headers

    for object_name, model in MODEL_MAP.items():
        model_fields = [
            f.name
            for f in model._meta.get_fields()
            if not getattr(f, "auto_created", False)
            and getattr(f, "editable", True)
            and not f.many_to_many
        ]
        extras = EXTRA_FIELDS.get(object_name, [])

        custom_fields = list(
            CustomField.objects.filter(custom_object__isnull=True, object_type=object_name)
        )
        custom_field_names = [cf.name for cf in custom_fields if cf.name] or []

        canonical_fields = list({*model_fields, *extras, *custom_field_names})

        headers = _collect_headers(canonical_fields)
        for field in model._meta.get_fields():
            if getattr(field, "auto_created", False) or field.many_to_many:
                continue
            if not getattr(field, "editable", True):
                continue
            verbose = getattr(field, "verbose_name", None)
            if verbose:
                headers.add(str(verbose))
                headers.add(_humanize(verbose))

        for cf in custom_fields:
            if cf.label:
                headers.add(cf.label)
                headers.add(_humanize(cf.label))

        labels = {object_name}
        labels.add(_humanize(object_name))
        if not object_name.lower().endswith("s"):
            labels.add(f"{object_name}s")
            labels.add(_humanize(f"{object_name}s"))

        objects.append({
            "name": object_name,
            "label": object_name,
            "labels": sorted(labels),
            "fields": sorted(set(canonical_fields)),
            "headers": sorted(h for h in headers if h),
        })

    for custom_object in CustomObject.objects.prefetch_related("custom_fields").all():
        object_name = custom_object.name
        label = custom_object.label or object_name
        headers = set()
        labels = {object_name, label}
        labels.add(_humanize(label))
        if not str(label).lower().endswith("s"):
            labels.add(f"{label}s")
            labels.add(_humanize(f"{label}s"))

        canonical_fields = ["custom_identifier"]
        headers.update(_collect_headers(canonical_fields))

        for cf in custom_object.custom_fields.all():
            if cf.name:
                canonical_fields.append(cf.name)
            if cf.label:
                headers.add(cf.label)
                headers.add(_humanize(cf.label))
            if cf.name:
                headers.add(cf.name)
                headers.add(_humanize(cf.name))

        objects.append({
            "name": object_name,
            "label": label,
            "labels": sorted(labels),
            "fields": sorted(set(canonical_fields)),
            "headers": sorted(h for h in headers if h),
        })

    return objects


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
        batch_info = data.get("batch_info")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON format."}, status=400)

    if not user_message:
        return JsonResponse({"error": "Message cannot be empty."}, status=400)

    # --- 4. Load session data ---
    session_data = request.session.get("session_data", {})
    #logger.info(f"🔹 DEBUG: Session Data: {session_data}")

    if isinstance(batch_info, dict):
        index = batch_info.get("index")
        total = batch_info.get("total")
        label = batch_info.get("label")
        if isinstance(index, int) and isinstance(total, int) and total > 0 and index > 0:
            session_data["batch_info"] = {
                "index": index,
                "total": total,
                "label": label or "",
            }

    # --- 4.1 Load custom session data if exist---
    if custom_session_id:
        session_data["session_id"] = custom_session_id
    elif session_data.get("session_id"):
        # If the client didn't send a session_id (new chat screen), start fresh.
        session_data = {}
        request.session["session_data"] = session_data

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

        skip_signals = isinstance(batch_info, dict)
        try:
            if skip_signals:
                set_skip_signals(True)
            ai_response = handle_user_request(request.user.username, user_message, session_data)
        except Exception as e:
            logger.error(f"❌ Error in Orchestrator logic: {e}", exc_info=True)
            return JsonResponse({"error": "Internal server error."}, status=500)
        finally:
            if skip_signals:
                set_skip_signals(False)

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
    skip_signals = isinstance(batch_info, dict)
    try:
        if skip_signals:
            set_skip_signals(True)
        ai_response = handle_user_request(request.user.username, user_message, session_data)
    except Exception as e:
        logger.error(f"❌ Error in Orchestrator logic: {e}", exc_info=True)
        return JsonResponse({"error": "Internal server error."}, status=500)
    finally:
        if skip_signals:
            set_skip_signals(False)

    # --- 7. Save updated session data ---
    request.session["session_data"] = session_data

    return JsonResponse({"response": ai_response})


@csrf_exempt
@login_required
def log_agent_message(request):
    """Persist a lightweight agent message without triggering the orchestrator."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method. Use POST."}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON format."}, status=400)

    message = (data.get("message") or "").strip()
    session_id = data.get("session_id")
    if not message:
        return JsonResponse({"error": "message is required"}, status=400)
    if not session_id:
        return JsonResponse({"error": "session_id is required"}, status=400)

    chat_session = ChatSession.objects.filter(session_id=session_id, user=request.user).first()
    if not chat_session:
        return JsonResponse({"error": "session not found"}, status=404)

    hidden = bool(data.get("hiddenMessage", False))
    ChatMessage.objects.create(
        session=chat_session,
        sender="agent",
        content=message,
        hiddenMessage=hidden,
    )

    return JsonResponse({"ok": True})


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
def list_record_layout(request):
    """Persist and return per-user list-record layout preferences."""

    if request.method == "GET":
        object_name = request.GET.get("object")
        if not object_name:
            return JsonResponse({"error": "object is required"}, status=400)

        layout_key = f"{object_name}__list"
        layout_obj = SingleRecordLayout.objects.filter(user=request.user, object_name=layout_key).first()
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
        layout_key = f"{object_name}__list"

        SingleRecordLayout.objects.update_or_create(
            user=request.user,
            object_name=layout_key,
            defaults={"layout": {"order": order, "hidden": hidden}},
        )

        return JsonResponse({"order": order, "hidden": hidden})

    return JsonResponse({"error": "Method not allowed"}, status=405)


@csrf_exempt
@login_required
def batch_schema(request):
    """Return available object fields for batch imports (standard + custom)."""
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    return JsonResponse({"objects": _build_batch_schema_objects()})


@csrf_exempt
@login_required
def batch_map(request):
    """Map batch headers to canonical field names using the LLM."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    object_name = payload.get("object")
    headers = payload.get("headers")
    if not object_name or not isinstance(headers, list):
        return JsonResponse({"error": "object and headers are required"}, status=400)

    objects = _build_batch_schema_objects()
    object_info = next(
        (obj for obj in objects if str(obj.get("name", "")).lower() == str(object_name).lower()
         or str(object_name).lower() in [lbl.lower() for lbl in obj.get("labels", [])]),
        None,
    )
    if not object_info:
        return JsonResponse({"error": "Unknown object."}, status=400)

    allowed_fields = object_info.get("fields", [])
    if not allowed_fields:
        return JsonResponse({"mapped_headers": [None for _ in headers], "unmapped_headers": headers})

    system_prompt = (
        "You map user-provided column headers to canonical field names. "
        "Return JSON only: {\"mapped_headers\": [..]} with one entry per header in order. "
        "Each entry must be one of the allowed field names or null. "
        "Do not invent field names."
    )
    user_prompt = json.dumps({
        "object": object_info.get("name"),
        "headers": headers,
        "allowed_fields": allowed_fields,
    })

    mapped_headers = [None for _ in headers]
    if OPENAI_API_KEY:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        try:
            response = client.chat.completions.create(
                model=OPENAI_BATCH_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
            )
            raw = response.choices[0].message.content.strip()
            result = json.loads(raw)
            if isinstance(result, dict) and isinstance(result.get("mapped_headers"), list):
                mapped_headers = result["mapped_headers"]
        except Exception as exc:
            logger.warning("Batch header mapping failed: %s", exc)

    normalized_allowed = {str(field).lower(): field for field in allowed_fields}
    normalized_headers = []
    for header in headers:
        norm = str(header or "").lower().replace(" ", "").replace("_", "")
        normalized_headers.append(norm)

    cleaned_headers = []
    for idx, mapped in enumerate(mapped_headers):
        if mapped:
            key = str(mapped).lower()
            cleaned_headers.append(normalized_allowed.get(key))
            continue
        header_norm = normalized_headers[idx]
        best = None
        for field in allowed_fields:
            field_norm = str(field).lower().replace(" ", "").replace("_", "")
            if field_norm == header_norm or header_norm.startswith(field_norm) or field_norm.startswith(header_norm):
                if not best or len(field_norm) > len(best):
                    best = field
        cleaned_headers.append(best)

    unmapped = []
    final_headers = []
    for idx, header in enumerate(cleaned_headers):
        if header and header in allowed_fields:
            final_headers.append(header)
        else:
            final_headers.append(None)
            unmapped.append(headers[idx])

    return JsonResponse({
        "mapped_headers": final_headers,
        "unmapped_headers": unmapped,
    })


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
