import json
import os
import re


CONFIDENCE_THRESHOLD = 0.85


def _normalize(value):
    text = str(value or "").strip().lower()
    if text.endswith("__c"):
        text = text[:-3]
    if text.endswith("__r"):
        text = text[:-3]
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def _variants(value):
    base = _normalize(value)
    variants = {base}
    if base.endswith("id"):
        variants.add(base[:-2])
    else:
        variants.add(f"{base}id")
    return {v for v in variants if v}


def _exact_api_match(local_field, crm_fields, used):
    local_variants = _variants(local_field)
    for field in crm_fields:
        name = field.get("name")
        if not name or name in used:
            continue
        if _normalize(name) in local_variants:
            return {
                "crm_field": name,
                "confidence": 1.0,
                "source": "EXACT_API_MATCH",
            }
    return None


def _label_match(local_field, crm_fields, used):
    local_variants = _variants(local_field)
    for field in crm_fields:
        name = field.get("name")
        if not name or name in used:
            continue
        label = field.get("label") or name
        if _normalize(label) in local_variants:
            return {
                "crm_field": name,
                "confidence": 0.9,
                "source": "LABEL_MATCH",
            }
    return None


def _llm_semantic_match(local_fields, crm_fields):
    openai_key = os.getenv("OPENAI_API_KEY")
    llm_enabled = os.getenv("FIELD_MAPPING_LLM_ENABLED", "").lower() in {"1", "true", "yes"}
    if not openai_key or not llm_enabled:
        return {}

    try:
        import openai
    except Exception:
        return {}

    from agents.llm import get_llm_client, get_model

    model = os.getenv("FIELD_MAPPING_LLM_MODEL", get_model("structured"))
    client = get_llm_client()

    crm_payload = [
        {"name": f.get("name"), "label": f.get("label")}
        for f in crm_fields
        if f.get("name")
    ]
    prompt = {
        "local_fields": local_fields,
        "crm_fields": crm_payload,
        "instruction": (
            "Match each local field to the best CRM field by meaning. "
            "Return only confident matches. "
            "Output JSON as {\"matches\": [{\"local_field\": str, "
            "\"crm_field\": str, \"confidence\": float}]} with confidence 0-1."
        ),
    }

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": "You are a strict JSON generator."},
                {"role": "user", "content": json.dumps(prompt)},
            ],
        )
    except Exception:
        return {}

    try:
        content = response.choices[0].message.content
        payload = json.loads(content)
    except Exception:
        return {}

    matches = payload.get("matches", [])
    results = {}
    for match in matches:
        local_field = match.get("local_field")
        crm_field = match.get("crm_field")
        confidence = match.get("confidence")
        if not local_field or not crm_field:
            continue
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            continue
        results[local_field] = {
            "crm_field": crm_field,
            "confidence": confidence_value,
            "source": "LLM_SEMANTIC_MATCH",
        }
    return results


def suggest_field_mappings(local_fields, crm_fields):
    suggestions = {}
    used = set()

    for local_field in local_fields:
        suggestion = _exact_api_match(local_field, crm_fields, used)
        if suggestion:
            suggestions[local_field] = suggestion
            used.add(suggestion["crm_field"])
            continue

        suggestion = _label_match(local_field, crm_fields, used)
        if suggestion:
            suggestions[local_field] = suggestion
            used.add(suggestion["crm_field"])

    unmatched = [f for f in local_fields if f not in suggestions]
    llm_suggestions = _llm_semantic_match(unmatched, crm_fields)
    for local_field, suggestion in llm_suggestions.items():
        if local_field in suggestions:
            continue
        suggestions[local_field] = suggestion

    for suggestion in suggestions.values():
        suggestion["auto_apply"] = suggestion.get("confidence", 0) >= CONFIDENCE_THRESHOLD

    return suggestions
