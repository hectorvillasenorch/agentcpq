import json
import os
import re
import logging

import openai
from dotenv import load_dotenv
from django.apps import apps

from cpq.models import CustomObject

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"

client = openai.OpenAI(api_key=OPENAI_API_KEY)


# ---------------------------------------------------------
# ✅ Helpers
# ---------------------------------------------------------
def to_snake_case(name):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()


def get_field_type(field):
    t = field.get_internal_type().lower()

    if "char" in t or "text" in t:
        return "string"
    if "bool" in t:
        return "boolean"
    if "int" in t or "float" in t or "decimal" in t:
        return "number"
    if "json" in t:
        return "json"

    return t


def build_model_schema():
    """
    ✅ Generates a full schema of CPQ models + custom objects + fields + relations.
    Fully safe for reverse relations.

    schema = {
        "<model>": {
            "fields": { "<field>": "type" },
            "relations": { "<rel>": "<related_model>" }
        }
    }
    """

    schema = {}

    # ---------------------------------------------------------
    # Standard CPQ models
    # ---------------------------------------------------------
    for model in apps.get_app_config("cpq").get_models():
        mname = to_snake_case(model.__name__)
        schema[mname] = {"fields": {}, "relations": {}}

        for field in model._meta.get_fields():
            # Skip auto reverse relations
            if field.auto_created and not field.concrete:
                continue

            # Relation
            if field.is_relation:
                rmodel = getattr(field, "related_model", None)
                if not (rmodel and hasattr(rmodel, "__name__")):
                    continue
                schema[mname]["relations"][field.name] = to_snake_case(rmodel.__name__)
                continue

            # Normal field
            try:
                schema[mname]["fields"][field.name] = get_field_type(field)
            except Exception:
                schema[mname]["fields"][field.name] = "unknown"

    # ---------------------------------------------------------
    # Custom Objects (fields end with __c)
    # ---------------------------------------------------------
    for obj in CustomObject.objects.all():
        oname = to_snake_case(obj.name)
        schema[oname] = {"fields": {}, "relations": {}}

        if hasattr(obj, "custom_fields"):
            fields = obj.custom_fields.all()
        elif hasattr(obj, "customfield_set"):
            fields = obj.customfield_set.all()
        else:
            fields = []

        for cf in fields:
            fname = cf.name if cf.name.endswith("__c") else f"{cf.name}__c"
            dt = (cf.data_type or "").lower()

            if dt in ["text", "string"]:
                schema[oname]["fields"][fname] = "string"
            elif dt in ["number", "currency", "integer", "float", "decimal"]:
                schema[oname]["fields"][fname] = "number"
            elif dt == "boolean":
                schema[oname]["fields"][fname] = "boolean"
            else:
                schema[oname]["fields"][fname] = "string"

    # ---------------------------------------------------------
    # Custom Fields on Standard Objects
    # ---------------------------------------------------------
    from cpq.models import CustomField

    for cf in CustomField.objects.filter(custom_object__isnull=True):
        obj_type = cf.object_type.lower()
        if obj_type not in schema:
            continue

        fname = cf.name if cf.name.endswith("__c") else f"{cf.name}__c"
        dt = (cf.data_type or "").lower()

        if dt in ["text", "string"]:
            schema[obj_type]["fields"][fname] = "string"
        elif dt in ["number", "currency", "integer", "float", "decimal"]:
            schema[obj_type]["fields"][fname] = "number"
        elif dt == "boolean":
            schema[obj_type]["fields"][fname] = "boolean"
        else:
            schema[obj_type]["fields"][fname] = "string"

    return schema

# ---------------------------------------------------------
# ✅ Path resolution helpers
# ---------------------------------------------------------
def _fix_double_c(path: str):
    """Collapse repeated __c suffixes: '__c__c' → '__c'."""
    if not isinstance(path, str):
        return path
    return re.sub(r'(__c)+$', '__c', path)


def _variants_for_field_name(raw: str):
    """
    Generate variants for matching a field in schema.
    Includes:
        - original
        - with __c
        - without __c
        - normalized snake_case
    """
    base = raw.rstrip('_')
    variants = [raw]

    # raw → raw__c
    if not raw.endswith("__c"):
        variants.append(f"{raw}__c")

    # raw__c → raw
    if raw.endswith("__c"):
        variants.append(raw[:-3])

    # snake_case version
    s = to_snake_case(base)
    if s not in variants:
        variants.append(s)
    if not s.endswith("__c"):
        variants.append(f"{s}__c")

    # unique preserve order
    return list(dict.fromkeys(variants))


