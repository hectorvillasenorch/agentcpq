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
from agents.llm import chat_json, get_llm_client, get_model, llm_configured
from agents.streaming import StreamSink, set_sink
from cpq.models import CustomField, CustomObject
from agents.knowledge_agent import resolve_knowledge_video_request
from cpq.models import Account, Activity, Contact, Lead, Opportunity, Quote, QuotePendingAttachment, Product
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
def quote_details_api(request):
    """Lightweight JSON endpoint: fresh quote details (editor payload) for a quote id.

    Lets the SPA silently refresh an open quote card after a related record
    (e.g. the Opportunity) was renamed, instead of showing a stale snapshot.
    """
    quote_id = request.GET.get("quote_id") or request.GET.get("id")
    if not quote_id:
        return JsonResponse({"error": "quote_id is required."}, status=400)
    try:
        from agents.utils.quote_agent.general_helpers import get_quote_details
        from cpq.models import Quote as _Quote

        quote = _Quote.objects.select_related("account", "opportunity").get(pk=quote_id)
        return JsonResponse(get_quote_details(quote), safe=False)
    except _Quote.DoesNotExist:
        return JsonResponse({"error": "Quote not found."}, status=404)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=500)


def _resolve_related_link_field(parent_object: str, related_object: str) -> str:
    """Which field on the related object points at the parent (config → auto-detect)."""
    from cpq.models import CustomField, CustomObject, ObjectRelationConfig

    cfg = (
        ObjectRelationConfig.objects.filter(
            parent_object__iexact=parent_object, related_object__iexact=related_object
        )
        .order_by("position")
        .first()
    )
    if cfg and (cfg.link_field or "").strip():
        return cfg.link_field.strip()

    custom = CustomObject.objects.filter(name__iexact=related_object).first()
    if custom is not None:
        for candidate in CustomField.objects.filter(custom_object=custom, data_type="lookup").exclude(lookup_model=""):
            model = (candidate.lookup_model or "").split(".")[-1]
            if model.lower() == parent_object.lower():
                return candidate.name
        return ""
    # standard objects: known relation map
    return {
        ("Quote", "Opportunity"): "opportunity",
        ("Quote", "Account"): "account",
        ("Contract", "Opportunity"): "opportunity",
        ("Activity", "Opportunity"): "opportunity",
        ("Activity", "Lead"): "lead",
        ("Activity", "Contact"): "contact",
        ("Activity", "Account"): "account",
        ("Subscription", "Quote"): "quote",
        ("Subscription", "Contract"): "contract",
        ("QuoteLine", "Quote"): "quote",
    }.get((related_object, parent_object), "")


@csrf_exempt
@login_required
def related_record_fields(request):
    """Field definitions for the 'add related record' form (custom objects + Activity)."""
    from cpq.models import CustomField, CustomObject

    parent_object = (request.GET.get("parent_object") or "").strip()
    related_object = (request.GET.get("related_object") or "").strip()
    if not parent_object or not related_object:
        return JsonResponse({"error": "parent_object and related_object are required."}, status=400)

    link_field = _resolve_related_link_field(parent_object, related_object)
    custom = CustomObject.objects.filter(name__iexact=related_object).first()

    if custom is not None:
        fields = []
        for field in CustomField.objects.filter(custom_object=custom).order_by("id"):
            is_link = field.name == link_field
            fields.append(
                {
                    "name": field.name,
                    "label": field.label or field.name,
                    "data_type": field.data_type or "text",
                    "options": field.options or [],
                    "is_link": is_link,
                    "required": bool(field.required),
                }
            )
        return JsonResponse(
            {
                "related_type": "custom",
                "object": custom.name,
                "label": custom.label,
                "link_field": link_field,
                "fields": fields,
            }
        )

    if related_object == "Activity":
        return JsonResponse(
            {
                "related_type": "standard",
                "object": "Activity",
                "label": "Activity",
                "link_field": link_field,
                "fields": [
                    {"name": "subject", "label": "Subject", "data_type": "text", "options": [], "required": True},
                    {
                        "name": "activity_type",
                        "label": "Type",
                        "data_type": "dropdown",
                        "options": ["call", "email", "meeting", "task"],
                        "required": True,
                    },
                    {
                        "name": "status",
                        "label": "Status",
                        "data_type": "dropdown",
                        "options": ["not_started", "in_progress", "completed", "deferred"],
                        "required": False,
                    },
                    {"name": "due_date", "label": "Due date", "data_type": "date", "options": [], "required": False},
                    {"name": "notes", "label": "Notes", "data_type": "textarea", "options": [], "required": False},
                ],
            }
        )

    return JsonResponse({"error": f"Adding {related_object} records from the form isn't supported yet."}, status=400)


