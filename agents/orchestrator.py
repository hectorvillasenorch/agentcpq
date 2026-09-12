import openai
import re
import json
import os
import logging
from html import escape as html_escape
from agents.quote_agent import quote_agent
from agents.product_agent import product_agent
from agents.bundles_agent import bundles_agent
from agents.admin_agent import admin_agent
from .dealdesk_agent import dealdesk_agent
from agents.custom_object_agent import custom_object_agent
from agents.analytics_agent import analytics_agent
from agents.record_agent import record_agent
from agents.knowledge_agent import knowledge_agent
from agents.action_trigger_agent import action_trigger_agent
from agentcpq.intelligence.lead_intelligence_agent import (
    lead_intelligence_agent,
    matches_lead_intelligence_trigger,
)
from agents.standard_record_agent import standard_record_agent
from dotenv import load_dotenv
from agents.llm import get_llm_client, get_model, chat_stream, temperature_supported
from agents.models import ChatSession, ChatMessage
from functools import lru_cache


def _decode_chat_text(text: str) -> str:
    if not text:
        return ""

    decoded = text
    if "\\u" in decoded or "\\U" in decoded:
        try:
            decoded = decoded.encode("utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            pass
    return decoded


def _build_batch_prefix(session_data: dict) -> str:
    if not session_data:
        return ""
    batch_info = session_data.pop("batch_info", None)
    if not isinstance(batch_info, dict):
        return ""
    try:
        index = int(batch_info.get("index"))
        total = int(batch_info.get("total"))
    except (TypeError, ValueError):
        return ""
    if index <= 0 or total <= 0:
        return ""
    label = str(batch_info.get("label") or "").strip()
    label_text = f" {html_escape(label)}" if label else ""
    return (
        '<div class="batch-result-header">'
        f'<span class="batch-result-pill">Batch {index}/{total}</span>'
        f'<span class="batch-result-label">Results{label_text}</span>'
        "</div>"
        f'<div class="batch-result-status">✅ Batch {index}/{total} completed.</div>'
    )
from django.contrib.auth.models import User
from django.utils import timezone
from uuid import uuid4
logger = logging.getLogger(__name__)

from cpq.models import CustomObject

# TDOO STOP Call to GPT
# Pything to understand request, and catch before hitting LLM

# Context Session Helpers
from .utils.orchestrator.context_handle_helpers import estimate_cost, get_recent_messages
from .utils.orchestrator.general_helpers import run_agent_async
from .utils.orchestrator.context_handle_helpers import (
    update_message_history,
    update_summary,
    build_conversation_context,
    extract_current_request,
)


load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = get_model("classifier")
client = get_llm_client()
logging.basicConfig(level=logging.DEBUG)
openai.log = "warning"


def _safe_serialize(value):
    if isinstance(value, dict):
        return {k: _safe_serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_serialize(v) for v in value]
    try:
        import numbers
        if isinstance(value, numbers.Number) and not isinstance(value, bool):
            return float(value)
    except Exception:
        pass
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    # Handle Decimal
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            return float(value)
    except Exception:
        pass
    # Handle dates/datetimes
    try:
        from datetime import date, datetime
        if isinstance(value, (date, datetime)):
            return value.isoformat()
    except Exception:
        pass
    if hasattr(value, "__dict__") and not isinstance(value, (str, bytes)):
        return str(value)
    return value


def handle_user_request(user,user_message, session_data):
    user = User.objects.get(username=user)
    logger.info(f"USER LOGGED IN - {user}")

    if should_reset_session(user_message):
        session_data.clear()
        return {
            "message": "🔄 Session cleared! Let's start fresh. What would you like to do?",
            "session_reset": True,
            "chat_sessions": list(ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at"))
        }

    # 🧠 Shortcut manual
    message = user_message.lower()
    normalized_message = user_message.strip().lower()

    # Typo/abbreviation-tolerant copy of the message used ONLY for routing decisions
    # ("opportuntiy", "shwo", "activites"…). Handlers still receive the raw message so
    # identifiers/names keep their exact spelling.
    try:
        from agents.utils.object_understanding import normalize_text as _normalize_text

        fuzzy_message = _normalize_text(user_message)
    except Exception:
        fuzzy_message = user_message

    # Handlers get the normalized copy: identifiers are preserved (tokens with digits
    # are never rewritten), but typo'd verbs/objects are corrected for the LLM too.
    # EXCEPT structured UI payloads — normalizing their JSON would corrupt values.
    _ui_payload_prefixes = (
        "update record:",
        "update quote:",
        "update quote line:",
        "delete quote:",
        "delete quote line:",
        "add product to quote:",
        "update bundle option:",
        "delete bundle option:",
        "delete bundle component from quote:",
    )
    if user_message.strip().lower().startswith(_ui_payload_prefixes):
        dispatch_message = user_message
    else:
        dispatch_message = fuzzy_message or user_message

    # 🧠 One-off reminders: "remind me <when> to <task>" (no event needed —
    # scheduled straight into the email outbox). Accepts "remindme" (no space).
    from agents.reminders import looks_like_reminder

    if looks_like_reminder(user_message):
        try:
            from agents.reminders import create_one_off_reminder

            logging.info("Do NOT use GPT (one-off reminder)\n")
            reminder_response = create_one_off_reminder(user, user_message, session_data)
            reminder_response["routing_trace"] = ["deterministic → Reminder"]
            reminder_response["session_id"] = session_data.get("session_id")
            reminder_response["chat_sessions"] = list(
                ChatSession.objects.filter(user=user).order_by("-created_at").values(
                    "session_id", "title", "created_at"
                )
            )
            return reminder_response
        except Exception:
            logging.exception("Reminder handler failed")

    trigger_phrases = get_trigger_phrases()

    pending_dealdesk_submission = session_data.get("dealdesk_pending_submission")
    if isinstance(pending_dealdesk_submission, dict):
        lowered = normalized_message
        if any(phrase in lowered for phrase in ("submit anyway", "force submit", "submit now", "confirm submit", "proceed to submit")):
            logging.info("Do NOT use GPT (pending deal desk submission confirmation)\n")
            return orchestrate_request_trigger(user, dispatch_message, session_data, decision="SubmitForApproval")
        if any(phrase in lowered for phrase in ("cancel submission", "cancel", "stop", "nevermind", "never mind")):
            session_data.pop("dealdesk_pending_submission", None)
            return {
                "message": "Deal Desk submission canceled. No approval request was sent.",
                "session_id": session_data.get("session_id"),
                "chat_sessions": list(
                    ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at")
                ),
            }

    # 🧠 Pending standard-record delete confirmation
    pending_delete = session_data.get("pending_delete")
    if isinstance(pending_delete, dict):
        lowered = normalized_message.rstrip(".!? ")
        confirm_phrases = ("yes", "y", "yep", "yeah", "confirm", "delete", "delete it", "go ahead", "proceed", "sure", "ok", "okay", "do it")
        cancel_phrases = ("no", "n", "cancel", "stop", "never mind", "nevermind", "keep", "keep it", "abort", "don't delete", "do not delete")
        if lowered in confirm_phrases or lowered.startswith("yes ") or lowered.startswith("confirm ") or lowered.startswith("go ahead"):
            logging.info("Do NOT use GPT (pending standard-record delete confirmation)\n")
            return orchestrate_request_trigger(user, dispatch_message, session_data, decision="DeleteStandardRecord")
        if lowered in cancel_phrases or lowered.startswith("no ") or lowered.startswith("cancel ") or lowered.startswith("stop "):
            session_data.pop("pending_delete", None)
            return {
                "message": "🛑 Deletion cancelled. Nothing was deleted.",
                "session_id": session_data.get("session_id"),
                "chat_sessions": list(
                    ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at")
                ),
            }
        # Anything else while a delete is pending: clear it (safety) and continue normally.
        session_data.pop("pending_delete", None)

    # 🧠 Pending duplicate-confirmation reply (create flow): "use it" / new name / cancel
    if (session_data.get("state") or {}).get("duplicate_confirmation"):
        from agents.standard_record_agent import resolve_duplicate_confirmation

        dup_response = resolve_duplicate_confirmation(user, user_message, session_data)
        if dup_response is not None:
            logging.info("Do NOT use GPT (duplicate confirmation reply)\n")
            dup_response["routing_trace"] = ["deterministic → duplicate_resolution"]
            dup_response["chat_sessions"] = list(
                ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at")
            )
            return dup_response

    # 🧠 "did you create it?" — answer truthfully from the ACTUAL saved row,
    # never from an LLM guess. (A lead was once reported as created with an
    # email/phone that were never persisted.)
    if re.match(
        r"^(did you (?:actually )?(?:create|save)|were you able to (?:create|save)|"
        r"did (?:the |a |that |my )?[a-z ]*(?:get )?created|did it (?:get )?(?:create|save)|"
        r"did you do it|is it created|did you make it)",
        (fuzzy_message or user_message).strip().lower(),
    ):
        ar = session_data.get("active_record")
        if isinstance(ar, dict) and ar.get("object") and ar.get("record_id"):
            try:
                from agents.standard_record_agent import MODEL_MAP
                from agents.utils.message_formatters import SUCCESS_ICON
                rec_model = MODEL_MAP.get(str(ar["object"]))
                rec = rec_model.objects.filter(pk=ar["record_id"]).first() if rec_model else None
                if rec is not None:
                    label = getattr(rec, "name", None) or getattr(rec, "first_name", None) or str(rec)
                    label = f"{getattr(rec, 'first_name', '')} {getattr(rec, 'last_name', '')}".strip() or label
                    parts = [f"{SUCCESS_ICON} Yes — {ar['object']} '<b>{label}</b>' was created."]
                    obj_low = str(ar["object"]).lower()
                    if obj_low in ("lead", "contact"):
                        present = [f"{k}: {getattr(rec, k)}" for k in ("email", "phone") if getattr(rec, k, None)]
                        missing = [k for k in ("email", "phone") if not getattr(rec, k, None)]
                        if present:
                            parts.append(" · ".join(present))
                        if missing:
                            parts.append(
                                f"⚠️ Heads-up: no {', '.join(missing)} was saved — "
                                f"share the missing value(s) and I'll update the {obj_low}."
                            )
                    return {
                        "message": "<br>".join(parts),
                        "routing_trace": ["deterministic → create_confirmation"],
                        "session_id": session_data.get("session_id"),
                        "chat_sessions": list(
                            ChatSession.objects.filter(user=user).order_by("-created_at").values(
                                "session_id", "title", "created_at"
                            )
                        ),
                    }
            except Exception as exc:
                logging.warning("create_confirmation lookup failed: %s", exc)
        return {
            "message": (
                "Honest answer: I don't see any record created in this session yet. "
                "Tell me what to create (e.g. \"create lead Jane Doe, email jane@corp.com\") "
                "and I'll make it, then confirm what was actually saved."
            ),
            "routing_trace": ["deterministic → create_confirmation"],
            "session_id": session_data.get("session_id"),
        }

    # 🧠 Pending create_quote flow: user selecting an opportunity
    if session_data.get("state", {}).get("create_quote"):
        wants_opportunity_selection = (
            re.search(r"use\s+(?:the\s+)?(?:current\s+)?oppor", user_message, re.IGNORECASE)
            or re.search(r"use\s+.*\boppor", user_message, re.IGNORECASE)
            or re.search(r"(custom\s+oppor\w*\s*name|oppor\w*\s*name\s*[:=])", user_message, re.IGNORECASE)
        )
        if wants_opportunity_selection:
            logging.info("Do NOT use GPT (pending create_quote opportunity selection)\n")
            return orchestrate_request_trigger(user, dispatch_message, session_data, decision="CreateQuote")

    # 🧠 Shortcut manual: "use opportunity <name>" → CreateQuote (opportunity selection
    # for a quote). Handles the case where the pending state was already cleared.
    if (
        re.search(r"use\s+(?:the\s+)?(?:current\s+)?oppor", user_message, re.IGNORECASE)
        or re.search(r"use\s+.*\boppor", user_message, re.IGNORECASE)
    ):
        logging.info("Do NOT use GPT (opportunity selection for quote)\n")
        return orchestrate_request_trigger(user, dispatch_message, session_data, decision="CreateQuote")

    # 🧠 Pending single-record flow (follow-up identifier)
    pending_single_record = session_data.get("state", {}).get("show_single_record")
    if pending_single_record:
        lowered = user_message.lower()
        looks_like_new_action = re.search(
            r"\b(show|list|display|view|open|create|update|delete|add|remove|metrics)\b",
            lowered,
        )
        if not looks_like_new_action:
            logging.info("Do NOT use GPT (pending show_single_record follow-up)\n")
            return orchestrate_request_trigger(user, dispatch_message, session_data, decision="ShowSingleRecord")

    # 🧠 Shortcut manual: product create/update → product_agent (never standard record)
    product_action = _infer_product_action(fuzzy_message)
    if product_action:
        logging.info("Do NOT use GPT (deterministic product action)\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision=product_action)
        response["routing_trace"] = [f"deterministic → {product_action}"]
        response["chat_sessions"] = list(
            ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at")
        )
        return response

    # 🧠 Shortcut manual: custom object schema CRUD (create/update/delete the object itself)
    custom_object_schema_action = _infer_custom_object_schema_action(fuzzy_message)
    if custom_object_schema_action:
        logging.info("Do NOT use GPT (deterministic custom object schema action)\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision=custom_object_schema_action)
        response["routing_trace"] = [f"deterministic → {custom_object_schema_action}"]
        response["chat_sessions"] = list(
            ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at")
        )
        return response

    # 🧠 Shortcut: "show all activities for <object> <id/name>" → activities table.
    # Must run BEFORE the single-record shortcut so "activities" isn't treated as a record.
    activities_match = re.match(
        r"^(?:(?:can\s+you\s+)?(?:show|list|view|display|get|find|open)\s+)?(?:me\s+)?(?:all\s+|the\s+|any\s+|my\s+)?"
        r"activi\w*\s+(?:for|of|on|related\s+to|linked\s+to)\s+.+$",
        fuzzy_message.strip(),
        re.IGNORECASE,
    )
    if activities_match:
        logging.info("Do NOT use GPT (record activities → ShowRecordActivities)\n")
        response = orchestrate_request_trigger(
            user, user_message, session_data, decision="ShowRecordActivities"
        )
        response["routing_trace"] = ["deterministic → ShowRecordActivities"]
        response["chat_sessions"] = list(
            ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at")
        )
        return response

    # 🧠 Shortcut: "show details for <object> <name>" → compact text summary
    # (Name, Amount, Close Date, Stage, Account…) with an eye icon to expand the form.
    details_match = re.match(
        r"^(?:(?:can\s+you\s+)?(?:show|display|view|get|give|open)\s+)?(?:me\s+)?(?:the\s+)?details\s+(?:about|for|of|on)\s+(.+)$",
        fuzzy_message.strip(),
        re.IGNORECASE,
    )
    if details_match:
        logging.info("Do NOT use GPT (record details → ShowRecordSummary)\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="ShowRecordSummary")
        response["routing_trace"] = ["deterministic → ShowRecordSummary"]
        response["chat_sessions"] = list(
            ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at")
        )
        return response

    # 🧠 Shortcut: "show related records for X" → the single-record form already
    # includes the Related records section, so route deterministically (fast, no LLM).
    related_records_match = re.match(
        r"^(?:show|display|view)?\s*related\s+records?\s+for\s+(.+)$",
        user_message.strip(),
        re.IGNORECASE,
    )
    if related_records_match:
        logging.info("Do NOT use GPT (related records → ShowSingleRecord)\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="ShowSingleRecord")
        response["routing_trace"] = ["deterministic → ShowSingleRecord"]
        response["chat_sessions"] = list(
            ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at")
        )
        return response

    # 🧠 Shortcut: "create action trigger / create email alert" → their agents.
    # Must run BEFORE the standard-record write inference (which would otherwise
    # misread "create action trigger when an opportunity..." as CreateStandardRecord).
    trigger_intent_patterns = (
        (re.compile(r"^create\s+(?:an?\s+|a\s+)?action\s+triggers?\b", re.IGNORECASE), "CreateActionTrigger"),
        (re.compile(r"^create\s+(?:an?\s+)?email\s+alerts?\b", re.IGNORECASE), "CreateEmailAlert"),
        # "convert lead(s) → account/contact/opportunity (when qualified)" → lead-conversion trigger
        (re.compile(r"^(?:auto(?:matically)?\s+)?convert\s+(?:the\s+)?leads?\b", re.IGNORECASE), "CreateActionTrigger"),
    )
    for pattern, decision in trigger_intent_patterns:
        if pattern.match(fuzzy_message.strip()):
            logging.info("Do NOT use GPT (deterministic %s)\n", decision)
            response = orchestrate_request_trigger(user, dispatch_message, session_data, decision=decision)
            response["routing_trace"] = [f"deterministic → {decision}"]
            response["chat_sessions"] = list(
                ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at")
            )
            return response

    # 🧠 Shortcut manual: deterministic standard record writes (must run before metrics shortcuts)
    standard_write_decision = _infer_standard_record_write_decision(user_message)
    if standard_write_decision:
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(
            user,
            user_message,
            session_data,
            decision=standard_write_decision,
        )
        response["routing_trace"] = [f"deterministic → {standard_write_decision}"]
        response["chat_sessions"] = list(
            ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at")
        )
        return response

    # 🧠 Shortcut manual: deterministic quote line-item actions (add / remove)
    quote_action_decision = _infer_quote_action_decision(fuzzy_message)
    if quote_action_decision:
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(
            user,
            user_message,
            session_data,
            decision=quote_action_decision,
        )
        response["routing_trace"] = [f"deterministic → {quote_action_decision}"]
        response["chat_sessions"] = list(
            ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at")
        )
        return response

    # 🧠 Shortcut manual: "show details" (defaults to quote details)
    if normalized_message in {"show details", "show detail", "show quote details", "show quote detail"}:
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="ShowQuoteDetails")

    # 🧠 Shortcut manual: lead intelligence dashboard
    elif matches_lead_intelligence_trigger(fuzzy_message):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="ShowLeadDashboard")

    # 🧠 Shortcut manual: "show quote details for <quote_id>"
    elif user_message.lower().startswith("show quote details for "):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user,dispatch_message, session_data, decision="ShowQuoteDetails")
    # 🧠 Shortcut manual: "show quote details <quote_id>"
    elif user_message.lower().startswith("show quote details "):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="ShowQuoteDetails")

    # 🧠 Shortcut manual: "show quote Q-00002" / "show the quote Q-00002"
    elif re.search(r"\b(?:show|view|open|display)\s+(?:the\s+)?quote\s+Q-\d+", user_message, re.IGNORECASE):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="ShowQuoteDetails")

    # 🧠 Shortcut manual: "show metrics: ..."
    elif normalized_message.startswith("show metrics:"):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="ShowMetrics")

    # 🧠 Shortcut manual: list/all/latest metrics phrasing
    elif _should_shortcut_to_metrics(fuzzy_message):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="ShowMetrics")

    # 🧠 Shortcut manual: singular object should be single-record
    elif _should_shortcut_to_single_record(fuzzy_message):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="ShowSingleRecord")

    # 🧠 Shortcut manual: "Update Quote Line:"
    elif user_message.startswith("Update Quote Line:"):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="UpdateQuoteLineFromUI")

    # 🧠 Shortcut manual: "Delete Quote Line:"
    elif user_message.startswith("Delete Quote Line:"):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="DeleteQuoteLineFromUI")

    # 🧠 Shortcut manual: "Add Product To Quote:"
    elif user_message.startswith("Add Product To Quote:"):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="AddProductToQuoteFromUI")

    # 🧠 Shortcut manual: explicit create quote phrases
    elif "create a quote" in message or "create the quote" in message:
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="CreateQuote")

    elif user_message.startswith("Update Bundle Option:"):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="UpdateBundleOption")

    elif user_message.startswith("Update Quote:"):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="UpdateQuoteFromUI")

    elif user_message.startswith("Update Record:"):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="UpdateSingleRecordFromUI")

    # 🧠 Shortcut manual: Add product option to bundle (avoid misrouting to quote)
    elif re.search(r"\badd\s+(?:product\s+)?option\b.*\bbundle\b", user_message, re.IGNORECASE):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="AddProductToBundle")

    # 🧠 Shortcut manual: "generate pdf"
    elif any(message.startswith(trigger) for trigger in trigger_phrases):
        logging.info("Do NOT use GPT\n")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="GenerateQuoteDocument")

    else:
        logging.info("USE GPT\n")
        response = orchestrate_request(user, dispatch_message, session_data)

    response["chat_sessions"] = list(ChatSession.objects.filter(user=user).order_by("-created_at").values("session_id", "title", "created_at"))
    return response