def _find_field_path(schema, start_model, target_field, max_depth=4):
    """
    DFS search: find path from `start_model` to any model containing `target_field`.
    Returns:
        - "field"
        - "rel1.field"
        - "rel1.rel2.field"
    """
    if start_model not in schema:
        return None

    target_variants = _variants_for_field_name(target_field)

    # Direct field in the root model
    for tv in target_variants:
        if tv in schema[start_model]["fields"]:
            return tv

    # DFS
    stack = [(start_model, [], 0)]
    visited = set()

    while stack:
        model, rel_path, depth = stack.pop()
        if depth > max_depth:
            continue

        key = (model, tuple(rel_path))
        if key in visited:
            continue
        visited.add(key)

        # Check fields
        for tv in target_variants:
            if tv in schema[model]["fields"]:
                return ".".join(rel_path + [tv])

        # Traverse relations
        for rel_name, next_model in schema[model]["relations"].items():
            if next_model in schema:
                stack.append((next_model, rel_path + [rel_name], depth + 1))

    return None


def resolve_path_from_root(schema, root_model, raw_path):
    """
    - If raw_path contains dots → sanitize and return.
    - If it's a single token → attempt to discover nested path.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        return raw_path

    raw_path = raw_path.strip()

    if "." in raw_path:
        return ".".join(_fix_double_c(p) for p in raw_path.split("."))

    # Root field
    if root_model in schema and raw_path in schema[root_model]["fields"]:
        return raw_path

    # Search nested
    discovered = _find_field_path(schema, root_model, raw_path, max_depth=5)
    if discovered:
        return _fix_double_c(discovered)

    # Try variant with __c
    if not raw_path.endswith("__c"):
        discovered = _find_field_path(schema, root_model, f"{raw_path}__c", max_depth=5)
        if discovered:
            return _fix_double_c(discovered)

    # Fallback
    return _fix_double_c(raw_path)


# ---------------------------------------------------------
# ✅ Normalize event type
# ---------------------------------------------------------
def normalize_event_type(evt, available_models):
    """Validate & normalize event_type dict."""
    if not isinstance(evt, dict):
        return None

    obj = evt.get("object_type")
    act = (evt.get("action") or "").lower().strip()

    # Accept "created", "updated", "deleted"
    action_map = {
        "created": "create",
        "updated": "update",
        "deleted": "delete",
    }
    act = action_map.get(act, act)

    if obj not in available_models:
        return None
    if act not in ["create", "update", "delete"]:
        return None

    return {"object_type": obj, "action": act}


# ---------------------------------------------------------
# ✅ Validate actions list
# ---------------------------------------------------------
def actions_are_valid(actions):
    """
    VALIDATION RULES (ONLY unified format):

    Supports:
    ✔ Normal CREATE
    ✔ Bulk CREATE (filters at action root)
    ✔ Normal UPDATE
    ✔ Bulk UPDATE (filters at action root)
    ✔ DELETE
    """
    if not isinstance(actions, list) or not actions:
        return False

    for a in actions:
        if not isinstance(a, dict):
            return False

        op = (a.get("operation") or "").upper()
        target = a.get("target", {})
        value = a.get("value")
        filters = a.get("filters")

        # All ops require target.object
        if not target.get("object"):
            return False

        # -------------------------------------------------
        # CREATE
        # -------------------------------------------------
        if op == "CREATE":
            fields = (value or {}).get("fields")

            # Normal CREATE → no filters allowed
            if not filters:
                if not isinstance(fields, dict) or not fields:
                    return False
                if target.get("path") not in (None, ""):
                    return False
                return True

            # Bulk CREATE
            if filters:
                if "source_object" not in filters:
                    return False
                if not isinstance(filters.get("items"), list):
                    return False
                if target.get("path") not in (None, ""):
                    return False
                if not isinstance(fields, dict) or not fields:
                    return False
                return True

            return False

        # -------------------------------------------------
        # UPDATE
        # -------------------------------------------------
        if op == "UPDATE":
            if not isinstance(value, dict):
                return False

            # Bulk UPDATE
            if filters:
                if "source_object" not in filters:
                    return False
                if not isinstance(filters.get("items"), list):
                    return False

                # Bulk update MUST update exactly one field
                p = target.get("path")
                if not isinstance(p, str) or not p.strip():
                    return False

                return True

            # Normal UPDATE
            else:
                p = target.get("path")
                if not isinstance(p, str) or not p.strip():
                    return False
                return True

        # -------------------------------------------------
        # DELETE
        # -------------------------------------------------
        if op == "DELETE":
            tfilters = target.get("filters")
            if not isinstance(tfilters, list):
                return False
            return True

        return False

    return True

# ---------------------------------------------------------
# 🔧 Normalizers (mantienen tu formato original)
# ---------------------------------------------------------

def _normalize_value_block(v):
    """Normalize a value block for CREATE / UPDATE / DELETE."""
    if not isinstance(v, dict):
        return None

    t = v.get("type")

    # Auto-detect expression if no type but formula present
    if not t and "formula" in v:
        t = "expression"

    # ✅ SEQUENCE SUPPORT
    if t == "sequence":
        return {
            "type": "sequence",
            "strategy": v.get("strategy", "auto"),
            "model": v.get("model"),
            "field": v.get("field"),
            "prefix": v.get("prefix"),
            "padding": v.get("padding", 0),
            "scope": v.get("scope"),
        }

    out = {"type": t}

    if t == "field":
        out["object"] = v.get("object")
        out["path"] = v.get("path")

    elif t == "static":
        out["data"] = v.get("data")

    elif t in ["expression", "date"]:
        out["formula"] = v.get("formula")

    elif t == "lookup":
        return {
            "type": "lookup",
            "model": v.get("model"),
            "where": v.get("where"),
        }

    return out


def normalize_conditions(cond):
    """
    Normalize conditions into strict format:

    {
        "logic": "AND" | "OR",
        "items": [
            {
                "alias": null | "xx",
                "left": { "object": ..., "path": ... },
                "operator": "...",
                "right": { "type": ..., ... }
            }
        ]
    }
    """
    if not cond:
        return None

    items = []
    for c in cond.get("items", []):
        items.append({
            "alias": c.get("alias"),
            "left": {
                "object": c.get("left", {}).get("object"),
                "path": c.get("left", {}).get("path"),
            },
            "operator": c.get("operator"),
            "right": _normalize_value_block(c.get("right")),
        })

    return {
        "logic": cond.get("logic", "AND"),
        "items": items,
    }


def normalize_create_value_fields(fields, schema):
    """
    Normalize CREATE.value.fields WITHOUT changing the structure.

    Each field entry is normalized depending on type:
      - field → resolve path against declared `object`
      - static / expression / date → preserved
    """
    if not isinstance(fields, dict):
        return {}

    out = {}

    for fname, spec in fields.items():
        if not isinstance(spec, dict):
            continue

        t = spec.get("type")

        if t == "field":
            obj = spec.get("object")
            path = spec.get("path")

            if isinstance(obj, str) and isinstance(path, str):
                norm_path = resolve_path_from_root(schema, obj, path)
            else:
                norm_path = _fix_double_c(path)

            out[fname] = {
                "type": "field",
                "object": obj,
                "path": norm_path,
            }

        elif t == "static":
            out[fname] = {
                "type": "static",
                "data": spec.get("data"),
            }

        elif t == "expression":
            out[fname] = {
                "type": "expression",
                "formula": spec.get("formula"),
            }
        
        elif t == "sequence":
            out[fname] = {
                "type": "sequence",
                "strategy": spec.get("strategy", "auto"),
                "model": spec.get("model"),
                "field": spec.get("field"),
                "prefix": spec.get("prefix"),
                "padding": spec.get("padding", 0),
                "scope": spec.get("scope"),
            }

        elif t == "date":
            out[fname] = {
                "type": "date",
                "formula": spec.get("formula"),
            }

        elif t == "lookup":
            out[fname] = {
                "type": "lookup",
                "model": spec.get("model"),
                "where": spec.get("where"),
            }

        else:
            # Skip unknown types to avoid {"type": None}
            continue

    return out


def _normalize_filter_list(filters, target_obj, schema):
    """
    Normalize filter list for CREATE / UPDATE / DELETE.

    Ensures:
      - valid operators
      - sanitized field paths
      - sanitized __c suffixes
      - NO expression/date values in filters
    """
    clean = []

    if not filters:
        return clean

    for f in filters:
        if not isinstance(f, dict):
            continue

        raw_field = f.get("field")
        operator = f.get("operator")
        raw_value = f.get("value")

        if not raw_field or not operator or not raw_value:
            continue

        # Normalize field path
        field_path = resolve_path_from_root(schema, target_obj, raw_field)
        field_path = _fix_double_c(field_path)

        # Normalize value
        val = _normalize_value_block(raw_value)
        if not isinstance(val, dict):
            continue

        # ❌ Filters DO NOT allow expression, date, lookup or sequence
        if val.get("type") in ["expression", "date", "sequence", "lookup"]:
            continue

        # Normalize field refs in value
        if val.get("type") == "field":
            vobj = val.get("object")
            vpth = resolve_path_from_root(schema, vobj, val.get("path"))
            val["path"] = _fix_double_c(vpth)

        clean.append({
            "field": field_path,
            "operator": operator,
            "value": val,
        })

    return clean


def normalize_actions(actions, schema):
    """
    NEW unified normalizer for all operations:
      - Bulk CREATE → action["filters"]
      - Bulk UPDATE → action["filters"]
      - Normal CREATE / UPDATE → no filters
      - DELETE → unchanged
    """
    out = []

    for a in actions or []:
        op = (a.get("operation") or "").upper()
        tgt = a.get("target", {}) or {}
        filters = a.get("filters")
        target_obj = tgt.get("object")
        target_path = tgt.get("path")

        # --------------------------------------------------
        # CREATE
        # --------------------------------------------------
        if op == "CREATE":
            fields = a.get("value", {}).get("fields", {})
            fields_norm = normalize_create_value_fields(fields, schema)

            # Bulk CREATE
            if filters:
                cleaned_items = _normalize_filter_list(
                    filters.get("items", []),
                    filters.get("source_object"),
                    schema,
                )

                out.append({
                    "operation": "CREATE",
                    "filters": {
                        "source_object": filters.get("source_object"),
                        "items": cleaned_items,
                    },
                    "target": {"object": target_obj, "path": None},
                    "value": {"fields": fields_norm},
                })
                continue

            # Normal CREATE
            out.append({
                "operation": "CREATE",
                "filters": None,
                "target": {"object": target_obj, "path": None},
                "value": {"fields": fields_norm},
            })
            continue

        # --------------------------------------------------
        # UPDATE
        # --------------------------------------------------
        if op == "UPDATE":
            val = a.get("value") or {}

            # Bulk UPDATE
            if filters:
                cleaned_items = _normalize_filter_list(
                    filters.get("items", []),
                    filters.get("source_object"),
                    schema,
                )

                out.append({
                    "operation": "UPDATE",
                    "filters": {
                        "source_object": filters.get("source_object"),
                        "items": cleaned_items,
                    },
                    "target": {
                        "object": target_obj,
                        "path": _fix_double_c(target_path),
                    },
                    "value": _normalize_value_block(val),
                })
                continue

            # Normal UPDATE
            out.append({
                "operation": "UPDATE",
                "filters": None,
                "target": {
                    "object": target_obj,
                    "path": _fix_double_c(target_path),
                },
                "value": _normalize_value_block(val),
            })
            continue

        # --------------------------------------------------
        # DELETE
        # --------------------------------------------------
        if op == "DELETE":
            tfilters = tgt.get("filters", [])
            cleaned_filters = _normalize_filter_list(tfilters, target_obj, schema)

            out.append({
                "operation": "DELETE",
                "target": {
                    "object": target_obj,
                    "filters": cleaned_filters,
                },
                "value": None,
            })
            continue

    return out

# ---------------------------------------------------------
# ✅ Main Extractor
# ---------------------------------------------------------
def extract_action_triggers_with_llm(user_message, current_state, previous_summary=None):
    schema = build_model_schema()
    available_models = list(schema.keys())

    print(f"\n\nSchema: {schema}\n\n")
    print(f"\n\nAvailable_models: {available_models}\n\n")

    # -----------------------------------------------------
    # ✅ STRICT SYSTEM PROMPT
    # -----------------------------------------------------
    system_prompt = f"""
    You are a CPQ Action Trigger extraction engine.

    ⚠️ STRICT REQUIREMENTS — DO NOT VIOLATE ⚠️
    - You MUST output EXACTLY the JSON structure below (no extra keys, no different formats).
    - Do NOT invent operators.
    - Do NOT invent action types.
    - If the user does NOT specify conditions, set "conditions": null.

    ========================================================
    ✅ FIELD NAME SELECTION (VERY IMPORTANT)
    ========================================================
    - Pick object names ONLY from AVAILABLE_MODELS.
    - Pick field names ONLY from MODEL_SCHEMA below.
    - NEVER guess names outside MODEL_SCHEMA.
    - Custom objects and custom fields ALWAYS end with __c, but users often omit that suffix.
    → If any object or field matches a custom one, ALWAYS return it with the __c suffix.

    ========================================================
    ✅ ALLOWED event_type.action
    ========================================================
    "create", "update", "delete" ONLY.

    ========================================================
    ✅ CONDITIONS FORMAT (STRICT)
    ========================================================
    Conditions MUST be:

    {{
    "logic": "AND" | "OR",
    "items": [
        {{
        "alias": null | "xx",
        "left": {{
            "object": "<event_root_object>",
            "path": "<field_or_relation_path>"
        }},
        "operator": "== | != | > | < | >= | <= | contains | in | not in",
        "right": {{ <VALUE FORMAT> }}
        }}
    ]
    }}

    RULES:
    - left.object MUST be event_type.object_type.
    - Relationship navigation MUST use MODEL_SCHEMA paths.
    - Alias is ONLY allowed for repeated field-to-field comparisons referencing THE SAME external object.

    ========================================================
    ✅ VALUE FORMAT (STRICT)
    ========================================================
    Valid formats:

    STATIC:
    {{
    "type": "static",
    "data": <LITERAL>
    }}

    FIELD:
    {{
    "type": "field",
    "object": "<object>",
    "path": "<path>"
    }}

    EXPRESSION:
    {{
    "type": "expression",
    "formula": "<FORMULA>"
    }}

    DATE:
    {{
    "type": "date",
    "formula": "<DATE_EXPRESSION>"
    }}

    LOOKUP (FOR FK SEARCH BY FILTER):
    {{
        "type": "lookup",
        "model": "<target_model>",
        "where": {{
            "logic": "AND" | "OR",
            "items": [
            {{
                "field": "<field_name>",
                "operator": "== | != | > | < | >= | <= | contains | in | not in",
                "value": {{ <VALUE FORMAT> }}
            }}
            ]
        }}
    }}

    STRICT RULES:
    - LOOKUP is ONLY allowed for FK target fields
    - LOOKUP MUST return a FULL OBJECT (not an ID)
    - LOOKUP where MUST contain at least ONE condition
    - Multiple conditions must use logic AND or OR
    - If lookup value requires CONCAT, +, or functions → MUST use type="expression"
    - NEVER use multiple duplicated keys to represent multiple conditions
    - NEVER mix lookup with static, expression or sequence
    
    SEQUENCE (FOR AUTO NUMBERING):
    {{
        "type": "sequence",
        "strategy": "auto" | "id_based" | "max_plus_one" | "scoped_max_plus_one",
        "model": "<target_model>",
        "field": "<field_name>",
        "prefix": "<string or empty>",
        "padding": <integer>,
        "scope": {{ optional }}
    }}

    RULES:
    - SEQUENCE is ONLY allowed for NON-FK scalar fields
    - NEVER use type="expression" for sequences


    ========================================================
    DATE FUNCTION RULES (STRICT)
    ========================================================

    ⚠️ DATEADD MUST ALWAYS BE USED AS AN EXPRESSION ⚠️
    - ANY use of DATEADD() MUST be placed inside:
        {{ "type": "expression", "formula": "DATEADD(...)" }}

    - NEVER output:
        "type": "date"
        when the formula contains DATEADD() or any function.

    - NEVER convert "1 year", "12 months", "30 days" into arithmetic like:
        TODAY() + 365
        TODAY() + 12
        TODAY() + 30

    Instead ALWAYS convert them into:
        DATEADD(<base>, <amount>, 'years' | 'months' | 'days')

    RULE:
    DATE formulas MUST ONLY be used for simple cases:
    - TODAY()
    - TOMORROW()
    - NOW()
    - TODAY() + N days/months/years 
    WITHOUT functions or nesting.

    If the formula contains functions → use EXPRESSION instead.

    ========================================================
    ✅ CREATE ACTION RULES (NORMAL CREATE — NO FILTERS)
    ========================================================
    "target.path" MUST be null or omitted.

    CREATE MUST be:

    {{
    "operation": "CREATE",
    "target": {{ "object": "<object_to_create>" }},
    "value": {{
        "fields": {{
        "<field_name>": {{ <VALUE BLOCK> }}
        }}
    }}
    }}

    ⇨ NEVER output create: {{ "value": {{ "type": "...", ... }} }}
    ⇨ ALWAYS use value.fields.

    ========================================================
    ✅ BULK CREATE (STRICT)
    ========================================================
    Bulk CREATE MUST be:

    {{
    "operation": "CREATE",
    "filters": {{
        "source_object": "<SOURCE_MODEL>",
        "items": [
        {{
            "field": "<path_in_source>",
            "operator": "...",
            "value": {{ ... }}
        }}
        ]
    }},
    "target": {{ "object": "<TARGET_MODEL>" }},
    "value": {{
        "fields": {{ ... }}
    }}
    }}

    RULES:
    - filters MUST be at top-level of action.
    - NEVER place filters inside target.
    - For each matched source row → one new record is created.

    ========================================================
    ✅ UPDATE RULES (NORMAL & BULK)
    ========================================================
    NORMAL UPDATE:
    {{
        "operation": "UPDATE",
        "target": {{ "object": "<event_root>", "path": "<field>" }},
        "value": {{ <VALUE FORMAT> }}
    }}

    BULK UPDATE:
    {{
        "operation": "UPDATE",
        "filters": {{
            "source_object": "<SOURCE_MODEL>",
            "items": [ ... ]
        }},
        "target": {{ "object": "<TARGET_MODEL>", "path": "<field>" }},
        "value": {{ <VALUE FORMAT> }}
    }}

    RULES:
    - NEVER use target.path = null in UPDATE.
    - Bulk update MUST update exactly ONE field.

    ========================================================
    🔥 BULK CREATE — ULTRA COMPACT STRICT RULES
    ========================================================

    1️⃣ FOREIGN KEYS (FK)
    - Check FK using MODEL_SCHEMA[target]["relations"].
    - If field is FK:
    → MUST use: {{ "type": "field", "object": "<obj>", "path": "<path_or_empty>" }}
    - NEVER use static/expression/date/raw IDs for FK fields.
    - FK values MUST come from:
    • source_object (bulk loop instance)
    • reachable relations via MODEL_SCHEMA
    • alias defined in conditions

    2️⃣ EMPTY PATH ("path": "")
    - Means: “use the FULL INSTANCE of the referenced object.”
    - ONLY allowed when:
    • target field is FK
    • referenced object exists in context (source_object, filter object, alias)
    - NOT allowed for scalar fields, filters, UPDATE targets, or unrelated objects.
    - If unsure, use normal path (e.g. "quote", "product", "id").

    3️⃣ BULK CREATE VALUE SOURCING
    - Bulk CREATE uses: source_object → filters → target → value.fields.
    - All value.fields MUST come from:
    • source_object
    • relations reachable from source_object
    • static/expression/date ONLY if target field is NOT FK.
    - Do NOT reference unrelated objects unless reachable or used in filters.
    - source_object is the DEFAULT data root.

    ========================================================
    END
    ========================================================


    ========================================================
    ✅ DELETE RULES
    ========================================================
    DELETE MUST be:

    {{
    "operation": "DELETE",
    "target": {{
        "object": "<object_to_delete>",
        "filters": [
        {{
            "field": "<field_path>",
            "operator": "...",
            "value": {{ ... }}
        }}
        ]
    }}
    }}

    ========================================================
    ✅ EXPRESSION RULES
    ========================================================
    Expression formulas may include:
    - +, -, *, /, parentheses
    - IF()
    - ROUND, FLOOR, CEIL, ABS, MAX, MIN
    - CONCAT, UPPER, LOWER, TRIM, LEFT, RIGHT, REPLACE
    - SUM, AVG, MIN, MAX, COUNT
    - Any field path from MODEL_SCHEMA

    NEVER wrap formulas in quotes.

    ========================================================
    ✅ DISCOUNT RULES
    ========================================================
    When user references a discount:
    - "%" → discount_percentage + discount_type="percentage"
    - "$" → discount_amount + discount_type="amount"
    - ALWAYS generate TWO updates.

    ========================================================
    ✅ SEQUENCE RULES (AUTO NUMBERING)
    ========================================================

    When the user says ANY of the following:

    - "next sequence"
    - "next number"
    - "next quote number"
    - "auto increment name"
    - "next folio"
    - "next code"

    You MUST generate:

    {{
    "type": "sequence",
    "strategy": "auto",
    "model": "<target_model>",
    "field": "<field_name>",
    "prefix": "<PREFIX>",
    "padding": <INTEGER>
    }}

    EXAMPLES:

    Quote name:
    "name": {{
    "type": "sequence",
    "strategy": "auto",
    "model": "quote",
    "field": "name",
    "prefix": "Q-",
    "padding": 5
    }}

    Purchase request:
    "name": {{
    "type": "sequence",
    "strategy": "auto",
    "model": "purchase_request",
    "field": "name",
    "prefix": "PR-",
    "padding": 5
    }}

    Rules:
    - ALWAYS use prefix "Q-" for quote names

    ========================================================
    ✅ REQUIRED KEYS
    ========================================================
    You MUST output:

    {{
    "create_action_trigger": [
        {{
        "data": {{
            "description": "...",
            "event_type": {{ "object_type": "...", "action": "..." }},
            "conditions": null OR {{...}},
            "actions": [ ... ],
            "active": true,
            "priority": null
        }},
        "completed": true|false
        }}
    ],
    "agent_message": "...",
    "summary": "..."
    }}

    ========================================================
    MODEL_SCHEMA (use these field & model names ONLY)
    ========================================================
    {json.dumps(schema, indent=2)}

    ========================================================
    AVAILABLE_MODELS
    ========================================================
    {json.dumps(available_models, indent=2)}
    """

    # -----------------------------------------------------
    # User Prompt
    # -----------------------------------------------------
    user_prompt = f"""
        User message: "{user_message}"

        Current state:
        {json.dumps(current_state, indent=2)}

        Previous summary:
        {previous_summary or "None"}

        Return ONLY valid JSON. No text outside the JSON.
        """

    # -----------------------------------------------------
    # LLM CALL
    # -----------------------------------------------------
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.2,
    )

    raw = response.choices[0].message.content.strip()
    logging.info(f"\n🔍 Raw GPT Response:\n{raw}\n")

    try:
        result = json.loads(raw)
    except Exception:
        logging.error("❌ JSON decode failed")
        return None

    # -----------------------------------------------------
    # 🔧 POST-FIX SANITIZER
    # -----------------------------------------------------
    def _sanitize_result_structure(r):
        try:
            cats = r.get("create_action_trigger", [])
            for t in cats:
                data = t.get("data", {})

                # Ensure description/agent_message exist
                if not data.get("description"):
                    data["description"] = "Action trigger extracted from user instruction."

                if not r.get("agent_message"):
                    r["agent_message"] = "Trigger interpreted and formatted. Review before saving."

                if not r.get("summary"):
                    r["summary"] = "Parsed trigger with validated structure."

                # Normalize event type
                evt = normalize_event_type(data.get("event_type"), available_models)
                data["event_type"] = evt
                event_root = evt["object_type"] if evt else None

                # -----------------------------------------
                # CONDITIONS SANITIZING
                # -----------------------------------------
                cond = data.get("conditions")
                if cond and isinstance(cond, dict):
                    items = cond.get("items") or []

                    for item in items:
                        # enforce left.object
                        if event_root and item.get("left"):
                            item["left"]["object"] = event_root

                        # sanitize left.path
                        lp = item["left"].get("path")
                        item["left"]["path"] = resolve_path_from_root(
                            schema, event_root, lp
                        )

                        # sanitize right.path if field
                        rgt = item.get("right") or {}
                        if isinstance(rgt, dict) and rgt.get("path"):
                            rgt["path"] = _fix_double_c(rgt["path"])

                        # Auto alias for pricingtable__c (optional rule)
                        if (
                            rgt.get("type") == "field"
                            and rgt.get("object") == "pricingtable__c"
                            and not item.get("alias")
                        ):
                            item["alias"] = "pt"

                    # remove empty conditions
                    if not items:
                        data["conditions"] = None
                    else:
                        cond["items"] = items
                        data["conditions"] = cond

                else:
                    data["conditions"] = None

                # -----------------------------------------
                # ACTIONS SANITIZING
                # -----------------------------------------
                acts = data.get("actions") or []
                for a in acts:
                    op = (a.get("operation") or "").upper()
                    tgt = a.get("target") or {}
                    val = a.get("value") or {}

                    # CREATE
                    if op == "CREATE":
                        a["target"]["path"] = None

                        fields = val.get("fields", {})
                        if isinstance(fields, dict):
                            new_fields = {}
                            for fname, spec in fields.items():
                                if not isinstance(spec, dict):
                                    continue

                                t = spec.get("type")
                                if t == "field":
                                    obj = spec.get("object")
                                    pth = spec.get("path")
                                    if isinstance(obj, str) and isinstance(pth, str):
                                        pth = _fix_double_c(pth)
                                        new_fields[fname] = {
                                            "type": "field",
                                            "object": obj,
                                            "path": pth,
                                        }
                                elif t == "static":
                                    new_fields[fname] = {
                                        "type": "static",
                                        "data": spec.get("data"),
                                    }
                                elif t == "expression":
                                    new_fields[fname] = {
                                        "type": "expression",
                                        "formula": spec.get("formula"),
                                    }
                                elif t == "date":
                                    new_fields[fname] = {
                                        "type": "date",
                                        "formula": spec.get("formula"),
                                    }
                                elif t == "sequence":
                                    new_fields[fname] = {
                                        "type": "sequence",
                                        "strategy": spec.get("strategy", "auto"),
                                        "model": spec.get("model"),
                                        "field": spec.get("field"),
                                        "prefix": spec.get("prefix"),
                                        "padding": spec.get("padding", 0),
                                        "scope": spec.get("scope"),
                                    }
                                elif t == "lookup":
                                    new_fields[fname] = {
                                        "type": "lookup",
                                        "model": spec.get("model"),
                                        "where": spec.get("where"),
                                    }

                            a["value"]["fields"] = new_fields

                        # sanitize bulk create filters
                        if a.get("filters"):
                            flt = a["filters"]
                            items = flt.get("items", [])
                            for f in items:
                                if f.get("field"):
                                    f["field"] = _fix_double_c(f["field"])
                                v = f.get("value")
                                if isinstance(v, dict) and v.get("path"):
                                    v["path"] = _fix_double_c(v["path"])

                    # UPDATE
                    elif op == "UPDATE":
                        if tgt.get("path"):
                            tgt["path"] = _fix_double_c(tgt["path"])

                        # sanitize field ref in value
                        if val.get("type") == "field" and val.get("path"):
                            val["path"] = _fix_double_c(val["path"])

                        # sanitize bulk update filters
                        if a.get("filters"):
                            flt = a["filters"]
                            items = flt.get("items", [])
                            for f in items:
                                if f.get("field"):
                                    f["field"] = _fix_double_c(f["field"])
                                v = f.get("value")
                                if isinstance(v, dict) and v.get("path"):
                                    v["path"] = _fix_double_c(v["path"])

                    # DELETE
                    elif op == "DELETE":
                        filters = tgt.get("filters", [])
                        cleaned = []
                        for f in filters:
                            if not isinstance(f, dict):
                                continue
                            v = f.get("value")
                            if isinstance(v, dict) and v.get("path"):
                                v["path"] = _fix_double_c(v["path"])
                            cleaned.append({
                                "field": f.get("field"),
                                "operator": f.get("operator"),
                                "value": v,
                            })
                        a["target"]["filters"] = cleaned

        except Exception:
            logging.exception("Post-fix sanitizer failed")

    _sanitize_result_structure(result)

    # -----------------------------------------------------
    # FINAL NORMALIZATION
    # -----------------------------------------------------
    norm = []

    for trig in result.get("create_action_trigger", []):
        data = trig.get("data", {}) or {}

        evt = normalize_event_type(data.get("event_type"), available_models)
        conditions = normalize_conditions(data.get("conditions"))
        actions = normalize_actions(data.get("actions"), schema)

        def is_valid_event(e):
            return bool(e and e.get("object_type") in available_models and e.get("action") in ["create", "update", "delete"])

        def is_valid_actions_list(a):
            return actions_are_valid(a)

        completed_flag = is_valid_event(evt) and is_valid_actions_list(actions)

        # Ensure description/agent_message
        if not data.get("description"):
            data["description"] = "Action trigger extracted from user instruction."

        if not result.get("agent_message"):
            result["agent_message"] = "Trigger interpreted and formatted. Review before saving."

        if not result.get("summary"):
            result["summary"] = "Parsed trigger with validated structure."

        # -------------------------------------
        # PRIORITY NORMALIZATION
        # -------------------------------------
        priority_value = data.get("priority")

        # If LLM output null or missing → default to 100
        if priority_value in (None, "", "null"):
            priority_value = 100

        # If it comes as string
        try:
            priority_value = int(priority_value)
        except Exception:
            priority_value = 100

        norm.append({
            "data": {
                "description": data.get("description"),
                "event_type": evt,
                "conditions": conditions,
                "actions": actions,
                "active": data.get("active", True),
                "priority": priority_value,
            },
            "completed": completed_flag,
        })

    result["create_action_trigger"] = norm
    return result
