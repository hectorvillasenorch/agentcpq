import json
import logging
import os
from typing import Any, Dict, List

import openai
from dotenv import load_dotenv

from cpq.models import CustomObject

from ..agents_utils import clean_llm_json
from ..orchestrator.context_handle_helpers import estimate_cost

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"

client = openai.OpenAI(api_key=OPENAI_API_KEY)

logger = logging.getLogger(__name__)

STANDARD_OBJECTS = [
    "Account",
    "Contact",
    "Lead",
    "Opportunity",
    "Product",
    "Quote",
]

ALLOWED_LOOKUPS = {
    "Account": ["name", "custom_identifier"],
    "Contact": ["email", "custom_identifier"],
    "Lead": ["email"],
    "Opportunity": ["name"],
    "Product": ["sku", "name"],
    "Quote": ["name"],
    "CustomRecord": ["custom_identifier", "record_id"],
}


def _collect_custom_objects() -> List[str]:
    try:
        return [obj.name for obj in CustomObject.objects.all()]
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Unable to load custom object names: %s", exc)
        return []


def extract_single_record_request(user_message: str, current_state: List[Dict[str, Any]], previous_summary: str | None = None):
    """Ask the LLM to parse a single-record lookup request."""

    custom_objects = _collect_custom_objects()

    lookup_instructions = []
    for object_name, allowed in ALLOWED_LOOKUPS.items():
        lookup_instructions.append(f"- {object_name}: {', '.join(allowed)}")
    lookup_instruction_text = "\n".join(lookup_instructions)

    custom_instruction = ""
    if custom_objects:
        custom_instruction = (
            "Custom objects available: " + ", ".join(custom_objects) + ".\n"
            "For a custom object, use the exact API name (e.g., Marketing_Campaign__c) in the `object` field and set `lookup_field` to `custom_identifier` unless the user specifies another field."
        )

    system_prompt = f"""
You are an assistant that turns user requests for a specific CRM record into strictly formatted JSON.
Return ONLY JSON that matches this schema:
{{
  "show_single_record": [
    {{
      "data": {{
        "object": null,
        "identifier": null,
        "lookup_field": null
      }},
      "completed": false
    }}
  ],
  "agent_message": "",
  "summary": ""
}}

Rules:
1. Supported standard objects: {', '.join(STANDARD_OBJECTS)}.
2. Object names are singular (use "Account", not "Accounts").
3. If the user mentions a custom object, keep the exact API name.
4. Required fields for completion: object AND identifier. Set completed=true only when both are present.
5. `lookup_field` must come from this allowlist. If not specified by the user, choose the first sensible default.
{lookup_instruction_text}
6. Do not hallucinate records or confirm that a record exists.
7. If you cannot determine object or identifier, leave them null and set completed=false. Ask a clarifying question in agent_message.
8. Keep agent_message short, professional, HTML-safe (use <br> for line breaks if needed), and continue the existing conversation tone.
9. summary should extend the prior summary with the new interpretation in plain text.
10. Return well-formed JSON without comments or trailing commas.

{custom_instruction}
"""

    user_prompt = f"""
User message: "{user_message}"

Current state:
{json.dumps(current_state, indent=2)}

Previous summary:
{previous_summary if previous_summary else "None"}

Return JSON following the schema.
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    tokens_used, cost_est = estimate_cost(messages, model=OPENAI_MODEL)
    logger.info(
        "💰 Single-record LLM estimate → tokens: %s | approx cost: $%.6f",
        tokens_used,
        cost_est,
    )

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=0.2,
    )

    raw_response = response.choices[0].message.content.strip()
    logger.info("🔍 Single-record LLM raw response:%s%s", os.linesep, raw_response)

    cleaned = clean_llm_json(raw_response)
    if cleaned is None:
        logger.error("❌ Unable to parse LLM JSON for single record request")
        return None, tokens_used, cost_est

    show_requests = cleaned.get("show_single_record")
    if not isinstance(show_requests, list):
        cleaned["show_single_record"] = []
        show_requests = []

    normalized_requests = []
    for item in show_requests:
        data = item.get("data") if isinstance(item, dict) else {}
        normalized_requests.append(
            {
                "data": {
                    "object": _sanitize(data.get("object")),
                    "identifier": _sanitize(data.get("identifier")),
                    "lookup_field": _sanitize(data.get("lookup_field")),
                },
                "completed": bool(data.get("object") and data.get("identifier")),
            }
        )

    cleaned["show_single_record"] = normalized_requests

    return cleaned, tokens_used, cost_est


def _sanitize(value):
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value
