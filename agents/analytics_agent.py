from django.db.models import Sum, F
import json
import os
import openai
import logging
import re
from dotenv import load_dotenv
from cpq.models import Quote, Account, Opportunity, QuoteLine, Product
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
from .utils.analytics_agent.handle_helpers import handle_show_metrics

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

def show_metrics(user, user_message, session_data):
    """
    Handles metrics display requests for system objects.
    Retrieves and aggregates data across different models,
    and generates dynamic summaries or insights for monitoring.
    """
    logging.info("🔧 Showing metrics...\n\n")
    

    current_state, previous_summary = get_session_context("show_metrics", session_data)


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

    response_message, results = handle_show_metrics(user, completed_metrics)


    # --- 5️⃣ Generar mensaje final dinámico usando función separada ---
    dynamic_message, updated_summary, tokens_used_final, cost_final = generate_final_metrics_message(
        completed_metrics=completed_metrics,
        db_results=response_message,
        remaining_metrics=remaining_metrics,
        previous_summary=llm_result["summary"]
    )
    
    if results:
        return {
        "message": dynamic_message,
        "session_summary": updated_summary,
        "retrieved_records": results,
        "hiddenMessage": True
    }

    return {
        "message": dynamic_message,
        "session_summary": updated_summary
    }


def agent_analytics(action, payload, session_data, crm='agentCPQ' ):
    
    # 1. Understand wahat action the user wants
    action = map_action(action)

    # 2. Retrieve context
    context = extract_context(session_data, crm)

    # 3. Apply agent-specific logic
    response = apply_agent_logic(intent, context)

    # 4. Update session if needed
    updated_session = update_session(intent, session_data)

    # 5. Return structured result
    return {
        "intent": intent,
        "response": response,
        "session": updated_session
    }


def map_action(action):
    action_map = {
        "CustomAnalyticsQuery": run_custom_query,
        # "SaveReportDefinition": save_report_definition,
        # "LoadSavedReport": load_saved_report,
        # "ShowRecentAnalytics": show_recent_analytics,
        # "GetCommonMetrics": get_common_metrics,
        # "FilterAnalyticsData": filter_analytics_data
    }
    handler = action_map.get(action)
    if handler is None:
        raise ValueError(f"Unknown action: {action}")
    return handler

def extract_context(session_data: dict, crm: dict) -> dict:
    """Step 2: Gather relevant objects from session and CRM."""
    pass


def apply_agent_logic(intent: str, context: dict) -> dict:
    """Step 3: Perform agent-specific processing."""
    pass


def update_session(intent: str, session_data: dict) -> dict:
    """Step 4: Modify session data based on interaction."""
    pass

def run_custom_query(session_data: dict, crm: dict) -> dict:
    query = build_query_from_payload(payload)


def build_query_from_payload(payload):
    # Dynamically building a SQL-like query.

    object_name = payload.get("object", "quote_lines")
    operation = payload.get("operation", "SUM").upper()
    field = payload.get("field")
    group_by_fields = payload.get("group_by", [])
    filters = payload.get("filters", {})

    allowed_operations = {"SUM", "COUNT", "AVG", "MIN", "MAX", "DIVIDE", "SUBTRACT"}
    if operation not in allowed_operations:
        raise ValueError(f"Unsupported operation: {operation}")

    if not field:
        raise ValueError("Missing required field for aggregation")

    # Build SELECT clause
    if operation in {"SUM", "COUNT", "AVG", "MIN", "MAX"}:
        agg_expr = f"{operation}({field})"
    elif operation == "DIVIDE":
        if not isinstance(field, list) or len(field) != 2:
            raise ValueError("DIVIDE requires two fields in a list")
        agg_expr = f"SUM({field[0]}) / NULLIF(SUM({field[1]}), 0)"
    elif operation == "SUBTRACT":
        if not isinstance(field, list) or len(field) != 2:
            raise ValueError("SUBTRACT requires two fields in a list")
        agg_expr = f"SUM({field[0]}) - SUM({field[1]})"
    else:
        raise ValueError(f"Unsupported operation: {operation}")

    # Combine with group by fields for full SELECT
    select_fields = group_by_fields + [agg_expr]
    select_clause = "SELECT " + ", ".join(select_fields)

    # Build WHERE clause
    conditions = []
    for key, value in filters.items():
        if isinstance(value, str):
            value = value.replace("'", "''")
            conditions.append(f"{key} = '{value}'")
        elif isinstance(value, (int, float)):
            conditions.append(f"{key} = {value}")
        elif isinstance(value, list):
            values = ", ".join(
                "'{}'".format(str(v).replace("'", "''")) if isinstance(v, str) else str(v)
                for v in value
            )
            conditions.append(f"{key} IN ({values})")
    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    # Build GROUP BY clause
    group_by_clause = f" GROUP BY {', '.join(group_by_fields)}" if group_by_fields else ""

    # Final query
    return f"{select_clause} FROM {object_name}{where_clause}{group_by_clause}"