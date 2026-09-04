import json
import logging
import os
import threading
import uuid
import openai

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.db import connection
from django.db.utils import OperationalError, ProgrammingError
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.template.context_processors import csrf
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt

from dotenv import load_dotenv

from agents.models import ChatMessage, ChatSession, SingleRecordLayout
from cpq.action_trigger.signal_controls import set_skip_signals
from agents.standard_record_agent import MODEL_MAP, EXTRA_FIELDS, _refresh_allowed_fields
from agents.llm import chat_json, get_llm_client, get_model
from agents.streaming import StreamSink, set_sink
from cpq.models import CustomField, CustomObject
from agents.knowledge_agent import resolve_knowledge_video_request
from cpq.models import Quote, QuotePendingAttachment, Product
from django.db.models import Q


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
OPENAI_MODEL = get_model("reasoning")
OPENAI_BATCH_MODEL = os.getenv("OPENAI_BATCH_MODEL", get_model("structured"))


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
@login_required
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
    sf_context = request.session.get("sf_launch_context") or {}
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

    if sf_context:
        session_data.setdefault("sf_account_id", sf_context.get("sf_account_id"))
        session_data.setdefault("sf_opportunity_id", sf_context.get("sf_opportunity_id"))
        session_data.setdefault("account", sf_context.get("account_name"))
        session_data.setdefault("opportunity", sf_context.get("opportunity_name"))

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
def chat_with_gpt_stream(request):
    """SSE endpoint that streams agent progress (LLM tokens + list rows).

    Mirrors the essential session setup of ``chat_with_gpt``, then runs the
    orchestrator on a worker thread while streaming events to the client:
      - ``token``: an incremental piece of LLM-generated text
      - ``rows``:  a serialized record list (object + rows)
      - ``done``:  the final orchestrator response
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method. Use POST."}, status=405)

    try:
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()
        custom_session_id = data.get("session_id")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON format."}, status=400)

    if not user_message:
        return JsonResponse({"error": "Message cannot be empty."}, status=400)

    # --- Load session data (same as chat_with_gpt) ---
    session_data = request.session.get("session_data", {})
    if custom_session_id:
        session_data["session_id"] = custom_session_id
    elif session_data.get("session_id"):
        session_data = {}
        request.session["session_data"] = session_data

    if "session_id" not in session_data:
        user_obj = User.objects.get(username=request.user.username)
        new_chat_session = ChatSession.objects.create(
            session_id=str(uuid.uuid4()),
            user=user_obj,
            title=user_message[:30],
        )
        session_data["session_id"] = str(new_chat_session.session_id)
        request.session["session_data"] = session_data

    sink = StreamSink()
    result_holder: dict = {}

    def _worker():
        set_sink(sink)
        try:
            ai_response = handle_user_request(request.user.username, user_message, session_data)
            result_holder["response"] = ai_response
        except Exception as exc:  # noqa: BLE001
            logger.error("Stream orchestrator error: %s", exc, exc_info=True)
            result_holder["error"] = str(exc)
        finally:
            set_sink(None)
            sink.finish()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

    def _events():
        def _default(o):
            if hasattr(o, "pk"):
                return o.pk
            if hasattr(o, "isoformat"):
                return o.isoformat()
            try:
                return str(o)
            except Exception:  # noqa: BLE001
                return repr(o)

        try:
            while True:
                item = sink.q.get()
                if item is None:
                    break
                yield (
                    f"event: {item['event']}\n"
                    f"data: {json.dumps(item['data'], ensure_ascii=False, default=_default)}\n\n"
                )
            # Worker finished — persist session, then report the final result.
            try:
                request.session["session_data"] = session_data
                request.session.save()
            except Exception:  # noqa: BLE001
                pass
            if result_holder.get("error"):
                yield (
                    "event: error\n"
                    f"data: {json.dumps({'message': result_holder['error']})}\n\n"
                )
            else:
                yield (
                    "event: done\n"
                    f"data: {json.dumps({'response': result_holder.get('response')}, ensure_ascii=False, default=_default)}\n\n"
                )
        except GeneratorExit:
            pass

    response = StreamingHttpResponse(_events(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@csrf_exempt
@login_required
def search_products(request):
    """Search products by name or SKU for the quote line editor's add-line picker."""
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"products": []})
    products = Product.objects.filter(Q(name__icontains=q) | Q(sku__icontains=q))[:10]
    data = [
        {
            "id": p.id,
            "name": p.name,
            "sku": p.sku,
            "price": str(p.price),
            "is_subscription": bool(p.is_subscription),
        }
        for p in products
    ]
    return JsonResponse({"products": data})