def orchestrate_request(user, user_message, session_data):
    # Typo-normalized copy used by the routing guards inside the classifier.
    from agents.utils.object_understanding import normalize_text as _normalize_text

    fuzzy_message = _normalize_text(user_message) or user_message
    session_context = {
        k: str(v) for k, v in session_data.items()
        if isinstance(v, (str, int, float, list, dict))
    }

    session_id = session_data.get("session_id")

    user = User.objects.get(username=user)

    # Robust session handling: create if missing or absent
    if not session_id:
        chat_session = ChatSession.objects.create(
            user=user,
            session_id=str(uuid4()),
            title=user_message[:30]
        )
        session_data["session_id"] = chat_session.session_id
    else:
        try:
            chat_session = ChatSession.objects.get(session_id=session_id)
        except ChatSession.DoesNotExist:
            chat_session = ChatSession.objects.create(
                user=user,
                session_id=session_id,
                title=user_message[:30]
            )
            session_data["session_id"] = chat_session.session_id

    # Save user message
    decoded_initial_user_message = _decode_chat_text(user_message)
    ChatMessage.objects.create(
        session=chat_session,
        sender="user",
        content=decoded_initial_user_message
    )


    session_data.setdefault("state", {})
    # For debug
    print(f"\n\nCurrent session state: {session_data['state']}\n\n")

    # 🔹 Get or create message history on session_data
    session_data.setdefault("message_history", [])

    # 🔹 Shortcut for clear how-to requests before hitting the LLM
    if _should_shortcut_to_knowledge(user_message):
        logging.info("🔀 Shortcutting to KnowledgeLookup based on heuristic match")
        response = orchestrate_request_trigger(user, dispatch_message, session_data, decision="KnowledgeLookup")
        response["routing_trace"] = ["deterministic → KnowledgeLookup"]
        return response

    # 🔹 Build message history
    message_history = session_data.get("message_history", [])

    # 🔹 Trim the last MAX_HISTORY messages
    recent_history = get_recent_messages(message_history, max_messages=6)


    # 🔹 Build history in roles format
    messages = [
        {
            "role": "system",
            "content": """
            You are an AI assistant that classifies user requests into predefined actions.
            Only answer with ONE label from the list provided, no explanations, no emojis, do not use this emoji: ✅.
            If the user's current message is exactly the same as the previous one, it is possible that what you decided earlier was not the correct action.
            Consider changing it for this new attempt, or ask the user what they want to do.
            """
        }
    ]

    # 🔹 Add the trimmed history
    for msg in recent_history:
        role = "assistant" if msg["sender"] == "agent" else "user"
        messages.append({"role": role, "content": msg["message"]})

    # 🔹 New user message
    messages.append({"role": "user", "content": user_message})

    # 🔹 List of labels
    custom_objects = CustomObject.objects.all()
    custom_objects_list = [co.label for co in custom_objects]

    messages.append({
        "role": "system",
        "content": f"""
        CRITICAL CLASSIFICATION RULES (HIGHEST PRIORITY):

        1) DETERMINISTIC PREFIX RULE:
        If the user message STARTS WITH the exact text:
        "create action trigger"
        You MUST ALWAYS return the label:
        "CreateActionTrigger"

        Possible labels:
        - "CreateQuote"
        - "AddProductToQuote"
        - "GenerateQuoteDocument"
        - "ProvideDates"
        - "UpdateQuoteLine"
        - "UpdateQuote"
        - "ShowQuoteNotes"
        - "DeleteQuoteLine"
        - "DeleteQuote"
        - "CreateProductRecord"
        - "CreateStandardRecord"
        - "UpdateStandardRecord"
        - "DeleteStandardRecord"
        - "UpdateProductRecord"
        - "SubmitForApproval"
        - "CheckApprovalStatus"
        - "ApproveQuote"
        - "RejectQuote"
        - "RecallQuote"
        - "ShowSingleRecord"
        - "GeneralQuery"
        - "CreateValidationRule"
        - "CreateInclusionRule"
        - "ShowRules"
        - "UpdateRule"
        - "DeleteRule"
        - "AddProductToBundle"
        - "UpdateBundleOption"
        - "DeleteBundleOption"
        - "DeleteBundleComponentFromQuote"
        - "ShowBundleStructure" → Use when the user wants to view the components/options of a bundle product (SKU or name). Examples: "show bundle structure SYM-ACPQ-IMP-STARTER", "list components in bundle STARTER", "display bundle ACME-BUNDLE".
        - "CreateCustomObject"
        - "UpdateCustomObject"
        - "DeleteCustomObject"
        - "CreateCustomField"
        - "UpdateCustomField"
        - "DeleteCustomField"
        - "CreateCustomRecord" (for {custom_objects_list})
        - "UpdateCustomRecord" (for {custom_objects_list})
        - "DeleteCustomRecord" (for {custom_objects_list})
        - "CreateEmailAlert"
        - "UpdateEmailAlert"
        - "DeleteEmailAlert"
        - "ShowQuoteDetails" → Use only when the user explicitly asks to view a quote.
                The message must reference a quote (the word "quote", a quote ID, or the current quote session).
                Examples:
                    - "Show quote"
                    - "Show details of quote Q-2024-001"
                    - "Display the current quote"
                    - "Open quote Q-2024-001"
                Do NOT pick this label when the user mentions products, bundles, accounts, metrics, lists, or any non-quote record.
        - "CreateStandardRecord" → Use when the user wants to create a standard record via chat (Lead, Account, Contact, Opportunity, Activity, Contract, Subscription, Tenant, Knowledge, Option).
                Examples:
                    - "Create a lead John Doe with email john@acme.com"
                    - "Add an account named Acme in New York"
                    - "Open a new opportunity Renewal Q1 for Acme at $50k"
                    - "Create a contract for opportunity Renewal Q1 starting 2026-01-01 with status Active"
                    - "Create a knowledge article titled 'How approvals work' with content ..."
        - "UpdateStandardRecord" → Use when the user wants to update a standard record (Lead, Account, Contact, or Opportunity) via chat.
                Examples:
                    - "Update account Acme phone to 555-0101"
                    - "Change opportunity Renewal Q1 stage to negotiation"
        - "DeleteStandardRecord" → Use when the user wants to delete a standard record (Lead, Account, Contact, or Opportunity) via chat.
                Examples:
                    - "Delete lead john@acme.com"
                    - "Remove account Acme"
        - "ShowSingleRecord" → Use when the user asks to open a specific record (Account, Product, Opportunity, Lead, Contact, Quote, Activity, Contract, Subscription, Option, Tenant, Knowledge, or any custom object) and expects a detailed card view. 
                Examples:
                    - "Show account Acme Corp"
                    - "Open product SKU-1001"
                    - "Display the opportunity Renewal Q1"
                    - "Show activity Meeting with Juan"
                    - "Open contract for Renewal Q1"
                Do NOT use this for bundle component breakdowns; prefer "ShowBundleStructure" when the user asks to see bundle options/components.
        - "ShowMetrics" → Use when the user requests listings, summaries, or filtered searches 
                involving one or more records (products, quotes, accounts, bundles, etc.).  
                This includes plural forms ("quotes", "products"), aggregate/numeric comparisons,
                date filters ("last 3 days", "this month"), or numerical filters ("top 5", "all", "recent").  
                Examples:
                    - "Show me my quotes created in the last 3 days"
                    - "List all quotes pending approval"
                    - "Show my last 5 quotes"
                    - "Display all products in the catalog"
                    - "List product record TEAM-BUNDLE"
        - "KnowledgeLookup" → Use when the user asks for how-to instructions, FAQs, or training guidance (e.g. "how do I create a quote", "teach me about approvals").
        - "CreateActionTrigger"
        - "CreateExclusionRule"
        """
    })

    messages.append({
        "role": "system",
        "content": """
        Routing clarifications:
        - If the user asks to show/open/view/display a specific record (e.g., “show lead with phone 9498724333”, “show lead Victor Lopez”, “open account ACME”), choose ShowSingleRecord. This includes lookups by phone, email, name, company, SKU, quote id, or any identifier.
        - Only use CreateStandardRecord when the user is asking to create/add a new record. Do NOT choose CreateStandardRecord when the verbs are show/open/view/display.
        - Use UpdateStandardRecord when the user says update/edit/change/modify a Lead/Account/Contact/Opportunity and provides at least one field to change.
        - Use DeleteStandardRecord when the user says delete/remove a Lead/Account/Contact/Opportunity.
        - When in doubt between ShowSingleRecord and CreateStandardRecord, prefer ShowSingleRecord if the user is requesting to see an existing record.
        """
    })

    tokens, est_cost = estimate_cost(messages, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 ORCHESTRATOR - Estimated tokens: {tokens}, approx cost: ${est_cost:.6f}\n\n")

    try:
        _create_kwargs = {"temperature": 0} if temperature_supported(OPENAI_MODEL) else {}
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            **_create_kwargs
        )

        raw_decision = response.choices[0].message.content.strip()
        decision = clean_llm_label(raw_decision)
        #decision = re.sub(r'[^\w\s\-\_\.\,]', '', decision)
        logging.info(f"\n🟢 AI Decision Received: {decision} \n")

        # Handle common model message when no active quote is found
        if "no active quote" in raw_decision.lower():
            return {
                "message": "⚠️ I couldn’t find an active quote. Please specify a quote name (e.g., Q-00066) or ask me to create a new quote."
            }

        # 🔒 Guard: write intents for standard records should not route to metrics.
        if decision == "ShowMetrics":
            standard_write_decision = _infer_standard_record_write_decision(user_message)
            if standard_write_decision:
                logging.info(
                    "Guarding against metrics for standard record write intent; rerouting to %s.",
                    standard_write_decision,
                )
                decision = standard_write_decision

        # 🔒 Guard: singular requests should open single-record, not metrics list
        if decision == "ShowMetrics" and _should_shortcut_to_single_record(fuzzy_message):
            logging.info("Guarding against metrics for singular record; rerouting to ShowSingleRecord.")
            decision = "ShowSingleRecord"

        # 🔒 Guard: plural/list requests should go to metrics, not single-record
        if decision == "ShowSingleRecord" and _should_shortcut_to_metrics(fuzzy_message):
            logging.info("Guarding against single-record for list request; rerouting to ShowMetrics.")
            decision = "ShowMetrics"

        # 🔒 Prevent accidental ShowSingleRecord unless the user explicitly asks to view a record
        if decision == "ShowSingleRecord":
            wants_record = re.search(
                r"\b(show|display|open|get|view)\b.*\b(record|opportunity|account|product|quote|contact|lead|activity|contract|subscription|option|tenant|knowledge)\b",
                user_message,
                re.IGNORECASE,
            )
            if not wants_record:
                wants_record = re.search(
                    r"\b(opportunity|account|product|quote|contact|lead|activity|contract|subscription|option|tenant|knowledge|bundle|custom\s+object|custom\s+record)\b",
                    user_message,
                    re.IGNORECASE,
                )
            if not wants_record:
                logging.info("Guarding against unintended ShowSingleRecord; rerouting to GeneralQuery.")
                decision = "GeneralQuery"

        # 🔒 Guard: list/all bundle products should go to metrics, not structure
        if decision == "ShowBundleStructure":
            wants_listing = re.search(r"\b(all|list|show)\b.*\bbundle(s)?\b", user_message, re.IGNORECASE)
            if wants_listing and not re.search(r"\bstructure\b", user_message, re.IGNORECASE):
                logging.info("Guarding against bundle listing routed to ShowBundleStructure; rerouting to ShowMetrics.")
                decision = "ShowMetrics"

    except Exception as e:
        logging.error(f"❌ Error in OpenAI call: {e}")
        return {"message": "⚠️ Sorry, an error occurred while processing your request."}

    routing_trace = [f"llm_classification → {decision}"]
    logging.info("ROUTING_TRACE: %s", routing_trace)

    action_map = get_action_map()

    if decision in action_map:
        # Skip context augmentation for structured inline-edit payloads.
        agent_input = (
            user_message
            if user_message.startswith(("Update Quote Line:", "Update Quote:", "Delete Quote Line:", "Add Product To Quote:", "Delete Quote:", "Update Record:", "Update Bundle Option:", "Delete Bundle Option:", "Delete Bundle Component From Quote:"))
            else build_conversation_context(session_data, user_message)
        )
        result = run_agent_async(action_map[decision], user, decision, agent_input, session_data)

        if result is None:
            logging.error(f"❌ Agent function for '{decision}' returned None.")
            return {"message": f"⚠️ Error: Agent function for '{decision}' returned nothing."}

        agent_message = result.get("message", "")
        hiddenMessage = result.get("hiddenMessage", False)
        suppress_chat = result.get("suppress_chat", False)

        session_summary = result.get("session_summary", None)

        if session_data and session_summary:
            update_summary(session_data, session_summary)

        sanitized_result = {
            key: _safe_serialize(value) for key, value in result.items() if key != "suppress_chat"
        }
        sanitized_result["session_id"] = session_data["session_id"]
        sanitized_result["routing_trace"] = routing_trace

        if suppress_chat:
            decoded_agent_message = _decode_chat_text(_strip_session_summary_text(agent_message))
            if session_data and decoded_initial_user_message and decoded_agent_message:
                update_message_history(session_data, decoded_initial_user_message, decoded_agent_message)

            ChatMessage.objects.create(
                session=chat_session,
                sender="agent",
                content=decoded_agent_message,
                hiddenMessage=hiddenMessage
            )

            sanitized_result["message"] = decoded_agent_message
            return sanitized_result

        for key, value in result.items():
            if key not in (
                "message", "session_id", "hiddenMessage", "temporaryMessage",
                "update_details", "iterations", "success", "quote_id", "notes",
                "tokens", "cost", "session_summary", "rules_created", "openGraphicBuilder", "cpq_model_schema",
                "single_record", "single_record_summary", "object_labels", "suppress_chat",
                "retrieved_records", "quote_details", "action_triggers_details",
                "intelligence_dashboard", "validation_rules_details", "rules",
                "email_alerts_details", "inclusion_rules_details", "exclusion_rules_details", "llm",
            ):
                agent_message += f"\n\n{key}:\n{json.dumps(_safe_serialize(value), indent=2, ensure_ascii=False)}"

        decoded_agent_message = _decode_chat_text(_strip_session_summary_text(agent_message))

        if session_data and decoded_initial_user_message and decoded_agent_message:
            update_message_history(session_data, decoded_initial_user_message, decoded_agent_message)

        # Persist structured card payloads so charts/tables re-render on refresh,
        # while keeping the visible message (and classifier context) JSON-free.
        structured_keys = (
            "single_record", "single_record_summary", "quote_details", "update_details",
            "retrieved_records", "action_triggers_details", "intelligence_dashboard",
            "validation_rules_details", "rules", "email_alerts_details",
            "inclusion_rules_details", "exclusion_rules_details",
        )
        storage_extras = ""
        for key in structured_keys:
            if result.get(key):
                storage_extras += f"\n\n{key}:\n{json.dumps(_safe_serialize(result.get(key)), indent=2, ensure_ascii=False)}"

        content_for_storage = f"{decoded_agent_message}{storage_extras}"

        ChatMessage.objects.create(
            session=chat_session,
            sender="agent",
            content=content_for_storage,
            hiddenMessage=hiddenMessage
        )

        sanitized_result["message"] = decoded_agent_message

        return sanitized_result

    logging.warning(f"⚠️ AI returned an unknown intent: {decision}")
    return {"message": "Sorry, I couldn’t understand your request. From Orchestrator"}


