import json
import os
import re
import logging

import openai
from dotenv import load_dotenv
from django.apps import apps
from django.contrib.auth.models import User
from django.contrib.auth.models import Group

from cpq.models import CustomObject

from agents.llm import chat_json, get_llm_client, get_model

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = get_model("structured")

client = get_llm_client()


# ---------------------------------------------------------
# ✅ Helpers
# ---------------------------------------------------------
def to_snake_case(name):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()

def is_custom_object(obj_name: str) -> bool:
    return isinstance(obj_name, str) and obj_name.endswith("__c")


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

    # ✅ Acepta object_type o object_name (compatibilidad total)
    obj = evt.get("object_name")
    act = (evt.get("action") or "").lower().strip()

    action_map = {
        "created": "create",
        "updated": "update",
        "deleted": "delete",
        "create": "create",
        "update": "update",
        "delete": "delete",
    }

    act = action_map.get(act, act)

    if obj not in available_models:
        return None
    if act not in ["create", "update", "delete"]:
        return None

    return {"object_name": obj, "action": act}


# ---------------------------------------------------------
# ✅ Validate actions list
# ---------------------------------------------------------
def actions_are_valid(actions):
    if not isinstance(actions, list) or not actions:
        return False

    for a in actions:
        if not isinstance(a, dict):
            return False

        op = (a.get("operation") or "").upper()
        target = a.get("target")
        value = a.get("value")
        filters = a.get("filters")

        # ✅ target MUST be a string always
        if not isinstance(target, str) or not target.strip():
            return False

        # -------------------------------------------------
        # CREATE
        # -------------------------------------------------
        if op == "CREATE":
            if not filters:
                if not isinstance(value, dict):
                    return False
                fields = value.get("fields")
                if not isinstance(fields, dict) or not fields:
                    return False
                return True

            # Bulk CREATE
            if filters:
                if "source_object" not in filters:
                    return False
                if not isinstance(filters.get("items"), list):
                    return False
                if not isinstance(value, dict):
                    return False
                fields = value.get("fields")
                if not isinstance(fields, dict) or not fields:
                    return False
                return True

        # -------------------------------------------------
        # CLONE
        # -------------------------------------------------
        if op == "CLONE":
            if not isinstance(value, dict):
                return False
            fields = value.get("fields")
            if not isinstance(fields, dict):
                return False

            # Bulk CLONE
            if filters:
                if "source_object" not in filters:
                    return False
                if not isinstance(filters.get("items"), list):
                    return False

            return True

        # -------------------------------------------------
        # UPDATE
        # -------------------------------------------------
        if op == "UPDATE":
            if not isinstance(value, dict):
                return False
            fields = value.get("fields")
            if not isinstance(fields, dict) or not fields:
                return False

            # Bulk UPDATE
            if filters:
                if "source_object" not in filters:
                    return False
                if not isinstance(filters.get("items"), list):
                    return False

            return True

        # -------------------------------------------------
        # DELETE
        # -------------------------------------------------
        if op == "DELETE":
            if value is not None:
                return False

            # Bulk DELETE
            if filters:
                if "source_object" not in filters:
                    return False
                if not isinstance(filters.get("items"), list):
                    return False

            return True
        
        # -------------------------------------------------
        # EMAIL
        # -------------------------------------------------
        if op == "EMAIL":
            email = a.get("email")

            if not isinstance(email, dict):
                return False

            # Required keys
            if not email.get("template"):
                return False
            if not email.get("subject"):
                return False
            if not email.get("recipients"):
                return False

            # EMAIL must NOT have value or filters
            if value is not None:
                return False
            if filters is not None:
                return False

            return True

        return False

    return True


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
        val = raw_value

        clean.append({
            "field": field_path,
            "operator": operator,
            "value": val,
        })

    return clean


def normalize_actions(actions, schema):
    out = []

    for a in actions or []:
        op = (a.get("operation") or "").upper()

        # 🔥 EMAIL ACTION — DO NOT NORMALIZE LIKE DB ACTIONS
        if op == "EMAIL":
            out.append({
                "operation": "EMAIL",
                "target": a.get("target"),
                "email": a.get("email"),
                "value": None,
                "filters": None,
            })
            continue

        target_raw = a.get("target")
        filters = a.get("filters")
        value = a.get("value")

        # ✅ Normalize target with schema
        if isinstance(target_raw, str) and "." in target_raw:
            root = target_raw.split(".")[0]
            tail = ".".join(target_raw.split(".")[1:])
            tail = resolve_path_from_root(schema, root, tail)
            target = f"{root}.{tail}"
        else:
            target = target_raw

        # -----------------------------
        # DELETE
        # -----------------------------
        if op == "DELETE":
            item = {
                "operation": "DELETE",
                "target": target,
                "value": None,
                "filters": None,
            }

            if filters:
                cleaned_items = _normalize_filter_list(
                    filters.get("items", []),
                    filters.get("source_object"),
                    schema,
                )

                item["filters"] = {
                    "source_object": filters.get("source_object"),
                    "items": cleaned_items,
                }

            out.append(item)
            continue
        else:
            item = {
                "operation": op,
                "target": target,
                "value": value,
                "filters": None,
            }

            if filters:
                cleaned_items = _normalize_filter_list(
                    filters.get("items", []),
                    filters.get("source_object"),
                    schema,
                )

                item["filters"] = {
                    "source_object": filters.get("source_object"),
                    "items": cleaned_items,
                }

            out.append(item)
            continue

    return out

