from django.db.models import Sum, F
import json
import os
import copy
import openai
import logging
import re
from dotenv import load_dotenv
from cpq.models import Quote, Account, Opportunity, QuoteLine, Product, CustomObject
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from django.http import FileResponse
from django.conf import settings
from reportlab.lib.colors import HexColor
from django.http import JsonResponse
from django.db import models
import logging
logger = logging.getLogger(__name__)

# LLM Helpers
from .utils.analytics_agent.llm_helpers import extract_metrics_with_llm, generate_final_metrics_message

# Handle Helpers
from .utils.analytics_agent.handle_helpers import handle_show_metrics, get_object_metadata, resolve_metrics_object_name
from .utils.orchestrator.context_handle_helpers import extract_current_request

# Windows Context Helpers
from .utils.session_context_helpers.session_context_helpers import get_session_context


def analytics_agent(user, action, user_message, session_data):
    action_map = {
        "ShowMetrics": show_metrics,
    }

    # ✅ Dynamically call the function if action exists in map
    if action in action_map:
        return action_map[action](user, user_message, session_data)

    return {"message": "🤖 Sorry, I couldn’t understand your request."}

_DIRECT_METRICS_RE = re.compile(
    r"^\s*show\s+metrics\s*:\s*show(?:\s+all)?\s+(?P<object>.+?)\s+records?"
    r"(?:\s+order\s+by\s+(?P<order_field>[\w\.]+)\s+(?P<order_dir>asc|desc))?"
    r"(?:\s+limit\s+(?P<limit>\d+))?\s*$",
    re.IGNORECASE,
)
_LATEST_LIST_RE = re.compile(
    r"^\s*(?:show|list|display|fetch|give)?\s*(?:me\s*)?(?:the\s*)?"
    r"(?:latest|recent|new|newest)\s+(?:(?P<limit>\d+)\s+)?(?P<object>.+?)"
    r"(?:\s+records?)?\s*$",
    re.IGNORECASE,
)
_REVENUE_TO_DATE_RE = re.compile(
    r"\brevenue\b.*\b(to\s+date|year\s+to\s+date|ytd|this\s+year|current\s+year|so\s+far|today)\b",
    re.IGNORECASE,
)
_PIPELINE_FORECAST_RE = re.compile(
    r"\b(pipeline|forecast|expected\s+revenue|expected\s+sales|expected\s+amount)\b",
    re.IGNORECASE,
)
_COUNT_REQUEST_RE = re.compile(r"\b(how\s+many|count|number\s+of)\b", re.IGNORECASE)
_GROUPING_HINT_RE = re.compile(r"\b(by|group|grouped|per|monthly|weekly|daily)\b", re.IGNORECASE)
_COUNT_METRICS_RE = re.compile(
    r"^\s*(?:show\s+metrics\s*:)?\s*(?:how\s+many|count|number\s+of)\s+(?P<object>.+?)"
    r"(?:\s+records?)?\s*$",
    re.IGNORECASE,
)
_BASIC_LIST_RE = re.compile(
    r"^\s*(?:show|list|display|fetch|get)\s+(?:all\s+)?(?P<object>.+?)"
    r"(?:\s+records?)?\s*$",
    re.IGNORECASE,
)
_STANDARD_WRITE_OBJECT_RE = re.compile(
    r"\b(lead|leads|account|accounts|contact|contacts|opportunity|opportunities|activity|activities|"
    r"contract|contracts|subscription|subscriptions|tenant|tenants|knowledge|option|options)\b",
    re.IGNORECASE,
)


def _detect_misrouted_standard_write_action(user_message: str) -> str | None:
    if not user_message:
        return None

    lowered = user_message.strip().lower()
    if not lowered:
        return None
    if lowered.startswith("show metrics:"):
        return None
    if not _STANDARD_WRITE_OBJECT_RE.search(lowered):
        return None

    if re.match(r"^\s*(?:batch\s*:)?\s*(create|add|insert|import|load|ingest)\b", lowered):
        return "CreateStandardRecord"
    if re.match(r"^\s*(?:batch\s*:)?\s*(update|edit|change|modify|set)\b", lowered):
        return "UpdateStandardRecord"
    if re.match(r"^\s*(?:batch\s*:)?\s*(delete|remove)\b", lowered):
        return "DeleteStandardRecord"
    return None


