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
            values = ", ".join(f"'{str(v).replace('\'', '\'\'')}'" if isinstance(v, str) else str(v) for v in value)
            conditions.append(f"{key} IN ({values})")
    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    # Build GROUP BY clause
    group_by_clause = f" GROUP BY {', '.join(group_by_fields)}" if group_by_fields else ""

    # Final query
    return f"{select_clause} FROM {object_name}{where_clause}{group_by_clause}"