def orchestrate_request_trigger(user, user_message, session_data, decision):
    logging.info(f"\n🟢 AI Decision Trigger: {decision} \n")
    session_id = session_data.get("session_id")
    
    user = User.objects.get(username=user)

    if not session_id:
        chat_session = ChatSession.objects.create(
            user=user,
            session_id=str(uuid4()),
            title=user_message[:30]
        )
        session_data["session_id"] = chat_session.session_id
    else:
        try:
            chat_session = ChatSession.objects.get(session_id=session_id)
        except ChatSession.DoesNotExist:
            chat_session = ChatSession.objects.create(
                user=user,
                session_id=session_id,
                title=user_message[:30]
            )
            session_data["session_id"] = chat_session.session_id

    #Extract the JSON to give the hidden field (Only for update message)
    if user_message.startswith("Update Quote Line:"):
        try:
            json_str = user_message.replace("Update Quote Line:", "")
            update_data = json.loads(json_str)
            hiddenMessage = update_data.get("hiddenMessage", False)
            decoded_message = _decode_chat_text(user_message)
            ChatMessage.objects.create(
                session=chat_session,
                sender="user",
                content=decoded_message,
                hiddenMessage = hiddenMessage
            )
        except json.JSONDecodeError as e:
            logging.error(f" Error decoding JSON: {e}")
    elif user_message.startswith("Update Quote:"):
        try:
            json_str = user_message.replace("Update Quote:", "")
            update_data = json.loads(json_str)
            hiddenMessage = update_data.get("hiddenMessage", False)
            decoded_message = _decode_chat_text(user_message)
            ChatMessage.objects.create(
                session=chat_session,
                sender="user",
                content=decoded_message,
                hiddenMessage = hiddenMessage
            )
        except json.JSONDecodeError as e:
            logging.error(f" Error decoding JSON: {e}")
    elif user_message.startswith("Update Record:"):
        try:
            json_str = user_message.replace("Update Record:", "")
            update_data = json.loads(json_str)
            hiddenMessage = update_data.get("hiddenMessage", False)
            decoded_message = _decode_chat_text(user_message)
            ChatMessage.objects.create(
                session=chat_session,
                sender="user",
                content=decoded_message,
                hiddenMessage=hiddenMessage
            )
        except json.JSONDecodeError as e:
            logging.error(f" Error decoding JSON: {e}")
    elif user_message.startswith("Update Bundle Option:"):
        try:
            json_str = user_message.replace("Update Bundle Option:", "")
            update_data = json.loads(json_str)
            hiddenMessage = update_data.get("hiddenMessage", False) if isinstance(update_data, dict) else False
            decoded_message = _decode_chat_text(user_message)
            ChatMessage.objects.create(
                session=chat_session,
                sender="user",
                content=decoded_message,
                hiddenMessage=hiddenMessage
            )
        except json.JSONDecodeError as e:
            logging.error(f" Error decoding JSON: {e}")
    else:
        decoded_message = _decode_chat_text(user_message)
        ChatMessage.objects.create(
            session=chat_session,
            sender="user",
            content=decoded_message
        )

    action_map = get_action_map()

    if decision in action_map:
        # Skip context augmentation for structured inline-edit payloads.
        agent_input = (
            user_message
            if user_message.startswith(("Update Quote Line:", "Update Quote:", "Delete Quote Line:", "Add Product To Quote:", "Delete Quote:", "Update Record:", "Update Bundle Option:", "Delete Bundle Option:", "Delete Bundle Component From Quote:"))
            else build_conversation_context(session_data, user_message)
        )
        result = action_map[decision](user, decision, agent_input, session_data)

        # Maintain conversation memory for deterministic flows too, so follow-up
        # requests ("add 5 seats", "show it") have context.
        if isinstance(result, dict) and result.get("message"):
            update_message_history(
                session_data,
                _decode_chat_text(user_message),
                _strip_session_summary_text(_decode_chat_text(str(result.get("message", "")))),
            )
            # Persist the agent's rolling summary so follow-up turns (e.g. "list all 5"
            # after "how many active deals do I have") can resolve the subject.
            session_summary = result.get("session_summary")
            if session_summary:
                update_summary(session_data, session_summary)

        if decision == "ShowLeadDashboard":
            payload = result.get("intelligence_dashboard") if isinstance(result, dict) else None
            logging.info(
                "ShowLeadDashboard result keys=%s has_dashboard=%s layout_key=%s",
                sorted(result.keys()) if isinstance(result, dict) else [],
                bool(payload),
                payload.get("layout_key") if isinstance(payload, dict) else None,
            )

        batch_prefix = _build_batch_prefix(session_data)

        suppress_chat = result.get("suppress_chat", False)
        hiddenMessage = result.get("hiddenMessage", False)

        sanitized_result = {key: _safe_serialize(value) for key, value in result.items() if key != "suppress_chat"}
        sanitized_result["session_id"] = session_data["session_id"]

        if suppress_chat:
            # IMPORTANT: keep the response message user-facing (do not append JSON payloads).
            # Structured payloads (single_record / quote_details) are still returned in JSON, and can be persisted
            # separately for UI rehydration without polluting the visible message.
            display_message = _strip_session_summary_text(_decode_chat_text(result.get("message", "")))
            sanitized_result["message"] = display_message

            # Persist only the structured payloads needed to re-render the UI on refresh.
            structured_keys = ("quote_details", "single_record", "retrieved_records", "validation_rules_details")
            agent_message_for_storage = f"{batch_prefix}{display_message}" if batch_prefix else display_message
            has_structured_payload = any(key in result for key in structured_keys)
            for key in structured_keys:
                if key in result:
                    agent_message_for_storage += (
                        f"\n\n{key}:\n"
                        f"{json.dumps(_safe_serialize(result.get(key)), indent=2, ensure_ascii=False)}"
                    )

            # If there is no structured payload, persist a normal visible message.
            # This prevents plain suppress_chat responses (e.g. Deal Desk auto-approve)
            # from disappearing in chat history after refresh.
            if not has_structured_payload:
                ChatMessage.objects.create(
                    session=chat_session,
                    sender="agent",
                    content=agent_message_for_storage,
                    hiddenMessage=hiddenMessage
                )
                return sanitized_result

            last_agent_message = ChatMessage.objects.filter(
                session=chat_session,
                sender="agent",
                content__icontains="single_record"
            ).order_by("-timestamp").first()

            if last_agent_message:
                last_agent_message.content = agent_message_for_storage
                last_agent_message.hiddenMessage = True
                last_agent_message.save(update_fields=["content", "hiddenMessage"])
            else:
                ChatMessage.objects.create(
                    session=chat_session,
                    sender="agent",
                    content=agent_message_for_storage,
                    hiddenMessage=True
                )

            return sanitized_result

        agent_message = result.get("message", "")

        for key, value in result.items():
            if key not in ("message", "session_id", "hiddenMessage", "original_value", "suppress_chat", "temporaryMessage", "session_summary", "single_record", "single_record_summary", "quote_details", "update_details", "retrieved_records", "object_labels", "llm"):
                prefix = "" if key == "intelligence_dashboard" else "📦 "
                agent_message += f"\n\n{prefix}{key}:\n{json.dumps(_safe_serialize(value), indent=2, ensure_ascii=False)}"

        agent_message = _strip_session_summary_text(_decode_chat_text(agent_message))

        # Persist structured card payloads into the stored message so the UI can
        # re-render charts/tables on refresh (without polluting the visible text).
        structured_keys = (
            "single_record", "single_record_summary", "quote_details", "update_details",
            "retrieved_records", "action_triggers_details", "intelligence_dashboard",
            "validation_rules_details", "rules", "email_alerts_details",
            "inclusion_rules_details", "exclusion_rules_details",
        )
        storage_extras = ""
        for key in structured_keys:
            if result.get(key):
                storage_extras += f"\n\n{key}:\n{json.dumps(_safe_serialize(result.get(key)), indent=2, ensure_ascii=False)}"

        agent_message_for_storage = f"{batch_prefix}{agent_message}{storage_extras}" if batch_prefix else f"{agent_message}{storage_extras}"

        ChatMessage.objects.create(
            session=chat_session,
            sender="agent",
            content=agent_message_for_storage,
            hiddenMessage=hiddenMessage
        )

        sanitized_result["message"] = agent_message

        return sanitized_result

    logging.warning(f"⚠️ AI returned an unknown intent: {decision}")
    return {"message": "Sorry, I couldn’t understand your request. From Orchestrator"}