def _resolve_metrics_object_name(raw_object):
    return resolve_metrics_object_name(raw_object)


def _parse_direct_metrics_request(user_message):
    if not user_message:
        return None
    match = _DIRECT_METRICS_RE.match(user_message)
    if not match:
        return None
    object_raw = match.group("object")
    resolved_object = _resolve_metrics_object_name(object_raw)
    if not resolved_object:
        return None

    order_field = match.group("order_field") or "created_at"
    order_dir = (match.group("order_dir") or "desc").lower()
    try:
        limit = int(match.group("limit")) if match.group("limit") else 10
    except (TypeError, ValueError):
        limit = 10

    return {
        "object": resolved_object,
        "method": "read",
        "conditions": [],
        "sort": {"field": order_field, "order": order_dir},
        "limit": limit,
    }

def _parse_latest_metrics_request(user_message):
    if not user_message:
        return None
    match = _LATEST_LIST_RE.match(user_message)
    if not match:
        return None
    object_raw = match.group("object")
    resolved_object = _resolve_metrics_object_name(object_raw)
    if not resolved_object:
        return None
    try:
        limit = int(match.group("limit")) if match.group("limit") else 10
    except (TypeError, ValueError):
        limit = 10
    return {
        "object": resolved_object,
        "method": "read",
        "conditions": [],
        "sort": {"field": "created_at", "order": "desc"},
        "limit": limit,
    }


def _parse_basic_list_request(user_message):
    if not user_message:
        return None
    match = _BASIC_LIST_RE.match(user_message)
    if not match:
        return None
    object_raw = match.group("object")
    if not object_raw:
        return None
    cleaned = str(object_raw).strip()
    if not cleaned or not cleaned.lower().endswith("s"):
        return None
    resolved_object = _resolve_metrics_object_name(cleaned)
    if not resolved_object:
        return None
    return {
        "object": resolved_object,
        "method": "read",
        "conditions": [],
        "sort": {"field": "created_at", "order": "desc"},
        "limit": 100,
    }


_SUMMARY_OBJECT_MAP = (
    (r"\bopportunit", "Opportunity"),
    (r"\bdeals?\b", "Opportunity"),
    (r"\baccount", "Account"),
    (r"\bleads?\b", "Lead"),
    (r"\bcontact", "Contact"),
    (r"\bquote", "Quote"),
    (r"\bproduct", "Product"),
    (r"\bactivit", "Activity"),
    (r"\bcontract", "Contract"),
    (r"\bsubscription", "Subscription"),
    (r"\btenant", "Tenant"),
    (r"\boption", "Option"),
    (r"\bknowledge", "Knowledge"),
)


def _object_from_summary(summary):
    if not summary:
        return None
    for pattern, obj in _SUMMARY_OBJECT_MAP:
        if re.search(pattern, str(summary), re.IGNORECASE):
            return obj
    return None


def _parse_followup_list_request(user_message, last_object, previous_summary):
    """Resolve a context-dependent follow-up like 'list all 5' / 'show them'.

    Uses the object resolved on the previous metrics turn (stored in session state),
    falling back to scanning the previous summary.
    """
    if not user_message:
        return None
    text = str(user_message).strip().lower()

    # If the user named an object explicitly, let the other parsers/LLM handle it.
    if re.search(
        r"\b(opportunit|account|lead|contact|quote|product|activit|contract|subscription|tenant|option|knowledge|bundle|record)\w*\b",
        text,
    ):
        return None

    # Must be a bare list/show follow-up.
    if not re.search(r"\b(list|show|display|view|get|give|see|pull)\b", text):
        return None
    if len(text.split()) > 8:
        return None

    resolved = last_object or _object_from_summary(previous_summary)
    if not resolved:
        return None

    limit = 10
    m = re.search(r"\b(\d+)\b", text)
    if m:
        try:
            limit = int(m.group(1))
        except ValueError:
            limit = 10

    return {
        "object": resolved,
        "method": "read",
        "conditions": [],
        "sort": {"field": "created_at", "order": "desc"},
        "limit": limit,
    }