@csrf_exempt
@login_required
def create_related_record(request):
    """Create a record of the configured related object, already linked to the parent."""
    import json as _json

    from django.contrib.contenttypes.models import ContentType
    from django.utils.dateparse import parse_date

    from cpq.models import CustomField, CustomFieldValue, CustomObject, CustomRecord

    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    try:
        payload = _json.loads(request.body.decode("utf-8") or "{}")
    except ValueError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    parent_object = str(payload.get("parent_object") or "").strip()
    parent_id = payload.get("parent_id")
    related_object = str(payload.get("related_object") or "").strip()
    values = payload.get("values") or {}
    if not parent_object or parent_id in (None, "") or not related_object:
        return JsonResponse({"error": "parent_object, parent_id and related_object are required."}, status=400)
    if not isinstance(values, dict):
        return JsonResponse({"error": "values must be an object."}, status=400)

    link_field_name = _resolve_related_link_field(parent_object, related_object)
    custom = CustomObject.objects.filter(name__iexact=related_object).first()

    # ---------- custom object (POV, G-Drive Documentation, …) ----------
    if custom is not None:
        if not link_field_name:
            return JsonResponse(
                {"error": f"No link field found from {related_object} to {parent_object}. Set it in Admin → Object Related Sections."},
                status=400,
            )
        record = CustomRecord.objects.create(object_type=custom)
        ctype = ContentType.objects.get_for_model(CustomRecord)
        fields_by_name = {f.name: f for f in CustomField.objects.filter(custom_object=custom)}

        link_field = fields_by_name.get(link_field_name)
        if link_field is None:
            record.delete()
            return JsonResponse({"error": f"Link field '{link_field_name}' not found on {related_object}."}, status=400)

        def _store(field, raw):
            if raw in (None, ""):
                return
            text = str(raw).strip()
            if not text:
                return
            if (field.data_type or "").lower() == "date":
                parsed = parse_date(text)
                if parsed is None:
                    raise ValueError(f"Invalid date '{text}' for {field.label or field.name}.")
                text = parsed.isoformat()
            CustomFieldValue.objects.create(
                field=field, record=record, content_type=ctype, object_id=record.id, value=text
            )

        try:
            for name, raw in values.items():
                field = fields_by_name.get(name)
                if field is None or field.name == link_field_name:
                    continue
                _store(field, raw)
            # the link back to the parent (store the pk, matching the form's convention)
            CustomFieldValue.objects.create(
                field=link_field, record=record, content_type=ctype, object_id=record.id, value=str(parent_id)
            )
        except ValueError as exc:
            CustomFieldValue.objects.filter(record=record).delete()
            record.delete()
            return JsonResponse({"error": str(exc)}, status=400)

        from agents.utils.record_agent.handle_helpers import serialize_record

        custom_fields = list(CustomField.objects.filter(custom_object=custom))
        record_payload = serialize_record(record, custom.name, custom, custom_fields, user=request.user)
        return JsonResponse(
            {
                "success": True,
                "message": f"✅ {custom.label or custom.name} created and linked.",
                "single_record": record_payload,
            }
        )

    # ---------- Activity (reuse the existing activity endpoint logic) ----------
    if related_object == "Activity":
        proxy = create_activity_for_record.__wrapped__ if hasattr(create_activity_for_record, "__wrapped__") else None  # noqa: F841
        from django.http import QueryDict

        activity_payload = {
            "object": parent_object,
            "record_id": parent_id,
            "subject": values.get("subject") or "",
            "activity_type": values.get("activity_type") or "call",
            "status": values.get("status") or "not_started",
            "due_date": values.get("due_date") or None,
            "notes": values.get("notes") or "",
        }
        fake_request = request
        fake_request._body = _json.dumps(activity_payload).encode()  # noqa: SLF001
        return create_activity_for_record(fake_request)

    return JsonResponse(
        {"error": f"Adding {related_object} records from the form isn't supported yet. Try chat: \"create a {related_object.lower()} for {parent_object} …\"."},
        status=400,
    )