def _should_shortcut_to_knowledge(user_message: str) -> bool:
    if not user_message:
        return False

    lowered = user_message.lower()

    knowledge_phrases = (
        "teach me",
        "how do i",
        "how to",
        "show me how",
        "guide me",
        "explain",
        "what is",
        "walk me through",
        "steps to",
        "instructions",
        "training on",
    )

    return any(phrase in lowered for phrase in knowledge_phrases)


def _infer_standard_record_write_decision(user_message: str) -> str | None:
    if not user_message:
        return None

    lowered = user_message.lower()

    # Keep quote/bundle/product/custom-field flows out of standard record mutation shortcuts.
    if re.search(r"\b(quote|quote line|quoteline|bundle|product|products|product option|pdf|custom field|custom object|field)\b", lowered):
        return None

    # Custom-object records (e.g. "create a POV for account X") belong to the
    # custom_object_agent — even when a standard word ("account") appears too.
    if _matches_custom_object_singular(lowered):
        return None

    standard_terms = (
        "lead",
        "leads",
        "account",
        "accounts",
        "contact",
        "contacts",
        "opportunity",
        "opportunities",
        "activity",
        "activities",
        "contract",
        "contracts",
        "subscription",
        "subscriptions",
        "tenant",
        "tenants",
        "knowledge",
        "option",
        "options",
    )
    if not _has_any_term(lowered, standard_terms):
        return None

    if re.search(r"\b(create|add|insert|import|load|ingest)\b", lowered):
        return "CreateStandardRecord"
    if re.search(r"\b(update|edit|change|modify|set)\b", lowered):
        return "UpdateStandardRecord"
    if re.search(r"\b(delete|remove)\b", lowered):
        return "DeleteStandardRecord"

    return None