def _parse_revenue_request(user_message):
    if not user_message:
        return None
    if not _REVENUE_TO_DATE_RE.search(user_message):
        return None
    return {
        "object": "Opportunity",
        "method": "read",
        "conditions": [
            {"field": "stage", "operator": "equals", "value": "closedwon"},
        ],
        "sort": None,
        "limit": 100,
        "aggregate": {
            "function": "sum",
            "field": "amount",
            "group_by": None,
            "group_field": None,
            "date_field": "created_at",
            "range": "this_year",
        },
    }


def _extract_range_key(user_message: str) -> str | None:
    if not user_message:
        return None
    lowered = user_message.lower()
    if re.search(r"\b(this quarter|current quarter)\b", lowered):
        return "this_quarter"
    if re.search(r"\b(last quarter|previous quarter)\b", lowered):
        return "last_quarter"
    if re.search(r"\b(this year|year to date|ytd|current year|to date)\b", lowered):
        return "this_year"
    if re.search(r"\bthis month\b", lowered):
        return "this_month"
    if re.search(r"\bthis week\b", lowered):
        return "this_week"
    if re.search(r"\blast week\b", lowered):
        return "last_week"
    if re.search(r"\blast month\b", lowered):
        return "last_month"
    if re.search(r"\blast 90 days\b", lowered):
        return "last_90_days"
    if re.search(r"\blast 3 months\b", lowered):
        return "last_3_months"
    if re.search(r"\blast 6 months\b", lowered):
        return "six_months"
    if re.search(r"\blast 9 months\b", lowered):
        return "nine_months"
    if re.search(r"\blast 12 months\b", lowered):
        return "twelve_months"
    return None


def _parse_pipeline_forecast_request(user_message):
    if not user_message:
        return None
    if not _PIPELINE_FORECAST_RE.search(user_message):
        return None
    if _GROUPING_HINT_RE.search(user_message):
        return None

    range_key = _extract_range_key(user_message) or "this_year"
    is_count = bool(_COUNT_REQUEST_RE.search(user_message))
    aggregate_field = "forecast_amount" if not is_count else "id"

    return {
        "object": "Opportunity",
        "method": "read",
        "conditions": [
            {"field": "stage", "operator": "not_in", "value": ["closedwon", "closedlost"]},
        ],
        "sort": None,
        "limit": 100,
        "aggregate": {
            "function": "count" if is_count else "sum",
            "field": aggregate_field,
            "group_by": None,
            "group_field": None,
            "date_field": "expected_close_date",
            "range": range_key,
        },
    }


