import json
import os
import openai
import logging
from functools import lru_cache
from dotenv import load_dotenv
from datetime import date

# ✅ Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"
# OPENAI_MODEL = "gpt-4"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Session Context Helpers
from ..orchestrator.context_handle_helpers import estimate_cost
from cpq.models import CustomObject, CustomField


CUSTOM_RECORD_BASE_FILTERS = [
    "id",
    "custom_identifier",
    "record_id",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
]

CUSTOM_RECORD_BASE_SORT = [
    "custom_identifier",
    "created_at",
    "updated_at",
]


@lru_cache(maxsize=1)
def _build_static_whitelist():
    return {
        "Product": {
            "filters": [
                "name", "sku", "price", "is_subscription", "term",
                "is_bundle", "family", "created_at", "created_by",
                "updated_at", "updated_by"
            ],
            "sort": ["name", "price", "created_at", "updated_at"]
        },
        "Lead": {
            "filters": [
                "first_name", "last_name", "phone", "email", "source",
                "status", "assigned_to", "created_at", "updated_at",
                "created_by", "owner"
            ],
            "sort": ["first_name", "last_name", "status", "created_at", "updated_at"]
        },
        "Account": {
            "filters": [
                "name", "industry", "website", "phone", "created_at",
                "updated_at", "owner", "created_by", "city", "state", "zip_code"
            ],
            "sort": ["name", "industry", "created_at", "updated_at"]
        },
        "Contact": {
            "filters": [
                "first_name", "last_name", "email", "phone", "company",
                "job_title", "created_at", "updated_at", "account",
                "created_by", "is_primary"
            ],
            "sort": ["first_name", "last_name", "created_at", "updated_at"]
        },
        "Opportunity": {
            "filters": [
                "name", "account", "amount", "stage", "owner",
                "expected_close_date", "created_at", "created_by"
            ],
            "sort": ["name", "amount", "stage", "expected_close_date", "created_at"]
        },
        "Quote": {
            "filters": [
                "name", "account", "opportunity", "subtotal", "net_amount",
                "status", "created_at", "updated_at", "discount_type",
                "discount_percentage", "discount_amount", "expiration_date",
                "owner", "created_by"
            ],
            "sort": ["name", "subtotal", "net_amount", "status", "created_at", "updated_at", "expiration_date"]
        },
        "Knowledge": {
            "filters": [
                "title", "content_text", "video_url", "image_url", "has_video",
                "tags", "language", "created_by", "created_at",
                "updated_by", "updated_at", "is_active"
            ],
            "sort": []
        }
    }


def build_whitelist_fields():
    whitelist = dict(_build_static_whitelist())

    try:
        custom_objects = list(CustomObject.objects.prefetch_related("custom_fields"))
    except Exception as exc:  # pragma: no cover - defensive guard
        logging.warning(f"⚠️ Unable to load custom objects for analytics whitelist: {exc}")
        return whitelist

    try:
        standard_custom_fields = list(CustomField.objects.filter(custom_object__isnull=True))
    except Exception as exc:  # pragma: no cover - defensive guard
        logging.warning(f"⚠️ Unable to load standard custom fields for analytics whitelist: {exc}")
        standard_custom_fields = []

    standard_custom_field_map = {}
    for field in standard_custom_fields:
        object_name = field.object_type
        if object_name not in whitelist:
            continue
        standard_custom_field_map.setdefault(object_name, [])
        if field.name not in standard_custom_field_map[object_name]:
            standard_custom_field_map[object_name].append(field.name)
        if field.label and field.label not in standard_custom_field_map[object_name]:
            standard_custom_field_map[object_name].append(field.label)

    for object_name, extra_fields in standard_custom_field_map.items():
        whitelist_filters = whitelist[object_name]["filters"]
        for field_name in extra_fields:
            if field_name not in whitelist_filters:
                whitelist_filters.append(field_name)

    for custom_obj in custom_objects:
        field_names = []
        for field in custom_obj.custom_fields.all():
            field_names.append(field.name)
            if field.label:
                field_names.append(field.label)
        sortable_custom_fields = [
            field.name
            for field in custom_obj.custom_fields.all()
            if (field.data_type or "").lower() in {"text", "textarea", "dropdown", "number", "currency", "percent", "date", "lookup"}
        ]

        whitelist[custom_obj.name] = {
            "filters": CUSTOM_RECORD_BASE_FILTERS + field_names,
            "sort": CUSTOM_RECORD_BASE_SORT + sortable_custom_fields,
        }

    return whitelist