# ---------------------------------------------------------
# ✅ Main Extractor
# ---------------------------------------------------------
def extract_action_triggers_with_llm(user, user_message, current_state, previous_summary=None, action=None):
    schema = build_model_schema()
    available_models = list(schema.keys())

    # print(f"\n\nSchema: {schema}\n\n")
    # print(f"\n\nAvailable_models: {available_models}\n\n")

    # -----------------------------------------------------
    # ✅ STRICT SYSTEM PROMPT
    # -----------------------------------------------------
    system_prompt = f"""
    You are a CPQ Action Trigger extraction engine.
    Your job is to interpret the user's message and transform it into a JSON for an action trigger.

    ========================================================
    ✅ REQUIRED KEYS
    ========================================================
    You MUST output:

    {{
        "create_action_trigger": [
            {{
            "data": {{
                "description": "...",
                "event_type": {{
                    "object_name": "...",
                    "action": "..." 
                }},
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
    ✅ DESCRIPTION
    ========================================================
    - Create a short description that explains what the action trigger will do,
        based on the event type (when <event_type.object_name> is <event_type.action>), 
        then explain the conditions, and finally what will be executed (actions).

    ========================================================
    ✅ EVENT TYPE
    ========================================================
    - event_type.object_name: Name of the object that will trigger the Action Trigger
    - event_type.action: Database action performed on the object_name.

    Rules:
    - Only the following are available: "CREATE", "UPDATE", "DELETE"
    - Do not write: BULK CREATE, BULK CLONE, BULK UPDATE, or BULK DELETE.

    ========================================================
    ✅ CONDITIONS FORMAT (STRICT)
    ========================================================
    The structure of an Action Trigger is:

    Event: Represents the event that will trigger the Action Trigger. 
        When a database object is created, updated, or deleted, that event becomes the EVENT ROOT OBJECT, 
        because it is the main object that triggers the Action Trigger. It can also be called the main instance.

    Conditions (HERE): Conditions are used to evaluate fields of the EVENT ROOT OBJECT and they ONLY evaluate 
        conditions from the EVENT ROOT OBJECT. They are not related to BULK OPERATIONS nor to LOOKUP. 
        They serve only as a bridge to decide whether the conditions are met and, if so, proceed to the 
        next step to execute actions in the database (CREATE, UPDATE, or DELETE). Conditions are a series of 
        logical operations where, if the result is TRUE, it means something must be executed in the database; 
        if the result is FALSE, it means we do not want to execute anything when this EVENT ROOT OBJECT triggers 
        a change in the database.

    Actions: The actions that will be executed in the database: CREATE, CLONE, UPDATE, BULK OPERATIONS, or DELETE.
    Conditions MUST be:

    {{
        "logic": "AND" | "OR",
        "items": [
            {{
                "source": {{
                    "object": "<ALWAYS_event_root_object>",
                    "field_name": "<field_or_relation_path>"
                }},
                "operator": "== | != | > | < | >= | <= | contains | in | not in",
                "target": {{ <VALUE FORMAT> }},
                "alias": null | "xx"
            }}
        ]
    }}

    🚨 HARD CONDITIONS RULE — EVENT ROOT ONLY (MAY COEXIST WITH FILTERS)

    IMPORTANT:
    - "conditions" and "filters" MAY appear together in the same action trigger.
    - They DO NOT serve the same purpose:

    ✅ "conditions" = logical gate to decide IF the trigger runs at all  
        (only for the EVENT ROOT OBJECT)

    ✅ "filters"   = record selection for BULK operations  
        (only for the SOURCE_OBJECT)

    STRICT RULES FOR "conditions":

    1) "conditions" MAY ONLY reference the EVENT ROOT OBJECT.

    - source.object MUST ALWAYS be exactly event_type.object_name
    - You MUST NEVER use any other object name here.
    - You MUST NOT use source_object, bulk iteration models, or any external model.

    2) "conditions" MUST NEVER be used to simulate BULK filters.

    ❌ INVALID USAGE EXAMPLES (DO NOT DO THIS):

    - Using "quote_line" as source.object:
        {{
        "source": {{
            "object": "quote_line",
            "field_name": "is_subscription"
        }},
        ...
        }}

    - Using any object that is NOT the event_type.object_name:
        {{
        "source": {{
            "object": "product",
            "field_name": "family"
        }},
        ...
        }}

    In these cases, if the user is describing "all quote lines…" or similar,
    the logic MUST go into "filters" (bulk selection), NOT into "conditions".

    3) VALID COEXISTENCE WITH FILTERS:

    It IS valid to have:

    - "conditions" checking only the EVENT ROOT, e.g.:
        IF opportunity.stage == "closedwon"

    - AND "filters" selecting BULK records, e.g.:
        all quote_line WHERE quote == opportunity.primary_quote

    Example in natural language:
    "create an action trigger for when opportunity is updated,
        if opportunity stage == 'closedwon',
        then bulk create all quote lines where quote = opportunity.primary_quote"

    → "conditions" checks ONLY opportunity (the event root)  
    → "filters" searches quote_line records  
    → This is VALID and EXPECTED.

    4) If the user does NOT specify any condition based on the event root object,
    you MUST set:
    "conditions": null

    ========================================================
    ✅ VALUE FORMAT (STRICT) (VALUE_FORMAT)
    ========================================================
    Valid formats:

    STATIC:
    {{
        "type": "static",
        "value": <LITERAL>
    }}

    NULL STATIC:
    {{
        "type": "static",
        "value": null
    }}

    FIELD:
    {{
        "type": "field",
        "object": "<object>",
        "field_name": "<path>"
    }}

    EXPRESSION:
    {{
        "type": "expression",
        "formula": "<formula>"
    }}

    DATE:
    {{
        "type": "date",
        "formula": "<date_expression>"
    }}


    ========================================================
    ✅ ACTIONS
    ========================================================

    "actions": [
        {{
            "operation": "CREATE | CLONE | UPDATE | DELETE | EMAIL",
            "filters": {{ <FILTERS_FORMAT> }},
            "target": "<object_and_path>",
            "value": {{
                "fields": {{
                    "<FIELD_NAME>": {{
                        "type": "<VALUE_FORMAT>"
                    }}
                }}
            }}
        }}
    ]

    - operation: The operation to be executed in the database. Valid operations are: CREATE, CLONE, UPDATE, DELETE.
        - CREATE: Create one or multiple records in a database model.
        - CLONE: Clone one or multiple records into a database model.
        - UPDATE: Update one or multiple records of a database model.
        - DELETE: Delete one or multiple records of a database model.
    - filters: Search filters in case the user requires them (check the filter format later).
    - target: Object and path that the engine must follow to determine which object the operation should be applied to.

        Target rules:
        - The target MUST ALWAYS start with the instance object that triggered the Action Trigger, meaning the event_type.object_name.
        - The target MAY be a path only if the user explicitly specifies it in the message, and it MUST ALWAYS start with the instance object that triggers the Action Trigger (event_type.object_name).
        - When the target is a path, you must always follow this format: <event_root>.<field>.<field>.<field>
        - When the target is a path, it can only be built using foreign key relationships of an object based on the <MODEL_SCHEMA>.

        !!IMPORTANT!!:
        - The target is the object that will be affected by the operation. 
            If it is a path, it cannot end with a regular field; it must always end with a Foreign Key field, 
            because this value does not represent the field that will be affected, but rather the path that 
            will be followed to obtain the object that will be affected.

    Target output example:
        User message: [...], then clone opportunity primary quote [...]
        Output: target: "opportunity.primary_quote" (according to the <MODEL_SCHEMA>)

    Example 2:
        User message: [...], then create an Account where [...]
        Output: target: "account"

    - Value: Inside value there will be the key FIELDS, which will contain the following depending on the operation type used:

        - When operation = CREATE: value.fields will contain the fields of the object to be created (the keys MUST ALWAYS reference the <MODEL_SCHEMA>).
        - When operation = CLONE: value.fields will contain the fields that the user wants to be different when cloning one or multiple records.
        - When operation = UPDATE: value.fields will contain the fields that should be updated in the record (the keys MUST ALWAYS reference the <MODEL_SCHEMA>).
        - When operation = DELETE: value = null.

    The value inside each field must follow the VALUE_FORMAT.

    ========================================================
    🚨 ABSOLUTE OPERATION TYPE ENFORCEMENT (CRITICAL)
    ========================================================

    The ONLY valid values for "operation" are:

    - "CREATE"
    - "UPDATE"
    - "CLONE"
    - "DELETE"

    🚫 It is STRICTLY FORBIDDEN to generate any other value for "operation", including but NOT limited to:

    - "LOOKUP"
    - "BULK"
    - "BULK_CREATE"
    - "BULK_CLONE"
    - "BULK_UPDATE"
    - "BULK_DELETE"
    - "FETCH"
    - "GET"
    - Any invented action

    ⚠️ LOOKUP is NOT an operation.
    ⚠️ LOOKUP is NOT an action.
    ⚠️ LOOKUP must NEVER appear as a standalone object inside the "actions" array.

    ✅ LOOKUP is ONLY allowed as:

    "value": {{
        "fields": {{
            "LOOKUP_<MODEL>": {{ ... }}
        }}
    }}

    ========================================================
    ✅ FILTERS FORMAT | BULK OPERATIONS (FILTERS_FORMAT)
    ========================================================

    All operations can be executed for a single record or for bulk records: BULK CREATE, BULK UPDATE, BULK CLONE, and BULK DELETE.
    - To perform BULK operations, the following flow is used:
    source_object → filters → target → value.fields  
    (Only when the operation is DELETE, value = null)
    - filters define WHICH records are selected
    - value.fields define WHAT is created/updated/cloned
    - conditions MUST NEVER be used as record selectors for BULK operations

    Filters are used to perform bulk operations and help the engine find multiple records of an object in the database. 
    Filters are typically used when you want to iterate over a set of records that are NOT related to the instance object that triggered the Action Trigger.

    Output format for filters:
    "filters": {{
        "source_object": "<source_model>",
        "items": [
            {{
                "field": "<path_in_source>",
                "operator": "== | != | > | < | >= | <= | contains | in",
                "value": {{ <VALUE_FORMAT> }}
            }}
        ]
    }}

    ❌ FORBIDDEN:

    - Using conditions to simulate BULK selection logic
    - Using conditions to filter records that belong to source_object
    - Mixing conditions logic with filters logic

    ✅ conditions = EVENT activation  
    ✅ filters = BULK record selection

    ====================================================================
    ✅ LOOKUP AS A TEMPORARY OBJECT NODE
    ====================================================================

    When the user wants to perform a LOOKUP search, that is, 
    to extract data from a record that is external to the current context, 
    we use the TEMPORAL LOOKUP NODE. This is an object that ALWAYS exists inside actions.value.fields 
    and is used to bring a specific record into the context so that its data can 
    be used to assign values to other fields, either as a foreign key or simply by extracting its data.

    You will know when the user wants to use a TEMPORAL LOOKUP NODE because there are only two ways to invoke it:

    1. The value of a field is a LOOKUP search:
    <MODEL_FIELD> = <OBJECT_TO_LOOKUP> where <OBJECT_TO_LOOKUP_FIELD> = <ANY_VALUE>

    This means the user wants to use the LOOKUP search as a foreign key, so you must first generate the lookup node and then assign the value.

    2. The user specifies a LOOKUP search first and then extracts a value from the temporal node to assign it to a field:
    lookup <OBJECT_TO_LOOKUP> where <OBJECT_TO_LOOKUP_FIELD> = <ANY_VALUE>, then use that record to set <MODEL_FIELD> = <OBJECT_TO_LOOKUP>.<ANY_FIELD_FROM_OBJECT_TO_LOOKUP>

    In this case, the user wants you to first generate the temporal node (the lookup), and then use that node to extract the value of a field and assign it to the target object's field where the operation will be applied.


    Rules:
    - LOOKUP creates a TEMPORARY OBJECT NODE inside actions.value.fields
    - The node is NOT a model. It is NOT a real database object.
    - The node is a TEMPORARY DATA SOURCE for the execution of the current action.

    --------------------------------------------------------
    RULE 1 — LOOKUP DECLARATION
    --------------------------------------------------------

    ALL LOOKUPS MUST:

    - Be declared ONLY inside:
    actions.value.fields

    - Use a TEMPORARY ALIAS name:
    LOOKUP_<MODEL>

    - ALWAYS define:
    "value": {{
        "fields": {{
            "LOOKUP_<MODEL>": {{
                "type": "lookup",
                "model": "<REAL_MODEL_FROM_SCHEMA>",
                where: {{ ... }}
            }}
        }}
    }}

    A LOOKUP MUST ALWAYS be nested inside:

    "value": {{
        "fields": {{ <HERE> }}
    }}

    It is STRICTLY FORBIDDEN for a LOOKUP to appear:

    - As a standalone action
    - As an object inside the actions list
    - As a sibling of "operation"
    - As an independent JSON block

    --------------------------------------------------------
    ✅ 🚨 LOOKUP.where FORMAT (STRICT — ENGINE COMPATIBLE)
    --------------------------------------------------------

    The internal engine ONLY accepts the following format for LOOKUP.where:

    VALID FORMAT:

    "where": {{
        "logic": "AND" | "OR",
        "items": [
            {{
                "field_name": "<field_path_on_model>",
                "operator": "== | != | > | < | >= | <= | contains | in",
                "value": {{ <value_format> }}
            }}
        ]
    }}

    EXAMPLES:
    --------------------------------------------------------
    ✅ LOOKUP AS A FOREIGN KEY VALUE
    --------------------------------------------------------

    When the user wants to use the temporary LOOKUP node as a Foreign Key, you must generate the NODE and assign to the field the name of the NODE using the value type field, for example:

    User message:
    create an action trigger for when <OBJECT_EXAMPLE_1> is updated, then clone that record but modify:
    <FIELD_FOREIGN_KEY> = <OBJECT_TO_LOOKUP> where <FIELD_EXAMPLE_1> = <VALUE>

    Output must be:

    "value": {{
        "fields": {{
            "LOOKUP_<OBJECT_TO_LOOKUP>": {{
                "type": "lookup",
                "model": "<OBJECT_TO_LOOKUP>",
                "where": {{
                    "logic": "AND",
                    "items": [
                        {{
                            "field": "<FIELD_EXAMPLE_1>",
                            "operator": "==",
                            "value": {{
                                <VALUE>
                            }}
                        }}
                    ]
                }}
            }},
            "<FIELD_FOREIGN_KEY>": {{
                "type": "field",
                "object": "LOOKUP_<OBJECT_TO_LOOKUP>",
                "field_name": "id"
            }}
        }}
    }}

    In this way, we tell the engine that it must use the id of the LOOKUP record that was found.

    🚨 FK + LOOKUP STRICT RULE

    If a target field is a Foreign Key:

    - The value MUST NOT come from:
    - static
    - expression
    - date
    - lookup directly

    - The ONLY allowed format is:

    {{
        "type": "field",
        "object": "LOOKUP_<MODEL>",
        "field_name": "id"
    }}

    Any other format for FK assignment using LOOKUP is STRICTLY INVALID.

    --------------------------------------------------------
    ✅ LOOKUP AS ANY OTHER VALUE
    --------------------------------------------------------

    For any other value obtained from the LOOKUP NODE, we follow the same logic. The user can operate on the value using any of the <VALUE_FORMAT> types, for example:

    User message:
    create an action trigger for when <OBJECT_EXAMPLE_2> is created, then clone that record but modify:
    find the <OBJECT_LOOKUP> record where <EXAMPLE_FIELD> equals <ANY_VALUE>, then take that record and set <EXAMPLE_FIELD_2> to lookup <OBJECT_LOOKUP>.<EXAMPLE_FIELD_3> + 1 year.

    Output must be:

    "value": {{
        "fields": {{
            "LOOKUP_<OBJECT_LOOKUP>": {{
                "type": "lookup",
                "model": "<OBJECT_LOOKUP>",
                "where": {{
                    "logic": "AND",
                    "items": [
                        {{
                            "field": "<EXAMPLE_FIELD>",
                            "operator": "==",
                            "value": {{
                                <ANY_VALUE>
                            }}
                        }}
                    ]
                }}
            }},
            "<EXAMPLE_FIELD_2>": {{
                "type": "expression",
                "formula": "<OBJECT_LOOKUP>.<EXAMPLE_FIELD_3> + 1 year"
            }}
        }}
    }}

    🚨 LOOKUP EXECUTION ORDER (MANDATORY)

    When a LOOKUP is required:

    1. The LOOKUP_<MODEL> node MUST be declared FIRST inside value.fields.
    2. The consuming FIELD that references LOOKUP_<MODEL> MUST appear AFTER it.
    3. The LLM MUST NEVER assign a LOOKUP node after a consuming field.

    Invalid order = Engine execution error.

    🚨 LOOKUP CAN NEVER BE A FINAL FIELD VALUE

    The following output is STRICTLY FORBIDDEN:

    {{
        "<any_field>": {{
            "type": "lookup",
            "model": "...",
            "where": {{ ... }}
        }}
    }}

    LOOKUP is NOT a value.
    LOOKUP is a TEMPORARY DATA NODE ONLY.

    Any LOOKUP must ALWAYS be followed by a field reference using:

    {{
        "type": "field",
        "object": "LOOKUP_<MODEL>",
        "field_name": "id" | "<any_field>"
    }}

    If a LOOKUP node exists but is NOT consumed by a FIELD → the output is INVALID.

    You MUST NEVER assign "type": "lookup" directly to a business field
    such as "product", "account", "quote", etc.

    ✅ INSTEAD, you MUST:

    1) Declare a TEMPORARY LOOKUP NODE inside value.fields:
        "LOOKUP_<MODEL>": {{
            "type": "lookup",
            "model": "<REAL_MODEL>",
            "where": {{ ... }}
        }}

    2) Consume that node using a FIELD reference that points to the LOOKUP node:
        "<FOREIGN_KEY_FIELD>": {{
            "type": "field",
            "object": "LOOKUP_<MODEL>",
            "field_name": "id"
        }}

    ========================================================
    ✅ BULK + LOOKUP COEXISTENCE RULES (CRITICAL)
    ========================================================

    Using BULK operations does NOT forbid the use of LOOKUP.

    However, LOOKUP usage is ONLY valid when the requested value CANNOT be resolved from:

    - the source_object
    - the event root object
    - or any of their reachable relations

    --------------------------------------------------------

    ✅ SOURCE OBJECT AS DEFAULT CONTEXT

    When filters.source_object is present:

    - value.fields is evaluated inside an implicit loop:
    FOR EACH record in filters.source_object

    - This means that source_object becomes the DEFAULT data context for value.fields, but data from the EVENT ROOT can also be used.

    - Any value that can be obtained from source_object or its reachable relations
    MUST be referenced directly using:

    {{
        "type": "field",
        "object": "<source_object>",
        "field_name": "<field_or_empty>"
    }}

    --------------------------------------------------------

    🚨 STRICT LOOKUP DECISION RULE

    - If the user explicitly references data that belongs to:
    • source_object
    • event root
    • or their reachable relations
    → LOOKUP is STRICTLY FORBIDDEN.

    - If the user explicitly references data that belongs to:
    • a different model NOT reachable from source_object or event root
    → LOOKUP is MANDATORY.

    --------------------------------------------------------

    ✅ VALID BULK + LOOKUP COMBINATION EXAMPLE (CONCEPTUAL)

    - Values coming from source_object → use FIELD
    - Values coming from unrelated records → use LOOKUP

    🚨 LOOKUP ACTION PROHIBITION (FINAL GUARD)

    It is STRICTLY FORBIDDEN for LOOKUP to appear in ANY of the following locations:

    - As an "operation" value
    - As an object inside the "actions" array
    - As a standalone JSON block
    - As a sibling of "operation"
    - As a top-level instruction

    LOOKUP ONLY exists inside:

    actions[i].value.fields.LOOKUP_<MODEL>

    ========================================================
    ✅ CLONE OPERATION (NORMAL & BULK)
    ========================================================

    When the user explicitly says:
    - "clone"
    - "duplicate"
    - "copy this record"
    - "make a copy"

    You MUST generate: clone operation

    When generating a CLONE action, the source record to be cloned is always resolved from the CURRENT EVENT INSTANCE or from the SOURCE_OBJECT (for BULK CLONE) and their reachable relations.

    Therefore:

    - The target MUST ALWAYS begin with the ROOT MODEL of the instance that triggered the event (event root), or with the source_object in BULK operations.
    - From that root, the path may be extended to point to a related instance.

    Rules:

    - If the user wants to clone the SAME instance that triggered the action or the source_object, then the target must contain ONLY the ROOT MODEL or the SOURCE OBJECT.
    (Conceptual example: if the root is <ROOT_OBJECT>, then: target: "<ROOT_OBJECT>".  
    But if it is a bulk clone, then: target: "<SOURCE_OBJECT>")

    - If the user wants to clone a DIFFERENT instance, this is only valid if that instance is reachable from the ROOT MODEL or from the source_object through a chain of relations.
    In such cases, the target must be built as a relation chain starting from the root.
    (Conceptual example: target: "<ROOT_OBJECT>.<RELATION_1>.<RELATION_2>")

    - It is NOT allowed to define a target that does not originate from the ROOT MODEL of the event or from the source_object.
    - All logic defining WHICH instance is being cloned MUST live EXCLUSIVELY inside target.
    - The engine will automatically navigate this path at runtime.
    - The LLM MUST NOT flatten or truncate the path.
    - The LLM MUST NOT move the path into value.fields.
    - The LLM MUST NOT replace the root object with the final model.
    - Only override fields explicitly requested.
    - CLONE is NOT UPDATE.
    - CLONE always creates new records.
    - NEVER manually copy all fields.
    - NEVER guess a different root object.
    - NEVER remove intermediate relationship levels from the path.


    FINAL FORMAT:

    {{
        "operation": "CLONE",
        "filters": {{
            "source_object": "<SOURCE_MODEL>",
            "items": [
            {{
                "field": "<path_in_source>",
                "operator": "...",
                "value": {{ ... }}
            }}
            ]
        }} | null (for symple clone),
        "target": "<object_and_path>",
        "value": {{
            "fields": {{
            "<ONLY overridden fields>": {{ <VALUE FORMAT> }}
            }}
        }}
    }}

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
    🔥 GENERAL RULES FOR THE JSON STRUCTURE
    ========================================================

    1. FOREIGN KEYS (FK)
    - Check FK using MODEL_SCHEMA[target]["relations"].
    - If field is FK:
    → MUST use: {{ "type": "field", "object": "<obj>", "path": "<path_or_empty>" }}
    - NEVER use static/expression/date/raw IDs for FK fields.
    - FK values MUST come from:
        • source_object (bulk loop instance)
        • reachable relations via MODEL_SCHEMA
        • alias defined in conditions

    2. Value Sources in VALUE.FIELDS:
    - All value.fields MUST come from:
            • source_object
            • relations reachable from source_object
            • static/expression/date ONLY if the target field is NOT an FK
    - Do NOT reference unrelated objects unless they are reachable or used in filters.
    - source_object is the DEFAULT data root.

    ========================================================
    ✅ SEQUENCE (FOR AUTO NUMBERING) (STRICT)
    ========================================================

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
    ✅ DATE FUNCTION RULES (STRICT)
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


    ⚠️ STRICT REQUIREMENTS — DO NOT VIOLATE ⚠️
    - You MUST output EXACTLY the JSON structure above (no extra keys, no different formats).
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
    MODEL_SCHEMA (use these field & model names ONLY)
    ========================================================
    {json.dumps(schema, indent=2)}

    ========================================================
    AVAILABLE_MODELS
    ========================================================
    {json.dumps(available_models, indent=2)}

    ========================================================
    COMPLETED
    ========================================================
    ALWAYS returd "completed" key as TRUE, ALWAYS.
    """

    # -----------------------------------------------------
    # Add email context to system_prompt if necessary
    # -----------------------------------------------------
    if action == "EMAIL":
        # -----------------------------------------------------
        # ✅ GET CURRENT USERS
        # -----------------------------------------------------

        users = list(
            User.objects.values(
                "username",
                "first_name",
                "last_name"
            )
        )

        users_context = [
            {
                "username": u["username"],
                "full_name": f'{u["first_name"]} {u["last_name"]}'.strip()
            }
            for u in users
        ]

        # -----------------------------------------------------
        # ✅ GET CURRENT EMAIL TEMPLATES
        # -----------------------------------------------------

        email_templates = []

        # -----------------------------------------------------
        # ✅ BASE ROLES (HARDCODED)
        # -----------------------------------------------------

        roles_list = [
            "creator",
            "staff",
            "superusers",
            "admins",
        ]

        # -----------------------------------------------------
        # ✅ ADD DJANGO GROUP NAMES
        # -----------------------------------------------------

        group_names = Group.objects.values_list("name", flat=True)

        roles_list.extend(group_names)

        # (opcional) eliminar duplicados y normalizar
        roles_list = list(set(roles_list))

        system_prompt += f"""
        ========================================================
        📧 EMAIL ACTION (STRICT — ENGINE COMPATIBLE)
        ========================================================

        EMAIL is a VALID action type executed by the Action Trigger Engine.

        EMAIL is NOT a database operation.
        EMAIL does NOT create, update, clone, or delete records.
        EMAIL ONLY sends notifications.

        --------------------------------------------------------
        ✅ EMAIL ACTION FORMAT (STRICT)
        --------------------------------------------------------

        When the user requests sending an email, notification, alert, or email alert,
        you MUST generate an action with:

        {{
            "operation": "EMAIL",
            "target": "<EVENT_ROOT>",
            "email": {{
                "template": "<string>",
                "subject": {{ <VALUE_FORMAT> }},
                "title": "<optional inline template string>",
                "message": "<optional inline template string>",
                "fields_mode": "replace|append",
                "fields": ["<path>", "..."] OR [{{"label":"...","value":{{<VALUE_FORMAT>}}}}, ...],
                "recipients": {{ ... }},
                "context": {{ ... }}
            }}
        }}

        🚨 STRICT RULES:

        1) "operation" MUST be exactly:
        "EMAIL"

        2) EMAIL actions MUST be placed inside the "actions" array.

        3) EMAIL actions MUST NOT include:
        - "value"
        - "filters"
        - "source_object"

        --------------------------------------------------------
        🧩 EMAIL.title / EMAIL.message (MERGE FIELDS)
        --------------------------------------------------------

        The engine supports optional inline template strings for the default email template:

        - email.title: short header text
        - email.message: main body text

        They support Django-template merge fields using the variables in context
        (at minimum: instance, record, trigger, event).

        Example:
            "title": "Opportunity {{ instance.name }}",
            "message": "Amount: {{ instance.amount }}\\nStage: {{ instance.stage }}"

        --------------------------------------------------------
        ✅ EMAIL.fields (CONTROL WHICH FIELDS SHOW)
        --------------------------------------------------------

        If the user asks to include specific fields in the email body/table,
        you MUST add:

        - email.fields_mode: "replace" (default) or "append"
        - email.fields: list of field paths to show in the Record Details table

        Supported formats:
        1) Paths (recommended):
            "fields": ["name", "amount", "account.name", "owner.username"]

        2) Label/value entries (advanced):
            "fields": [
              {{"label": "Amount", "value": {{"type":"field","object":"opportunity","field_name":"amount"}}}}
            ]

        NOTE:
        - For numeric IDs in expressions, use CONCAT with `.pk` (NOT `.id`):
            "formula": "CONCAT('New record: ', opportunity.pk, ' Created')"
        - `.id` is NOT reliable inside expressions; prefer `.pk`.

        --------------------------------------------------------
        📄 EMAIL.template (STRICT — DEFAULT vs CUSTOM)
        --------------------------------------------------------

        Format:
        "template": "<string>"

        EMAIL.template ONLY supports TWO modes:

        --------------------------------------------------------
        1) DEFAULT TEMPLATE
        --------------------------------------------------------

        If the user does NOT explicitly mention an email template name,
        you MUST ALWAYS output:

        "template": "default"

        This is the system default email template.

        --------------------------------------------------------
        2) CUSTOM TEMPLATE
        --------------------------------------------------------

        If the user explicitly mentions an email template name in the message,
        you MUST:

        - Compare the mentioned name against the list of AVAILABLE email templates
        - The list of valid templates is provided in the variable:

        ========================================================
        EMAIL_TEMPLATES_NAMES
        ========================================================
        {json.dumps(email_templates, indent=2)}

        Rules:
        - You MUST ONLY use a template name if it EXACTLY matches
        one of the values in email_templates
        - Matching is CASE-INSENSITIVE
        - The output MUST preserve the ORIGINAL template name as stored
        in email_templates

        Output format:

        "template": "<EMAIL_TEMPLATE_NAME>"

        --------------------------------------------------------
        🚫 FORBIDDEN TEMPLATE BEHAVIOR
        --------------------------------------------------------

        - You MUST NOT invent template names
        - You MUST NOT guess similar names
        - You MUST NOT use partial matches
        - You MUST NOT use expressions
        - You MUST NOT use VALUE_FORMAT

        ❌ INVALID:
        {{
            "template": {{
                "type": "expression",
                ...
            }}
        }}

        ❌ INVALID:
        "template": "custom_template_that_does_not_exist"

        --------------------------------------------------------
        🚨 TEMPLATE FALLBACK RULE (MANDATORY)
        --------------------------------------------------------

        If the user mentions a template name BUT it does NOT match
        any value in email_templates:

        - You MUST FALL BACK to:
        "template": "default"

        - You MUST NOT throw an error
        - You MUST NOT invent a new template

        --------------------------------------------------------
        📌 EMAIL.subject
        --------------------------------------------------------

        EMAIL.subject MUST use <VALUE_FORMAT>.

        Allowed types:
        - static
        - expression
        - field

        Examples:

        STATIC:
        {{
            "type": "static",
            "value": "New Account Created"
        }}

        EXPRESSION:
        {{
            "type": "expression",
            "formula": "'New Account Created: ' + account.name"
        }}

        --------------------------------------------------------
        👥 EMAIL.recipients (STRICT)
        --------------------------------------------------------

        Structure:
        {{
            "users": [...],
            "roles": [...],
            "fields": [...],
            "external": [...]
        }}

        At least ONE of the above MUST be present.

        --------------------------------------------------------
        EMAIL.recipients.users (STRICT — USER RESOLUTION)
        --------------------------------------------------------

        EMAIL.recipients.users is a list of USERNAMES.

        The user may refer to recipients using:
        - a username
        - a full name

        However, the OUTPUT MUST ALWAYS contain USERNAMES ONLY.

        --------------------------------------------------------
        📋 AVAILABLE USERS
        --------------------------------------------------------

        The list of valid users is provided in:

        ========================================================
        USERNAMES_LIST
        ========================================================
        {json.dumps(users_context, indent=2)}

        Each entry has the following structure:

        {{
            "username": "<string>",
            "full_name": "<string>"
        }}

        --------------------------------------------------------
        🔎 USER MATCHING RULES
        --------------------------------------------------------

        When resolving recipients.users:

        1) USERNAME MATCH
        - If the user explicitly mentions a username that exists in USERNAMES_LIST:
        → add that username to recipients.users

        2) FULL NAME MATCH
        - If the user explicitly mentions a full name that matches
        the "full_name" of a user in USERNAMES_LIST (case-insensitive):
        → add the corresponding "username" to recipients.users

        3) If the user explicitly specifies that the alert should be 
        sent to themselves (for example by saying "send me", 
        "notify me", "alert me"), then automatically include the 
        username of the requesting user: {user.username}.

        --------------------------------------------------------
        🚫 FORBIDDEN BEHAVIOR
        --------------------------------------------------------

        - You MUST NOT invent usernames
        - You MUST NOT invent full names
        - You MUST NOT guess similar names
        - You MUST NOT use partial or fuzzy matches
        - You MUST NOT include full names in the output
        - You MUST NOT include users not explicitly mentioned

        --------------------------------------------------------
        🧹 DUPLICATE HANDLING
        --------------------------------------------------------

        - If the same user is mentioned multiple times
        (by username and/or full name),
        include the username ONLY ONCE.

        --------------------------------------------------------
        🚨 FALLBACK RULE
        --------------------------------------------------------

        - If the user does NOT explicitly mention any valid user
        (by username or full name),
        you MUST OMIT the "users" key entirely.

        --------------------------------------------------------
        ✅ OUTPUT FORMAT
        --------------------------------------------------------

        Example:

        "recipients": {{
            "users": ["john_doe", "maria.smith"]
        }}

        --------------------------------------------------------
         recipients.roles
        --------------------------------------------------------

        EMAIL.recipients.roles is a list of ROLE / GROUP NAMES.

        The user may refer to recipients using group / role names.
        The OUTPUT MUST contain ONLY valid group names.

        --------------------------------------------------------
        📋 AVAILABLE GROUPS
        --------------------------------------------------------

        The list of valid groups is provided in:
        {json.dumps(roles_list, indent=2)}

        --------------------------------------------------------
        🔎 ROLE / GROUP MATCHING RULES
        --------------------------------------------------------

        When resolving recipients.roles:

        1) If the user explicitly mentions a group or role name
        AND it EXACTLY matches one of the values in AVAILABLE GROUPS
        (case-insensitive),
        → include it in recipients.roles using the canonical name.

        2) If the user mentions a group or role name
        that does NOT exist in AVAILABLE GROUPS,
        → IGNORE it completely.

        --------------------------------------------------------
        🚫 FORBIDDEN BEHAVIOR
        --------------------------------------------------------

        - You MUST NOT invent group names
        - You MUST NOT guess similar group names
        - You MUST NOT normalize names
        - You MUST NOT include groups not explicitly mentioned

        --------------------------------------------------------
        🧹 DUPLICATE HANDLING
        --------------------------------------------------------

        - If the same group is mentioned multiple times,
        include it ONLY ONCE.

        --------------------------------------------------------
        🚨 FALLBACK RULE
        --------------------------------------------------------

        - If the user does NOT explicitly mention any valid group,
        you MUST OMIT the "roles" key entirely.

        --------------------------------------------------------
        ✅ OUTPUT FORMAT
        --------------------------------------------------------

        Example:

        "recipients": {{
            "roles": ["admins", "finance_team"]
        }}

        --------------------------------------------------------
        📨 recipients.fields
        --------------------------------------------------------

        EMAIL.recipients.fields defines dynamic email addresses
        resolved from the EVENT ROOT object using a FIELD PATH.

        --------------------------------------------------------
        📌 FORMAT (STRICT)
        --------------------------------------------------------

        {{
            "type": "field",
            "object": "<EVENT_ROOT>",
            "field_name": "<PATH>"
        }}

        --------------------------------------------------------
        📐 PATH RESOLUTION RULES (CRITICAL)
        --------------------------------------------------------

        The "field_name" MUST be a VALID PATH built EXCLUSIVELY
        using the MODEL_SCHEMA provided below.

        You MUST construct the path step-by-step by navigating
        through relations and fields defined in MODEL_SCHEMA.

        --------------------------------------------------------
        🔎 HOW TO BUILD A VALID PATH
        --------------------------------------------------------

        1) Start from the EVENT ROOT object
        (event_type.object_name)

        2) At each step:
        - Check MODEL_SCHEMA[current_object]["fields"]
        - Check MODEL_SCHEMA[current_object]["relations"]

        3) You may ONLY:
        - Traverse relations explicitly defined in MODEL_SCHEMA
        - End the path at a scalar field (e.g. email, username)

        4) The FINAL resolved value MUST be:
        - a string email
        - OR a list of string emails

        --------------------------------------------------------
        🚫 STRICT PROHIBITIONS
        --------------------------------------------------------

        - You MUST NOT invent fields
        - You MUST NOT invent relations
        - You MUST NOT skip relationship levels
        - You MUST NOT use objects not reachable from EVENT ROOT
        - You MUST NOT assume implicit relations
        - You MUST NOT use paths not present in MODEL_SCHEMA

        --------------------------------------------------------
        🧠 NULL HANDLING
        --------------------------------------------------------

        - If the resolved value is null at runtime,
        it will be ignored by the engine.
        - You MUST STILL output the field definition
        if the path itself is valid.

        --------------------------------------------------------
        ✅ VALID EXAMPLES
        --------------------------------------------------------

        If EVENT ROOT = "account" and MODEL_SCHEMA defines:

        account
        relations:
            owner → user
        fields:
            name
            created_at

        user
        fields:
            email

        VALID:
        {{
            "type": "field",
            "object": "account",
            "field_name": "owner.email"
        }}

        --------------------------------------------------------
        ❌ INVALID EXAMPLES
        --------------------------------------------------------

        ❌ Field does not exist:
        "field_name": "owner.mail"

        ❌ Relation not defined:
        "field_name": "manager.email"

        ❌ Skipped relation:
        "field_name": "email"

        ❌ Unreachable object:
        "field_name": "opportunity.owner.email"

        --------------------------------------------------------
        🚨 FALLBACK RULE
        --------------------------------------------------------

        - If the user mentions a dynamic email path
        that CANNOT be resolved using MODEL_SCHEMA,
        you MUST OMIT that recipients.fields entry entirely.

        - You MUST NOT guess or approximate paths.

        --------------------------------------------------------
        🌐 recipients.external
        --------------------------------------------------------

        Static list of external emails.

        Example:
            "external": [
            "sales@company.com",
            "finance@company.com"
        ]

        --------------------------------------------------------
        🧠 EMAIL.context
        --------------------------------------------------------

        EMAIL.context defines the variables available inside the email template.

        Structure:
        {{
            "<variable_name>": {{ <VALUE_FORMAT> }}
        }}

        Rules:
        - Each key becomes a template variable.
        - VALUE_FORMAT rules apply strictly.
        - object references MUST be reachable from EVENT ROOT.
        - DO NOT invent objects or fields.

        - You MUST ALWAYS include the EVENT ROOT object
            as a context variable.

        - The variable name MUST be "instance".

        --------------------------------------------------------
        ✅ DEFAULT CONTEXT FORMAT
        --------------------------------------------------------

        "context": {{
            "instance": {{
                "type": "field",
                "object": "<event_root>",
                "field_name": ""
            }}
        }}

        --------------------------------------------------------
        🚨 EMAIL ACTION HARD FAIL RULES
        --------------------------------------------------------

        - If the user does NOT request an email → DO NOT generate EMAIL.
        - If no recipients can be inferred → DO NOT guess recipients.
        - If no subject can be inferred → generate a simple static subject.
        - NEVER mix EMAIL with CREATE/UPDATE/CLONE/DELETE in the same action object.
        - EMAIL MUST ALWAYS be its own action entry inside "actions".

        --------------------------------------------------------
        ✅ EMAIL ACTION SUMMARY RULE
        --------------------------------------------------------

        When an EMAIL action is generated:
        - The description MUST mention that an email notification will be sent.
        - The summary MUST mention EMAIL explicitly.
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
    response = chat_json(
        client,
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0,
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

                # -------------------------------------------------
                # 🔥 AUTO-SET signal_timing FOR CUSTOM OBJECTS
                # -------------------------------------------------
                if evt and is_custom_object(evt.get("object_name")):
                    data["signal_timing"] = "virtual"

                event_root = evt["object_name"] if evt else None

                # -----------------------------------------
                # CONDITIONS SANITIZING
                # -----------------------------------------
                cond = data.get("conditions")
                if cond and isinstance(cond, dict):
                    items = cond.get("items") or []

                    # remove empty conditions
                    if not items:
                        data["conditions"] = None

                else:
                    data["conditions"] = None
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
        conditions = data.get("conditions")
        actions = normalize_actions(data.get("actions"), schema)

        def is_valid_event(e):
            return bool(e and e.get("object_name") in available_models and e.get("action") in ["create", "update", "delete"])

        def is_valid_actions_list(a):
            return actions_are_valid(a)

        completed_flag = is_valid_event(evt) and is_valid_actions_list(actions)

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

        normalized_data = {
            "description": data.get("description"),
            "event_type": evt,
            "conditions": conditions,
            "actions": actions,
            "active": data.get("active", True),
            "priority": priority_value,
        }

        # 🔥 PRESERVE signal_timing IF PRESENT
        if "signal_timing" in data:
            normalized_data["signal_timing"] = data["signal_timing"]

        norm.append({
            "data": normalized_data,
            "completed": completed_flag,
        })

    result["create_action_trigger"] = norm
    return result