def _infer_product_action(user_message: str) -> str | None:
    """Deterministically route product create/update requests to the product agent.

    Guards against quote/bundle/option phrasings so those flows keep their own
    routing ("add product to quote", "create a product option for bundle", …).
    """
    if not user_message:
        return None
    lowered = user_message.lower()
    # Never hijack structured UI payloads (they carry their own routing and use
    # record_id + JSON; 'product'/'update' inside the JSON must not route here).
    if lowered.startswith(
        (
            "update record:",
            "update quote:",
            "update quote line:",
            "delete quote:",
            "delete quote line:",
            "add product to quote:",
            "update bundle option:",
            "delete bundle option:",
            "delete bundle component from quote:",
        )
    ):
        return None
    if re.search(r"\b(quote|bundle|option|pdf|line)\b", lowered):
        return None
    if not re.search(r"\bproduct(s)?\b", lowered):
        return None
    if re.search(r"\b(create|add|insert|new)\b", lowered):
        return "CreateProductRecord"
    if re.search(r"\b(update|edit|change|modify)\b", lowered):
        return "UpdateProductRecord"
    return None


def _infer_custom_object_schema_action(user_message: str) -> str | None:
    """Route schema-level custom object requests ("update/delete custom object X")."""
    if not user_message:
        return None
    lowered = user_message.lower()
    if not re.search(r"\bcustom\s+object\b", lowered):
        return None
    if re.search(r"\b(delete|remove)\b", lowered):
        return "DeleteCustomObject"
    if re.search(r"\b(update|edit|change|modify)\b", lowered):
        return "UpdateCustomObject"
    if re.search(r"\b(create|add|new)\b", lowered):
        return "CreateCustomObject"
    return None