def _parse_count_metrics_request(user_message):
    if not user_message:
        return None
    if not re.search(r"\b(how\s+many|count|number\s+of)\b", user_message, re.IGNORECASE):
        return None

    text = user_message.strip()
    # Strip the count phrasing + range/stage noise to isolate the object.
    stripped = re.sub(
        r"\b(how\s+many|count|number\s+of)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    range_key = _extract_range_key(text)

    stage = None
    if re.search(r"\bclosed\s+won\b|\bwon\b", text, re.IGNORECASE):
        stage = "closedwon"
    elif re.search(r"\bclosed\s+lost\b|\blost\b", text, re.IGNORECASE):
        stage = "closedlost"
    elif re.search(r"\bopen\b", text, re.IGNORECASE):
        stage = "open"

    for noise in (
        r"\bthis (week|month|quarter|year)\b",
        r"\blast (week|month|quarter|year)\b",
        r"\byear to date\b|\bytd\b",
        r"\b(closed\s+won|closed\s+lost|won|lost|open)\b",
        r"\b(that\s+are|which\s+are|that\s+were|which\s+were|were|are|got|get|have\s+been|has\s+been)\b",
        r"\b(records?|deals?)\b",
    ):
        stripped = re.sub(noise, " ", stripped, flags=re.IGNORECASE)

    object_raw = " ".join(stripped.split()).strip(" ,")
    resolved_object = None
    for pat, obj in _SUMMARY_OBJECT_MAP:
        if re.search(pat, object_raw, re.IGNORECASE):
            resolved_object = obj
            break
    if not resolved_object:
        resolved_object = _resolve_metrics_object_name(object_raw)
    if not resolved_object:
        return None

    conditions = []
    if stage == "open":
        conditions = [{"field": "stage", "operator": "not_in", "value": ["closedwon", "closedlost"]}]
    elif stage:
        conditions = [{"field": "stage", "operator": "equals", "value": stage}]

    return {
        "object": resolved_object,
        "method": "read",
        "conditions": conditions,
        "sort": None,
        "limit": 100,
        "aggregate": {
            "function": "count",
            "field": "id",
            "group_by": None,
            "group_field": None,
            "date_field": "created_at",
            "range": range_key,
        },
    }


_CATEGORICAL_TIME_WORDS = {
    "month", "months", "week", "weeks", "day", "days", "quarter", "quarters",
    "year", "years", "weekly", "monthly", "daily", "quarterly",
}
_GROUPBY_STOPWORDS = {
    "records", "deals", "all", "the", "this", "last", "next", "current", "that",
    "which", "recent", "recently", "top", "latest", "me", "my", "by",
}


def _parse_groupby_field_request(user_message):
    """Resolve categorical groupings like 'how many accounts group by region'.

    Accepts ANY standard field or custom field name/label — the backend resolves
    and validates the actual field (and reports a friendly error if it doesn't exist).
    """
    if not user_message:
        return None
    text = user_message.strip()

    field = None
    # "group(ed) by <field>" — allow multi-word custom field labels.
    m = re.search(r"\bgroup(?:ed)?\s+by\s+([a-z_]+(?:\s+[a-z_]+){0,2})", text, re.IGNORECASE)
    if m:
        field = m.group(1).strip().lower()
    else:
        # "accounts by <field>" / "leads by source" — single token.
        m2 = re.search(r"\bby\s+([a-z_]+)\b", text, re.IGNORECASE)
        if m2:
            cand = m2.group(1).lower()
            if cand not in _CATEGORICAL_TIME_WORDS and cand not in _GROUPBY_STOPWORDS:
                field = cand

    if not field:
        return None
    if field in _CATEGORICAL_TIME_WORDS:
        return None

    # Friendly aliases for fields users name differently than the model (Account has `state`, not `region`).
    _FIELD_ALIASES = {"region": "state", "territory": "state"}
    field = _FIELD_ALIASES.get(field, field)

    is_amount = bool(re.search(r"\b(amount|revenue|sum|total|value|forecast)\b", text, re.IGNORECASE))

    object_name = None
    for pat, obj in _SUMMARY_OBJECT_MAP:
        if re.search(pat, text, re.IGNORECASE):
            object_name = obj
            break
    if not object_name:
        object_name = "Opportunity" if is_amount else None
    if not object_name:
        return None

    stage = None
    if re.search(r"\bclosed\s+won\b|\bwon\b", text, re.IGNORECASE):
        stage = "closedwon"
    elif re.search(r"\bclosed\s+lost\b|\blost\b", text, re.IGNORECASE):
        stage = "closedlost"

    conditions = [{"field": "stage", "operator": "equals", "value": stage}] if stage else []

    return {
        "object": object_name,
        "method": "read",
        "conditions": conditions,
        "sort": None,
        "limit": 100,
        "aggregate": {
            "function": "sum" if is_amount else "count",
            "field": "amount" if is_amount else "id",
            "group_by": "field",
            "group_field": field,
            "date_field": "created_at",
            "range": _extract_range_key(text),
        },
    }


def _parse_grouped_metrics_request(user_message):
    """Resolve time-bucketed aggregations deterministically, e.g.:

    - "opportunity amount by month"        → sum(amount) by month (closed won)
    - "sum of amount by month"             → sum(amount) by month
    - "revenue by month"                   → sum(amount) by month
    - "how many opportunities by month"    → count by month
    - "average deal amount by quarter"     → avg(amount) by quarter
    """
    if not user_message:
        return None
    text = str(user_message).strip().lower()
    if not re.search(r"\b(by|per|grouped\s+by|monthly|weekly|daily|quarterly)\b", text):
        return None

    bucket = None
    if re.search(r"\bmonthly\b|\bmonths?\b", text):
        bucket = "month"
    elif re.search(r"\bweekly\b|\bweeks?\b", text):
        bucket = "week"
    elif re.search(r"\bdaily\b|\bdays?\b", text):
        bucket = "day"
    elif re.search(r"\bquarterly\b|\bquarters?\b", text):
        bucket = "quarter"
    if not bucket:
        return None

    is_count = bool(re.search(r"\b(count|how\s+many|number\s+of)\b", text))
    is_avg = bool(re.search(r"\b(average|avg|mean)\b", text))
    is_amount = bool(re.search(r"\b(amount|revenue|sum|total|sales|value|forecast|expected\s+revenue)\b", text))
    if not (is_count or is_avg or is_amount):
        # "opportunities by month" (no metric word) → count
        is_count = True

    object_name = None
    for pat, obj in _SUMMARY_OBJECT_MAP:
        if re.search(pat, text):
            object_name = obj
            break
    if object_name is None:
        object_name = "Opportunity" if (is_amount or is_avg) else None
    if not object_name:
        return None

    # Stage filter (explicit), then sensible defaults.
    stage = None
    if re.search(r"\bclosed\s+won\b|\bwon\b", text):
        stage = "closedwon"
    elif re.search(r"\bclosed\s+lost\b|\blost\b", text):
        stage = "closedlost"
    elif re.search(r"\bopen\b", text):
        stage = "open"
    if stage is None and object_name == "Opportunity" and is_amount:
        # "revenue / amount" implies closed-won revenue.
        stage = "closedwon"

    conditions = []
    if stage == "open":
        conditions = [{"field": "stage", "operator": "not_in", "value": ["closedwon", "closedlost"]}]
    elif stage:
        conditions = [{"field": "stage", "operator": "equals", "value": stage}]

    if is_avg:
        function = "avg"
    elif is_count:
        function = "count"
    else:
        function = "sum"

    if function == "count":
        field = "id"
    elif object_name == "Opportunity":
        field = "amount"
    else:
        field = "amount"

    date_field = "expected_close_date" if (object_name == "Opportunity" and function == "sum") else "created_at"

    return {
        "object": object_name,
        "method": "read",
        "conditions": conditions,
        "sort": None,
        "limit": 100,
        "aggregate": {
            "function": function,
            "field": field,
            "group_by": bucket,
            "group_field": None,
            "date_field": date_field,
            "range": _extract_range_key(user_message),
        },
    }


def _parse_followup_stage_filter(user_message, last_request):
    """Apply a follow-up filter like 'yes, only closed won' to a pending grouped metric."""
    if not user_message or not last_request:
        return None
    if not isinstance(last_request.get("aggregate"), dict):
        return None
    text = str(user_message).strip().lower().rstrip(".!? ")
    if not re.search(r"\b(closed\s+won|closed\s+lost|won|lost|open|all|pipeline)\b", text):
        return None

    stage = None
    if re.search(r"\bclosed\s+won\b|\bwon\b", text):
        stage = "closedwon"
    elif re.search(r"\bclosed\s+lost\b|\blost\b", text):
        stage = "closedlost"
    elif re.search(r"\bopen\b", text):
        stage = "open"
    # "all" → drop any stage filter.

    new_request = copy.deepcopy(last_request)
    new_conditions = [c for c in new_request.get("conditions", []) if str(c.get("field", "")).lower() != "stage"]
    if stage == "open":
        new_conditions.append({"field": "stage", "operator": "not_in", "value": ["closedwon", "closedlost"]})
    elif stage:
        new_conditions.append({"field": "stage", "operator": "equals", "value": stage})
    new_request["conditions"] = new_conditions
    return new_request


def show_metrics(user, user_message, session_data):
    """
    Handles metrics display requests for system objects.
    Retrieves and aggregates data across different models,
    and generates dynamic summaries or insights for monitoring.
    """
    logging.info("🔧 Showing metrics...\n\n")

    # Deterministic parsers below are regex-anchored; operate on the raw request.
    user_message = extract_current_request(user_message)

    write_action = _detect_misrouted_standard_write_action(user_message)
    if write_action:
        from .standard_record_agent import standard_record_agent
        return standard_record_agent(user, write_action, user_message, session_data)

    current_state, previous_summary = get_session_context("show_metrics", session_data)
    session_data.setdefault("state", {})
    last_object = session_data["state"].get("last_metrics_object")

    direct_request = (
        _parse_grouped_metrics_request(user_message)
        or _parse_groupby_field_request(user_message)
        or _parse_revenue_request(user_message)
        or _parse_pipeline_forecast_request(user_message)
        or _parse_count_metrics_request(user_message)
        or _parse_direct_metrics_request(user_message)
        or _parse_latest_metrics_request(user_message)
        or _parse_basic_list_request(user_message)
        or _parse_followup_list_request(user_message, last_object, previous_summary)
    )
    if direct_request:
        response_message, results, object_labels = handle_show_metrics(user, [direct_request])
        session_data["state"]["last_metrics_object"] = direct_request["object"]
        session_data["state"]["last_metrics_request"] = direct_request
        display_label = object_labels.get(direct_request["object"], direct_request["object"])
        # Aggregates (sum/count/avg …) carry their own human message; list reads use the generic one.
        if isinstance(direct_request.get("aggregate"), dict):
            message = response_message.strip() or f"📊 {display_label} metrics."
        else:
            message = f"📊 Showing latest {display_label} records."
        if results:
            return {
                "message": message,
                "retrieved_records": results,
                "object_labels": object_labels,
                "hiddenMessage": True,
            }
        if response_message:
            return {"message": response_message}
        return {"message": message}

    # Follow-up stage/filter answers ("yes, only closed won") applied to the last grouped metric.
    followup_request = _parse_followup_stage_filter(user_message, session_data["state"].get("last_metrics_request"))
    if followup_request:
        response_message, results, object_labels = handle_show_metrics(user, [followup_request])
        session_data["state"]["last_metrics_request"] = followup_request
        session_data["state"]["last_metrics_object"] = followup_request["object"]
        if results:
            return {
                "message": response_message.strip() or "📊 Updated metrics.",
                "retrieved_records": results,
                "object_labels": object_labels,
                "hiddenMessage": True,
            }
        return {"message": response_message}


    # --- Initial LLM call to extract quote line updates ---
    llm_result, tokens_used, cost_est = extract_metrics_with_llm(
        user_message=user_message,
        current_state=current_state,
        previous_summary=previous_summary
    )

    # --- 3️⃣ Separate completed products vs. incomplete products ---
    completed_metrics = []
    remaining_metrics = []

    for line_item in llm_result["show_metrics"]:
        if line_item.get("completed"):
            completed_metrics.append(line_item["data"])
        else:
            remaining_metrics.append(line_item)

    # Save incomplete on session state
    session_data["state"]["show_metrics"] = remaining_metrics

    # Return if not any completed products
    if not completed_metrics:
        return {
            "message": llm_result["agent_message"],
            "session_summary": llm_result["summary"]
        }

    # Remember the resolved object so follow-up turns ("list all 5") can use it.
    for metric in completed_metrics:
        obj = metric.get("object")
        if obj:
            canonical = _resolve_metrics_object_name(obj)
            if canonical:
                session_data["state"]["last_metrics_object"] = canonical
                session_data["state"]["last_metrics_request"] = metric
            break

    response_message, results, object_labels = handle_show_metrics(user, completed_metrics)

    display_completed_metrics = []
    for metric in completed_metrics:
        metric_copy = {**metric}
        obj_name = metric_copy.get("object")
        if obj_name in object_labels:
            metric_copy = {
                **metric_copy,
                "object": object_labels[obj_name],
                "api_object": obj_name,
            }
        display_completed_metrics.append(metric_copy)


    # --- 5️⃣ Generar mensaje final dinámico usando función separada ---
    dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_metrics_message(
        completed_metrics=display_completed_metrics,
        db_results=response_message,
        remaining_metrics=remaining_metrics,
        previous_summary=llm_result["summary"]
    )

    if results:
        return {
        "message": dynamic_message,
        "session_summary": updated_summary,
        "retrieved_records": results,
        "object_labels": object_labels,
        "hiddenMessage": True
    }

    return {
        "message": dynamic_message,
        "session_summary": updated_summary
    }


# def agent_analytics(action, payload, session_data, crm='agentCPQ' ):
#
#     # 1. Understand wahat action the user wants
#     action = map_action(action)
#
#     # 2. Retrieve context
#     context = extract_context(session_data, crm)
#
#     # 3. Apply agent-specific logic
#     response = apply_agent_logic(intent, context)
#
#     # 4. Update session if needed
#     updated_session = update_session(intent, session_data)
#
#     # 5. Return structured result
#     return {
#         "intent": intent,
#         "response": response,
#         "session": updated_session
#     }
#
#
# def map_action(action):
#     action_map = {
#         "CustomAnalyticsQuery": run_custom_query,
#         # "SaveReportDefinition": save_report_definition,
#         # "LoadSavedReport": load_saved_report,
#         # "ShowRecentAnalytics": show_recent_analytics,
#         # "GetCommonMetrics": get_common_metrics,
#         # "FilterAnalyticsData": filter_analytics_data
#     }
#     handler = action_map.get(action)
#     if handler is None:
#         raise ValueError(f"Unknown action: {action}")
#     return handler
#
# def extract_context(session_data: dict, crm: dict) -> dict:
#     # Step 2: Gather relevant objects from session and CRM.
#     pass
#
#
# def apply_agent_logic(intent: str, context: dict) -> dict:
#     # Step 3: Perform agent-specific processing.
#     pass
#
#
# def update_session(intent: str, session_data: dict) -> dict:
#     # Step 4: Modify session data based on interaction.
#     pass
#
# def run_custom_query(session_data: dict, crm: dict) -> dict:
#     # Build query from payload
#     query = build_query_from_payload(payload)
#
#
# def build_query_from_payload(payload):
#     # Dynamically building a SQL-like query.
#
#     object_name = payload.get("object", "quote_lines")
#     operation = payload.get("operation", "SUM").upper()
#     field = payload.get("field")
#     group_by_fields = payload.get("group_by", [])
#     filters = payload.get("filters", {})
#
#     allowed_operations = {"SUM", "COUNT", "AVG", "MIN", "MAX", "DIVIDE", "SUBTRACT"}
#     if operation not in allowed_operations:
#         raise ValueError(f"Unsupported operation: {operation}")
#
#     if not field:
#         raise ValueError("Missing required field for aggregation")
#
#     # Build SELECT clause
#     if operation in {"SUM", "COUNT", "AVG", "MIN", "MAX"}:
#         agg_expr = f"{operation}({field})"
#     elif operation == "DIVIDE":
#         if not isinstance(field, list) or len(field) != 2:
#             raise ValueError("DIVIDE requires two fields in a list")
#         agg_expr = f"SUM({field[0]}) / NULLIF(SUM({field[1]}), 0)"
#     elif operation == "SUBTRACT":
#         if not isinstance(field, list) or len(field) != 2:
#             raise ValueError("SUBTRACT requires two fields in a list")
#         agg_expr = f"SUM({field[0]}) - SUM({field[1]})"
#     else:
#         raise ValueError(f"Unsupported operation: {operation}")
#
#     # Combine with group by fields for full SELECT
#     select_fields = group_by_fields + [agg_expr]
#     select_clause = "SELECT " + ", ".join(select_fields)
#
#     # Build WHERE clause
#     conditions = []
#     for key, value in filters.items():
#         if isinstance(value, str):
#             value = value.replace("'", "''")
#             conditions.append(f"{key} = '{value}'")
#         elif isinstance(value, (int, float)):
#             conditions.append(f"{key} = {value}")
#         elif isinstance(value, list):
#             values = ", ".join(
#                 "'{}'".format(str(v).replace("'", "''")) if isinstance(v, str) else str(v)
#                 for v in value
#             )
#             conditions.append(f"{key} IN ({values})")
#     where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
#
#     # Build GROUP BY clause
#     group_by_clause = f" GROUP BY {', '.join(group_by_fields)}" if group_by_fields else ""
#
#     # Final query
#     return f"{select_clause} FROM {object_name}{where_clause}{group_by_clause}"