def extract_metrics_with_llm(user_message, current_state, previous_summary=None):
    """
    Uses LLM to extract metrics from user input.
    Returns JSON, tokens used, and estimated cost.
    """

    whitelist_fields = build_whitelist_fields()
    current_date = date.today().isoformat()

    system_prompt = """
    ROLE
    You extract metrics/listing requests into STRICT JSON for the "show_metrics" schema.
    You ONLY extract; you do not execute, summarize, or infer results.

    SCOPE
    - Valid objects are the keys in the provided whitelist below.
    - If the user asks for anything that is not a metrics/listing request, return completed=false and explain that this agent only shows metrics.

    HARD RULES
    1) Use ONLY fields listed in whitelist["<Object>"]["filters"] for conditions.
    2) Use ONLY fields listed in whitelist["<Object>"]["sort"] for sorting.
    3) If the user does NOT specify any conditions, that is VALID. Set conditions=[] and completed=true.
       - Never ask for filtering conditions when the user simply wants "all", "list", "show", "latest", or "recent".
       - Phrases like "show me a list of opportunities" or "list accounts" are valid metrics requests.
       - If the user uses a plural object name (e.g., "accounts", "opportunities"), map it to the singular object name in `object`.
    4) If the user specifies a limit, use it; otherwise default to 100.
    5) If the user specifies sorting, use it. If they say "latest/newest/recent", set sort to {"field":"created_at","order":"desc"}.
       If they say "oldest/earliest", set order="asc". Otherwise set sort=null.
    6) Operators must be one of:
       equals, not_equals, contains, starts_with, ends_with,
       greater_than, greater_or_equal, less_than, less_or_equal,
       within_last, within_range, before_date, after_date,
       in, not_in, is_true, is_false.
    7) Only set aggregate when the user explicitly asks for totals, counts, averages, or charts/over-time trends.
    8) Do not fabricate fields or values. Do not infer missing data.
    9) JSON ONLY. No prose before/after the JSON.

    OUTPUT JSON SCHEMA (exact):
    {
      "show_metrics": [
        {
          "data": {
            "object": <object_name>,
            "method": "read",
            "limit": <limit>,
            "aggregate": {
              "function": "sum|count|avg|min|max",
              "field": <field_name>,
              "group_by": "month|week|day|quarter|field|null",
              "group_field": <field_name_or_null>,
              "date_field": <date_field_name_or_null>,
              "range": "last_3_months|last_month|last_90_days|three_months|six_months|nine_months|twelve_months|this_month|this_year|next_year|this_quarter|last_quarter|custom|null"
            },
            "conditions": [
              { "field": <field_name>, "operator": <operator>, "value": <value> }
            ],
            "sort": { "field": <field_name>, "order": <asc_or_desc> }
          },
          "completed": false
        }
      ],
      "agent_message": "string",
      "summary": "string"
    }

    OPERATOR VALUE FORMATS
    - within_last: {"days": 30} or {"months": 6} etc.
    - within_range: [min, max] or ["YYYY-MM-DD", "YYYY-MM-DD"]
    - before_date / after_date: "YYYY-MM-DD"
    - in / not_in: ["Value1", "Value2"]
    - is_true / is_false: value must be null
    - "less than or equals" -> less_or_equal
    - "greater than or equals" -> greater_or_equal

    COMPLETED CRITERIA
    - completed=true when:
      a) object is present AND conditions are valid (can be empty), OR
      b) object is present AND at least one full condition has field+operator+value.
    - completed=false otherwise.

    AGGREGATION RULES
    - For "group by <field>": group_by="field", group_field=<field>, function="count", field="id".
    - For time series: group_by="month|week|day|quarter" and date_field=<date field>.
      If no date field is specified, use created_at by default.
    - If the user does not mention a date range, leave aggregate.range=null.
    - If the user says "all time", leave aggregate.range=null.
    - If the user asks for "quarter" or "quarterly", use group_by="quarter".
    - If the user asks for "this quarter", set aggregate.range="this_quarter".
    - If the user asks for "last quarter" or "previous quarter", set aggregate.range="last_quarter".
    - If the user asks for "revenue to date" or "year-to-date revenue", interpret as:
      object="Opportunity", aggregate sum(field="amount"), conditions stage equals "closedwon",
      aggregate.range="this_year", aggregate.date_field="created_at".
    - If the user asks for "revenue" and does NOT mention pipeline/forecast, interpret as:
      object="Opportunity", aggregate sum(field="amount"), conditions stage equals "closedwon".
    - If the user asks about forecast/pipeline/expected revenue, interpret as:
      object="Opportunity", aggregate sum(field="amount"),
      conditions stage not_in ["closedwon","closedlost"],
      aggregate.date_field="expected_close_date" and aggregate.range based on the requested timeframe.
    - If the user asks "how many deals in pipeline", interpret as:
      object="Opportunity", aggregate count(field="id"),
      conditions stage not_in ["closedwon","closedlost"],
      aggregate.date_field="expected_close_date" and aggregate.range based on the requested timeframe.

    AGENT_MESSAGE RULES
    - Only talk about extraction status or missing info.
    - Do NOT mention missing filters if none were requested.
    - Short, natural, professional. Use <br> for line breaks.

    SUMMARY RULES
    - Keep brief. It can append to the previous summary if provided.
    - Never describe actual data/records in the summary.
    """
    system_prompt += f"""
    - The current date is {current_date}. Use this as the reference point when interpreting relative dates like "today", "yesterday", "tomorrow", or "this week".
    - For "today", set a within_range condition with ["{current_date}", "{current_date}"] on the appropriate date field.
    - Do not hardcode past dates when the user says "today".
    """

    system_prompt += f"""

    Each object has valid fields for filtering and sorting:

    {json.dumps(whitelist_fields, indent=2)}

    Agent message:
    - Interpret this as an attempt, therefore do not say things like 'has been successfully'.
    - If no metrics are mentioned in the user's message, respond naturally by asking which metrics they want to display.
        Use language that is easy for a regular user to understand, without emphasizing technical or internal terms. Quoted phrases can be used if it helps clarity, but keep the message intuitive.
    - Generate a natural response for the user explaining what happened: completed, errors, missing information, questions for the user, requests for data, etc.
    - Short, professional, natural.
    - Don't be technical.
    - Continue naturally (do NOT start with 'Hello' or 'Hi' or 'Great news')
    - Use <br> for line breaks.
    - Include information if the user tried to show records from an object that does not int valid fields for filtering and sorting.
    - Do not explain if there are no failed or incomplete metrics.
    - For each condition, simply include the field, operator, and value if present.
    - If any field, operator, or value is missing, set "completed": false and list which parts are missing.
    - The agent_message should only reflect the extraction status and any missing information.

    Summary:
    - Create a short summary combining previous summary + this iteration.
    - The "summary" field should only combine previous summary with this extraction iteration. Do not include any information about actual records retrieved.
    """


    user_prompt = f"""
    User message: "{user_message}"

    Current date: {current_date}
    Current State: {current_state}

    Return JSON as described above.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 LLM Metrics - Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0
    )

    raw_response = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT Response: {raw_response}\n\n")

    try:
        result_json = json.loads(raw_response)
    except json.JSONDecodeError as e:
        logging.error(f"❌ JSON decode error: {str(e)}")
        return None, tokens_used, cost_est

    # Normalize structure
    normalized_metrics = []

    for item in result_json.get("show_metrics", []):
        data = item.get("data", {})

        # Si 'data' viene como lista, tomamos el primer dict
        if isinstance(data, list) and data:
            data = data[0]

        # --- FIX: asegurar que sort siempre sea dict ---
        sort_data = data.get("sort") if isinstance(data.get("sort"), dict) else {}
        aggregate_data = data.get("aggregate") if isinstance(data.get("aggregate"), dict) else None

        normalized_metrics.append({
            "data": {
                "object": data.get("object"),
                "method": data.get("method", "read"),
                "limit": data.get("limit", 100),
                "aggregate": aggregate_data,
                "conditions": [
                    {
                        "field": cond.get("field"),
                        "operator": cond.get("operator"),
                        "value": cond.get("value")
                    } for cond in data.get("conditions", [])
                ],
                "sort": {
                    "field": sort_data.get("field"),
                    "order": sort_data.get("order", "desc")
                }
            },
            "completed": item.get("completed", False)
        })

    result_json["show_metrics"] = normalized_metrics

    return result_json, tokens_used, cost_est


def generate_final_metrics_message(completed_metrics, db_results, remaining_metrics, previous_summary):
    """
    Generates in ONE LLM call:
    1) A concise, professional, emoji-rich message for the user.
    2) An updated short summary that extends the previous summary with changes from this iteration.
    Returns (message_text, updated_summary, tokens_used, cost_est).
    """

    final_prompt = f"""
    This is an ongoing conversation about quote line update.
    The assistant should return a JSON with two fields only: "message" and "summary".

    Context:
    - User initially wanted to show records from this object: {completed_metrics}.
    - Here you have all the backend messages about the metrics: {db_results}.
    - Metrics still incomplete: {remaining_metrics}.
    - Previous summary: {previous_summary}.

    Only focus on generating a message using the information obtained from the backend; do not use the summary to create the message.

    Instructions for "message":
    - Be short, friendly, professional, natural, ask follow-ups, concise but specific and friendly.
    - Mention only which objects were successfully showed and which are still pending or incomplete.
    - You don’t need to list each change in detail; instead, describe the metrics naturally in the message.
    - For failed metrics, mention the object and its error, but only if there are any.
    - For incomplete metrics, briefly mention them ONLY if there are any.
      If none exist, omit this section entirely (do not mention that there are no incomplete metrics).
    - Omit entire sections if there are no metrics in that category.
    - End by asking a short, natural follow-up question about next steps.
    - The message is user-facing and can use <br> for line breaks.
    - If an metric fails, explain it as a short, natural comment for the user, not as a system error. Keep it user-friendly and conversational, not technical or formal.
    - Do not include any statement about incomplete metrics if none exist. For example, do not say things like 'There are currently no incomplete metrics to show.' Simply omit that information.
    - When a metric has been successfully made, specify the object and conditions to render.
    - Don’t say phrases like “Great news!”; if records matching the user’s request are found, just respond: here they are (the records the user requested).
    - Use this emoji "✅" for records successfully getted.
    - No utilices

    Instructions for "summary":
    - Write a short but detailed summary that continues the previous summary with the new changes.
    - Summarize successes, failures, and incompletes in 2–4 sentences max.
    - The summary is NOT for the user directly, it's for keeping track of progress across iterations.
    - Do not include any information about requests that were successfully completed.

    ⚠️ IMPORTANT: Return ONLY valid JSON in this format:
    {{
        "message": "...",
        "summary": "..."
    }}
    """

    messages_for_llm = [
        {"role": "system", "content": "You are a concise and friendly AI assistant for CPQ metrics."},
        {"role": "user", "content": final_prompt}
    ]

    tokens_used, cost_est = estimate_cost(messages_for_llm, model=OPENAI_MODEL)
    logging.info(f"\n\n💰 Estimated tokens: {tokens_used}, approx cost: ${cost_est:.6f}\n\n")

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages_for_llm,
        temperature=0.7,
        response_format={"type": "json_object"}  # fuerza JSON válido (si usas GPT-4.1 / GPT-4o / GPT-5)
    )

    raw_output = response.choices[0].message.content.strip()
    logging.info(f"\n\n🔍 Raw GPT JSON Response Analytics: {raw_output}\n\n")

    try:
        parsed = json.loads(raw_output)
        message = parsed.get("message", "").strip()
        updated_summary = parsed.get("summary", "").strip()
    except Exception as e:
        logging.error(f"❌ Error parsing LLM JSON output: {e}")
        message = raw_output
        updated_summary = previous_summary

    return message, updated_summary, tokens_used, cost_est