@csrf_exempt
@login_required
def update_action_trigger(request, trigger_id):
    """Update an existing ActionTrigger (name/description/event_type/conditions/actions/active)."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed."}, status=405)

    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    from cpq.models import ActionTrigger

    try:
        trigger = ActionTrigger.objects.get(pk=trigger_id)
    except ActionTrigger.DoesNotExist:
        return JsonResponse({"error": "Action trigger not found."}, status=404)

    if "name" in body and str(body.get("name") or "").strip():
        trigger.name = str(body["name"]).strip()
    if "description" in body:
        trigger.description = body.get("description") or ""
    if "event_type" in body:
        trigger.event_type = body["event_type"]
    if "conditions" in body:
        trigger.conditions = body["conditions"]
    if "actions" in body:
        trigger.actions = body["actions"]
    if "active" in body:
        trigger.active = bool(body["active"])

    try:
        trigger.full_clean()
        trigger.save()
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    from .utils.action_trigger.general_helpers import get_action_triggers_details

    details = get_action_triggers_details([trigger])
    return JsonResponse({"trigger": details[0] if details else None})


@csrf_exempt
@login_required
def search_records(request):
    """Search records of an object by name/email/etc. for lookup-field comboboxes."""
    object_name = (request.GET.get("object") or "").strip()
    q = (request.GET.get("q") or "").strip()
    if not object_name or not q:
        return JsonResponse({"results": []})

    from agents.utils.analytics_agent.handle_helpers import get_object_metadata
    from agents.utils.record_agent.handle_helpers import _friendly_label_for_record

    metadata = get_object_metadata(object_name)
    if not metadata:
        # User-like targets (Owner / Created By / Assigned To) search by email+username.
        if object_name == "User":
            from django.contrib.auth import get_user_model

            users = get_user_model().objects.filter(Q(email__icontains=q) | Q(username__icontains=q))[:8]
            return JsonResponse(
                {
                    "results": [
                        {"value": str(u.pk), "label": u.get_full_name() or u.email or u.username}
                        for u in users
                    ]
                }
            )
        return JsonResponse({"results": []})

    model = metadata["model"]
    custom_object = metadata["custom_object"]
    queryset = model.objects.all()
    if custom_object is not None:
        queryset = queryset.filter(object_type=custom_object)

    field_names = {f.name for f in model._meta.get_fields()}
    search_filter = Q()
    for key in ("name", "title", "subject", "email", "username", "company", "company_name", "sku", "phone", "domain", "custom_identifier"):
        if key in field_names:
            search_filter |= Q(**{f"{key}__icontains": q})
    if "first_name" in field_names or "last_name" in field_names:
        search_filter |= Q(first_name__icontains=q) | Q(last_name__icontains=q)
    if not search_filter:
        return JsonResponse({"results": []})

    limit = min(int(request.GET.get("limit", 8)), 25)
    results = []
    for record in queryset.filter(search_filter).distinct()[:limit]:
        label = _friendly_label_for_record(record)
        if label:
            results.append({"value": str(getattr(record, "pk", "")), "label": str(label)})
    return JsonResponse({"results": results})


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
        client = get_llm_client()
        try:
            response = chat_json(
                client,
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


@login_required
def agents_spa(request):
    """Serve the React chat SPA shell."""
    return render(request, "agents_spa.html")


@csrf_exempt
@login_required
def chat_sessions_api(request):
    """GET /agents/api/sessions/ → the user's chat sessions (newest first)."""
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    sessions = ChatSession.objects.filter(user=request.user).order_by("-created_at")
    data = [
        {
            "session_id": s.session_id,
            "title": s.title or "Untitled Session",
            "created_at": s.created_at.isoformat(),
        }
        for s in sessions
    ]
    return JsonResponse({"sessions": data})


@csrf_exempt
@login_required
def chat_messages_api(request):
    """GET /agents/api/messages/?session_id=... → messages for a session."""
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    session_id = request.GET.get("session_id")
    if not session_id:
        return JsonResponse({"error": "session_id is required"}, status=400)
    try:
        session = ChatSession.objects.get(session_id=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        return JsonResponse({"error": "session not found"}, status=404)
    messages = ChatMessage.objects.filter(session=session).order_by("timestamp")
    data = [
        {
            "sender": m.sender,
            "content": m.content,
            "timestamp": m.timestamp.isoformat(),
            "hidden": m.hiddenMessage,
        }
        for m in messages
    ]
    return JsonResponse({"messages": data})
