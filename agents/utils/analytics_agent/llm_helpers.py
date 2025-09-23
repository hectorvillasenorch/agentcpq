import json
import os
import openai
import logging
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

def extract_metrics_with_llm(user_message, current_state, previous_summary=None):
    """
    Uses LLM to extract metrics from user input.
    Returns JSON, tokens used, and estimated cost.
    """

    whitelist_fields = {
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
        }
    }
    
    system_prompt = """
    You are an AI assistant that helps extract user requests into a standardized JSON format called 'show_metrics'.
    The user can ask to 'show', 'list', or 'get' records from the following objects: Product, Lead, Account, Contact, Opportunity, Quote.
    Rules:
    1. Only use the fields in 'filters' for conditions.
    2. Only use the fields in 'sort' for sorting.
    3. If user specifies a limit, use it; otherwise default to 10.
    4. Operators must be standardized: equals, not_equals, contains, starts_with, ends_with, greater_than, greater_or_equal, less_than, less_or_equal, within_last, within_range, before_date, after_date, in, not_in, is_true, is_false.
    5. Modify only the field mentioned by the user.
    6. If the user attempts to do anything other than show metrics, do not modify/add any data and indicate in the agent_message that this agent can only show metrics.
    7. If the user doesn't specify a sorting method, set sort to null.
    8. You cannot infer that a piece of data does not exist, just extract the user's information. If the required fields are extracted, then mark completed as true.
        - Your only task is to extract the metrics requested by the user.
        - Do not make assumptions or statements about whether any records exist.
        - Do not generate summaries about the data.
        - Do not speculate about missing users, names, or counts.
        - Do not read, use, or reference any previous summary.
        - Only generate messages based on the extracted metrics from the backend.
        - The "summary" field should strictly indicate extraction status, not record contents or previous messages.

    9. Output must strictly follow the JSON schema:

    {
    "show_metrics": [
        {
            "data": {
                "object": <object_name>,
                "method": "read",
                "limit": <limit>,
                "conditions": [
                    {
                        "field": <field_name,
                        "operator": <operator>,
                        "value": <value>
                    },
                ],
                "sort": {
                    "field": <field_name>,
                    "order": <asc_or_desc>
                }
            },
            "completed": false
        }
    ],
    "agent_message": "string",
    "summary": "string"
    }

    Special formatting for operators:
    - "within_last": value must be a JSON object with time units, e.g. {"days": 30}, {"hours": 12}, {"months": 6}.
    - "within_range": value must be an array of two values [min, max]. Can be numbers (e.g. [100, 500]) or dates (e.g. ["2025-01-01", "2025-03-01"]).
    - "before_date": value must be a string in ISO date format "YYYY-MM-DD".
    - "after_date": value must be a string in ISO date format "YYYY-MM-DD".
    - "in" and "not_in": value must be an array, e.g. ["Open", "Closed"].
    - "is_true" and "is_false": value should be null (these are boolean checks on the field itself).
    - If user say "less than or equals", set operator as "less_or_equals".
    - If user say "greater than or equals", set operator as "greater_or_equal".

    When generating the "show_metrics" JSON array:

    1. Each item must have a "data" object containing:
    - "object" (the system object to show)
    - "method" (e.g., "read")
    - "conditions" (a list of conditions for filtering)
    - "sort" (optional, can be null)

    2. Set "completed": true if:
    - "object" is not null
    AND
    (EITHER
        a) there are no conditions (the user just wants to see the object, e.g., "show me my product catalog")
        OR
        b) there is at least one condition with "field", "operator", and "value" all not null
    )

    3. If any of these rules are not met, set "completed": false.

    4. Always generate one object per metric request. Do not combine multiple objects or multiple conditions into a single item.
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

        normalized_metrics.append({
            "data": {
                "object": data.get("object"),
                "method": data.get("method", "read"),
                "limit": data.get("limit", 10),
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
    - Do NOT mention incomplete or failed metrics.
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
    logging.info(f"\n\n🔍 Raw GPT JSON Response: {raw_output}\n\n")

    try:
        parsed = json.loads(raw_output)
        message = parsed.get("message", "").strip()
        updated_summary = parsed.get("summary", "").strip()
    except Exception as e:
        logging.error(f"❌ Error parsing LLM JSON output: {e}")
        message = raw_output
        updated_summary = previous_summary

    return message, updated_summary, tokens_used, cost_est