@csrf_exempt
@login_required
def create_activity_for_record(request):
    """Create an Activity already linked to the record open in the chat record form.

    POST JSON: {object, record_id, subject, activity_type, status, due_date, notes}
    Lead/Opportunity/Contact link directly (plus their account); Account links
    directly to the account (and its newest opportunity/contact when present).
    """
    import json as _json
    from django.utils.dateparse import parse_date

    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)

    try:
        payload = _json.loads(request.body.decode("utf-8") or "{}")
    except ValueError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    object_name = str(payload.get("object") or "").strip()
    record_id = payload.get("record_id")
    subject = str(payload.get("subject") or "").strip()
    activity_type = str(payload.get("activity_type") or "call").strip()
    status = str(payload.get("status") or "not_started").strip()
    due_date = parse_date(str(payload.get("due_date"))) if payload.get("due_date") else None
    notes = str(payload.get("notes") or "").strip()

    if not object_name or record_id in (None, ""):
        return JsonResponse({"error": "object and record_id are required."}, status=400)
    if not subject:
        return JsonResponse({"error": "subject is required."}, status=400)
    if activity_type not in dict(Activity.ACTIVITY_TYPE_CHOICES):
        return JsonResponse({"error": f"Invalid activity_type '{activity_type}'."}, status=400)
    if status not in dict(Activity.STATUS_CHOICES):
        return JsonResponse({"error": f"Invalid status '{status}'."}, status=400)

    link_kwargs = {}
    linked_note = ""
    custom_account = None
    custom_object = None
    custom_record = None

    try:
        if object_name == "Lead":
            lead = Lead.objects.get(pk=record_id)
            link_kwargs["lead"] = lead
            # Lead has no direct account FK: resolve through its contact, or
            # the account created when the lead was converted.
            lead_contact = getattr(lead, "contact", None)
            if lead_contact is not None and lead_contact.account_id:
                link_kwargs["account"] = lead_contact.account
            elif getattr(lead, "converted_account_id", None):
                link_kwargs["account"] = lead.converted_account
        elif object_name == "Opportunity":
            opp = Opportunity.objects.get(pk=record_id)
            link_kwargs["opportunity"] = opp
            if opp.account_id:
                link_kwargs["account"] = opp.account
        elif object_name == "Contact":
            contact = Contact.objects.get(pk=record_id)
            link_kwargs["contact"] = contact
            if contact.account_id:
                link_kwargs["account"] = contact.account
        elif object_name == "Account":
            account = Account.objects.get(pk=record_id)
            # Link directly to the account — no opportunity/contact required.
            link_kwargs["account"] = account
            opp = account.opportunities.order_by("-id").first()
            if opp is not None:
                link_kwargs["opportunity"] = opp
                linked_note = f" (linked to Opportunity '{opp.name}')"
            else:
                contact = account.contacts.order_by("-id").first()
                if contact is not None:
                    link_kwargs["contact"] = contact
                    linked_note = f" (linked to Contact '{contact}')"
        else:
            # Custom objects: resolve an Activity parent through lookup fields
            # (e.g. a project__c record with an Account/Opportunity lookup).
            from cpq.models import CustomObject, CustomRecord

            custom_object = CustomObject.objects.filter(name__iexact=object_name).first()
            if custom_object is None:
                return JsonResponse({"error": f"Activities can't be linked directly to {object_name}."}, status=400)
            custom_record = CustomRecord.objects.filter(pk=record_id, object_type=custom_object).first()
            if custom_record is None:
                return JsonResponse({"error": f"{object_name} record not found."}, status=404)

            from cpq.views import _resolve_activity_relation_from_custom_record

            relation = _resolve_activity_relation_from_custom_record(custom_record, request.user)
            if relation.get("lead"):
                link_kwargs["lead"] = relation["lead"]
            if relation.get("contact"):
                link_kwargs["contact"] = relation["contact"]
            if relation.get("opportunity"):
                link_kwargs["opportunity"] = relation["opportunity"]
            custom_account = relation.get("account")
            if custom_account:
                link_kwargs["account"] = custom_account
            if not link_kwargs:
                # Allow activities linked only through an Activity lookup
                # custom field (e.g. project__c) even when the custom record
                # has no Lead/Contact/Opportunity/Account to resolve.
                has_activity_lookup = False
                try:
                    from cpq.models import CustomField

                    target_names = {
                        (custom_object.name or "").strip().lower(),
                        (custom_object.label or "").strip().lower(),
                    }
                    target_names.discard("")
                    for field in CustomField.objects.filter(
                        crm="AgentCPQ", object_type="Activity", data_type="lookup"
                    ):
                        lookup_ref = (field.lookup_model or "").strip().lower()
                        lookup_short = lookup_ref.split(".")[-1] if lookup_ref else ""
                        field_name = (field.name or "").lower()
                        field_label = (field.label or "").lower()
                        if lookup_short in target_names or lookup_ref in target_names or any(t in field_name or t in field_label for t in target_names):
                            has_activity_lookup = True
                            break
                except Exception:
                    has_activity_lookup = False
                if not has_activity_lookup:
                    return JsonResponse(
                        {
                            "error": (
                                "No related Lead, Contact, Opportunity, or Account was found on this "
                                "record to link the activity to."
                            )
                        },
                        status=400,
                    )
            linked_note = f" (linked via {custom_object.label or custom_object.name})"
    except (Lead.DoesNotExist, Opportunity.DoesNotExist, Contact.DoesNotExist, Account.DoesNotExist):
        return JsonResponse({"error": f"{object_name} not found."}, status=404)

    try:
        activity = Activity.objects.create(
            subject=subject,
            activity_type=activity_type,
            status=status,
            due_date=due_date,
            notes=notes,
            created_by=request.user,
            **link_kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": f"Failed to create activity: {exc}"}, status=500)

    if custom_account is not None:
        try:
            from cpq.views import _set_activity_account_lookup

            _set_activity_account_lookup(activity, custom_account)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to set activity account lookup", exc_info=True)

    # When the activity was logged against a custom object (e.g. Project),
    # persist any Activity lookup custom field that targets that object
    # (e.g. project__c) so the custom record can show the activity as related.
    if custom_object is not None and custom_record is not None:
        try:
            from django.contrib.contenttypes.models import ContentType as ActivityContentType

            from cpq.models import CustomField, CustomFieldValue

            activity_ct = ActivityContentType.objects.get_for_model(Activity)
            target_names = {
                (custom_object.name or "").strip().lower(),
                (custom_object.label or "").strip().lower(),
            }
            target_names.discard("")
            for field in CustomField.objects.filter(
                crm="AgentCPQ", object_type="Activity", data_type="lookup"
            ):
                lookup_ref = (field.lookup_model or "").strip().lower()
                lookup_short = lookup_ref.split(".")[-1] if lookup_ref else ""
                field_name = (field.name or "").lower()
                field_label = (field.label or "").lower()
                if not (
                    lookup_short in target_names
                    or lookup_ref in target_names
                    or any(t in field_name or t in field_label for t in target_names)
                ):
                    continue
                CustomFieldValue.objects.update_or_create(
                    field=field,
                    content_type=activity_ct,
                    object_id=activity.pk,
                    defaults={"value": str(custom_record.pk)},
                )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to set activity custom-object lookup", exc_info=True)

    from agents.utils.record_agent.handle_helpers import serialize_record
    from agents.utils.analytics_agent.handle_helpers import get_object_metadata

    metadata = get_object_metadata("Activity") or {}
    record_payload = serialize_record(
        activity, "Activity", None, metadata.get("custom_fields") or [], user=request.user
    )
    return JsonResponse(
        {
            "success": True,
            "message": f"✅ Activity '{subject}' created{linked_note}.",
            "single_record": record_payload,
        }
    )


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

    # Business rule: never suggest converted Leads in lookup/search comboboxes.
    if object_name == "Lead":
        queryset = queryset.exclude(status="converted")

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
    if llm_configured():
        client = get_llm_client()
        try:
            response = chat_json(
                client,
                model=get_model("structured"),
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