def _infer_quote_action_decision(user_message: str) -> str | None:
    """Deterministically route common quote line-item commands (add / remove).

    These are unambiguous and cheap to detect, so they skip the LLM classifier
    (and, for well-formed messages, the agent's extraction LLM too).
    """
    if not user_message:
        return None
    lowered = user_message.lower()

    # Structured UI commands are handled by dedicated deterministic shortcuts.
    if user_message.startswith(("Add Product To Quote:", "Delete Quote Line:", "Update Quote Line:")):
        return None

    if "quote" not in lowered:
        return None

    # Guard against obvious non-line-item targets (quote-level edits, PDF, notes…).
    if re.search(r"\b(discount|tax|note|notes|expiration|expiry|status|pdf|document|approval)\b", lowered):
        return None

    if re.search(r"\badd\b", lowered) and re.search(r"\bto\s+(?:the\s+)?quote\b", lowered):
        return "AddProductToQuote"
    if re.search(r"\b(remove|delete)\b", lowered) and re.search(r"\b(?:from|to)\s+(?:the\s+)?quote\b", lowered):
        return "DeleteQuoteLine"

    return None


def _is_view_request(lowered: str) -> bool:
    return re.search(r"\b(show|list|display|view|open|see|get|fetch)\b", lowered) is not None


def _has_any_term(lowered: str, terms) -> bool:
    return any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in terms)


def _has_plural_objects(lowered: str) -> bool:
    plural_terms = (
        "opportunities",
        "accounts",
        "leads",
        "contacts",
        "quotes",
        "products",
        "activities",
        "contracts",
        "subscriptions",
        "tenants",
        "options",
        "bundles",
        "records",
        # common abbreviations
        "opptys",
        "oppties",
        "opps",
        "accts",
        "prods",
    )
    if _has_any_term(lowered, plural_terms):
        return True
    return _matches_custom_object_plural(lowered)


def _has_singular_objects(lowered: str) -> bool:
    singular_terms = (
        "opportunity",
        "account",
        "lead",
        "contact",
        "quote",
        "product",
        "activity",
        "contract",
        "subscription",
        "tenant",
        "option",
        "bundle",
        "record",
        # common abbreviations
        "oppty",
        "opp",
        "acct",
        "prod",
    )
    if _has_any_term(lowered, singular_terms):
        return True
    return _matches_custom_object_singular(lowered)


def _normalize_compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


@lru_cache(maxsize=1)
def _custom_object_token_sets() -> tuple[set[str], set[str]]:
    singular: set[str] = set()
    plural: set[str] = set()
    try:
        for obj in CustomObject.objects.all():
            name = str(obj.name or "")
            label = str(obj.label or "")
            for raw in (name, label):
                if not raw:
                    continue
                base = re.sub(r"__(c|r|x)$", "", raw.strip(), flags=re.IGNORECASE)
                compact = _normalize_compact(base)
                if not compact:
                    continue
                singular_base = compact[:-1] if compact.endswith("s") else compact
                plural_base = compact if compact.endswith("s") else f"{compact}s"
                singular.add(singular_base)
                plural.add(plural_base)
    except Exception:
        return set(), set()
    return singular, plural


def _matches_custom_object_plural(lowered: str) -> bool:
    normalized = _normalize_compact(lowered)
    if not normalized:
        return False
    _, plural = _custom_object_token_sets()
    for token in plural:
        if token and token in normalized:
            return True
    return False


def _matches_custom_object_singular(lowered: str) -> bool:
    normalized = _normalize_compact(lowered)
    if not normalized:
        return False
    singular, _ = _custom_object_token_sets()
    for token in singular:
        if token and token in normalized:
            return True
    return False


def _has_list_keywords(lowered: str) -> bool:
    list_keywords = (
        "list",
        "show all",
        "all",
        "latest",
        "recent",
        "newest",
        "oldest",
        "top",
        "last",
        "first",
        "table",
        "records",
        "metrics",
        "summary",
        "count",
        "group by",
        "grouped by",
    )
    for keyword in list_keywords:
        if " " in keyword:
            if keyword in lowered:
                return True
        else:
            if re.search(rf"\\b{re.escape(keyword)}\\b", lowered):
                return True
    return False


def _should_shortcut_to_metrics(user_message: str) -> bool:
    if not user_message:
        return False

    lowered = user_message.lower()
    if _is_revenue_metrics_query(lowered):
        return True
    # Aggregate intent ("amount by month", "count of leads", "how many …") resolves to
    # ShowMetrics regardless of the leading verb ("need", "show", "list", …).
    if _looks_like_aggregate(lowered):
        return True
    if not _is_view_request(lowered):
        return False

    if _has_plural_objects(lowered):
        return True

    if _has_singular_objects(lowered) and _has_list_keywords(lowered):
        return True

    return False


def _looks_like_aggregate(text: str) -> bool:
    """True for time-bucketed / count / group-by report intents, e.g.
    'need opportunity amount by month', 'how many leads by week', 'accounts group by region'."""
    if not (_has_singular_objects(text) or _has_plural_objects(text)):
        return False
    if re.search(r"\b(how\s+many|count|number\s+of)\b", text):
        return True
    has_grouping = re.search(r"\b(by|per|group(?:ed)?\s+by|monthly|weekly|daily|quarterly)\b", text)
    has_metric = re.search(r"\b(amount|revenue|sum|total|average|avg|value|forecast|breakdown)\b", text)
    return bool(has_grouping and has_metric)


def _should_shortcut_to_single_record(user_message: str) -> bool:
    if not user_message:
        return False

    lowered = user_message.lower()
    if not _is_view_request(lowered):
        return False

    if _has_plural_objects(lowered):
        return False

    if _has_list_keywords(lowered):
        return False

    if _has_singular_objects(lowered):
        return True

    # No object keyword, but the user gave a specific identifier (e.g. "show Northwind Labs").
    # Exclude knowledge/list/generic phrasings so we don't hijack those flows.
    if re.search(
        r"\b(how|what|who|why|when|explain|teach|guide|steps|instructions|me\b|my\b|help|"
        r"all\b|list\b|forecast|metrics|report|pricing|discount|approval|configure|setup|dashboard)\b",
        lowered,
    ):
        return False

    # Require at least one token beyond the view verb (a name/identifier).
    return len(lowered.split()) >= 2


def _is_revenue_metrics_query(lowered: str) -> bool:
    if "revenue" not in lowered and "forecast" not in lowered and "pipeline" not in lowered:
        return False
    return bool(
        re.search(
            r"\b(revenue|forecast|pipeline|expected)\b",
            lowered,
        )
    )


_FAST_QUERY_STANDALONE = {
    "hello", "hi", "hey", "hello there", "hi there", "thanks", "thank you",
    "ok", "okay", "good", "bye", "goodbye", "test", "testing", "yo",
    "who are you", "what can you do", "help",
}

# Presence of these words suggests the answer needs deeper reasoning.
_COMPLEX_QUERY_MARKERS = (
    "why", "how", "explain", "compare", "analyze", "recommend", "strategy",
    "difference", "best", "pros", "cons", "describe", "elaborate", "summarize",
    "optimize", "improve", "approval", "pricing", "discount", "forecast",
    "workflow", "rule", "example", "trade-off", "tradeoff", "versus",
)


def _is_fast_general_query(user_message: str) -> bool:
    """Decide whether a general question can be answered by the cheap/fast model.

    Greetings, acknowledgments and short non-reasoning questions go to the fast
    model; anything that needs real reasoning stays on the stronger model.
    """
    text = extract_current_request(user_message).strip().lower()
    if not text:
        return True
    if text.rstrip(".!? ") in _FAST_QUERY_STANDALONE:
        return True
    words = text.split()
    if len(words) <= 6 and not any(marker in text for marker in _COMPLEX_QUERY_MARKERS):
        return True
    return False


def handle_general_query(user,decision, user_message, session_data):
    """Handles general inquiries about CPQ, pricing rules, approvals, etc."""
    try:
        # ✅ Initialize OpenAI client
        client = get_llm_client()

        # ✅ Pick a model: fast model for simple questions, stronger reasoning model otherwise.
        model = get_model("default") if _is_fast_general_query(user_message) else get_model("reasoning")
        logging.info(f"🤖 General query using model: {model}")

        # ✅ Construct GPT prompt
        system_prompt = """
        You are an AI assistant that specializes in Configure, Price, Quote (CPQ) systems.
        You help users understand CPQ workflows, approval processes, pricing rules, and best practices.
        Your responses should be clear, accurate, and professional.

        Example Queries:
        - "How does CPQ approval work?"
        - "What is the best way to structure discount rules?"
        - "How can I optimize my quote approvals?"
        - "What are common CPQ pricing strategies?"

        Answer concisely and professionally.
        """

        # ✅ Send request to OpenAI GPT (streams tokens when a sink is active)
        response = chat_stream(
            client,
            model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
        )

        # ✅ Extract AI-generated response
        ai_response = response.choices[0].message.content.strip()

        # ✅ Return as a structured JSON response
        return {
            "success": True,
            "message": ai_response
        }


    except Exception as e:
        logging.error(f"❌ Error handling general query: {str(e)}")
        return {
            "success": False,
            "response": {
                "message": "⚠️ Error processing your request. Please try again later."
            }
        }

# Phrases that unambiguously mean "clear the chat session". Kept deterministic so we
# don't pay for (and wait on) an LLM call on every single message.
_SESSION_RESET_STANDALONE = {
    "reset",
    "restart",
    "start over",
    "start fresh",
    "new chat",
    "new session",
    "new conversation",
}

_SESSION_RESET_PHRASES = (
    "reset session",
    "reset the session",
    "reset my session",
    "reset this session",
    "reset chat",
    "reset the chat",
    "reset my chat",
    "reset this chat",
    "reset conversation",
    "reset the conversation",
    "clear session",
    "clear the session",
    "clear my session",
    "clear this session",
    "clear chat",
    "clear the chat",
    "clear conversation",
    "clear the conversation",
    "start a new chat",
    "start a new session",
    "start a new conversation",
    "restart chat",
    "restart session",
    "restart the chat",
    "restart the session",
    "forget everything",
    "forget all",
    "wipe session",
    "wipe the session",
    "wipe chat",
)


def should_reset_session(user_message):
    """Deterministically detect whether the user wants to clear the chat session."""
    if not user_message:
        return False

    # Normalize to lowercase alphanumeric tokens (collapse whitespace, strip punctuation).
    normalized = " ".join(re.sub(r"[^a-z0-9 ]", " ", user_message.lower()).split())

    if normalized in _SESSION_RESET_STANDALONE:
        return True
    return any(phrase in normalized for phrase in _SESSION_RESET_PHRASES)

def get_action_map():
    return {
        # Quote-related actions handled by quote_agent
        "CreateQuote": quote_agent,
        "AddProductToQuote": quote_agent,
        "UpdateQuoteLine": quote_agent,
        "UpdateQuote": quote_agent,
        "DeleteQuoteLine": quote_agent,
        "DeleteQuote": quote_agent,
        "ShowQuoteDetails": quote_agent,
        "ShowQuoteNotes": quote_agent,
        "GenerateQuoteDocument": quote_agent,
        #"ProvideDates": quote_agent,

        # Only for triggered messages
        "UpdateQuoteLineFromUI": quote_agent,
        "UpdateQuoteFromUI": quote_agent,
        "DeleteQuoteLineFromUI": quote_agent,
        "AddProductToQuoteFromUI": quote_agent,

        # Product-related actions handled by product_agent
        "CreateProductRecord": product_agent,
        "UpdateProductRecord": product_agent,
        # Standard objects
        "CreateStandardRecord": standard_record_agent,
        "UpdateStandardRecord": standard_record_agent,
        "DeleteStandardRecord": standard_record_agent,

        # Bundles-related actions handled by bundles_agent
        "AddProductToBundle": bundles_agent,
        "UpdateBundleOption": bundles_agent,
        "DeleteBundleOption": bundles_agent,
        "DeleteBundleComponentFromQuote": bundles_agent,
        "ShowBundleStructure": bundles_agent,

        # Record detail cards
        "ShowSingleRecord": record_agent,
        "ShowRecordSummary": record_agent,
        "ShowRecordActivities": record_agent,
        "UpdateSingleRecordFromUI": record_agent,

        # Approval-related actions handled by dealdesk_agent
        "SubmitForApproval": dealdesk_agent,
        "CheckApprovalStatus": dealdesk_agent,
        "ApproveQuote": dealdesk_agent,
        "RejectQuote": dealdesk_agent,
        "RecallQuote": dealdesk_agent,

        # General query handling
        "GeneralQuery": handle_general_query,

        # Rules
        "CreateValidationRule": admin_agent,
        "CreateInclusionRule": admin_agent,
        "ShowRules": admin_agent,
        "UpdateRule": admin_agent,
        "DeleteRule": admin_agent,

        # Custom Objects
        "CreateCustomObject": custom_object_agent,
        "UpdateCustomObject": custom_object_agent,
        "DeleteCustomObject": custom_object_agent,
        "CreateCustomField": custom_object_agent,
        "UpdateCustomField": custom_object_agent,
        "DeleteCustomField": custom_object_agent,
        "CreateCustomRecord": custom_object_agent,
        "UpdateCustomRecord": custom_object_agent,
        "DeleteCustomRecord": custom_object_agent,
        # EmailAlerts
        "CreateEmailAlert": admin_agent,
        "CreateExclusionRule": admin_agent,
        "UpdateEmailAlert": admin_agent,
        "DeleteEmailAlert": admin_agent,
        # Metrics Agent
        "ShowMetrics": analytics_agent,
        # Knowledge Agent
        "KnowledgeLookup": knowledge_agent,
        # Action Trigger Agent
        "CreateActionTrigger": action_trigger_agent,
        # Intelligence Agent
        "ShowLeadDashboard": lead_intelligence_agent,
    }


def get_trigger_phrases():
    return [
        "pdf",
        "generate doc",
        "generate document",
        "generate pdf",
        "create quote pdf",
    ]


def clean_llm_label(text: str) -> str:
    """
    Limpia la respuesta del LLM y deja únicamente letras A-Z / a-z.
    No números, no guiones, no símbolos, no emojis.
    """
    if not text:
        return ""

    # Quitar todo lo que no sea A-Z
    cleaned = re.sub(r'[^A-Za-z]', '', text)

    return cleaned


def _strip_session_summary_text(message: str) -> str:
    """Remove accidental session_summary artifacts from agent messages."""
    if not message:
        return message
    parts = []
    for line in message.splitlines():
        if "session_summary" in line.lower():
            continue
        parts.append(line)
    return "\n".join(parts)
