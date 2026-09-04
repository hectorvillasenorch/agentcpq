from cpq.models import ActionTrigger
from django.apps import apps
from collections import OrderedDict
from django.db.models import Case, When

import json
import os
import re
import logging

import openai
from dotenv import load_dotenv
from django.apps import apps

from cpq.models import CustomObject

from agents.llm import chat_json, get_llm_client, get_model

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = get_model("structured")

client = get_llm_client()


def get_action_triggers_details(action_triggers):
    """
    Recibe un queryset o lista de ActionTrigger y devuelve una lista JSON-serializable
    con los detalles listos para mostrar en el frontend.
    """

    if not action_triggers:
        return []

    # ✅ MANTENER ORDEN ORIGINAL DE CREACIÓN
    if hasattr(action_triggers, "values"):
        triggers_qs = action_triggers
    else:
        ids = [t.id for t in action_triggers]
        triggers_qs = ActionTrigger.objects.filter(id__in=ids).order_by(
            Case(*[When(id=pk, then=pos) for pos, pk in enumerate(ids)])
        )

    trigger_details = []

    for trigger in triggers_qs:
        actions = trigger.actions or []

        reordered_actions = []

        for action in actions:
            op = action.get("operation")

            # -------------------------------------------------
            # 🔥 EMAIL ACTION — DO NOT TOUCH value / fields
            # -------------------------------------------------
            if op == "EMAIL":
                reordered_actions.append(action)
                continue

            # -------------------------------------------------
            # DB ACTIONS ONLY
            # -------------------------------------------------
            target = action.get("target")
            value = action.get("value") or {}
            fields = value.get("fields") or {}

            model = _resolve_model_from_target(target)

            if model and fields:
                value["fields"] = _reorder_fields_by_model(fields, model)
                action["value"] = value

            reordered_actions.append(action)

        trigger_details.append({
            "id": trigger.id,
            "name": trigger.name,
            "description": trigger.description,
            "event_type": trigger.event_type,
            "conditions": trigger.conditions or {},
            "actions": reordered_actions,
            "active": trigger.active,
            "created_by": trigger.created_by.username,
            "created_at": trigger.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        })

    return trigger_details

def _resolve_model_from_target(target: str):
    """
    Resuelve el modelo final a partir de un target como:
    - "subscription"
    - "opportunity.primary_quote"
    - "opportunity.primary_quote.account"
    """
    if not isinstance(target, str) or not target:
        return None

    parts = target.split(".")

    try:
        # Modelo raíz
        model = apps.get_model("cpq", parts[0])
    except Exception:
        return None

    # Recorrer relaciones si hay path
    for rel in parts[1:]:
        try:
            field = model._meta.get_field(rel)
            model = field.related_model
        except Exception:
            return None

    return model

def _reorder_fields_by_model(fields: dict, model):
    """
    Reordena un dict de fields para que coincida con el orden del modelo Django.
    """
    if not isinstance(fields, dict) or not model:
        return fields

    ordered = OrderedDict()

    # Orden real del modelo (solo fields, no relaciones reversas)
    model_field_names = [f.name for f in model._meta.fields]

    # 1️⃣ Primero los que existen en el modelo
    for fname in model_field_names:
        if fname in fields:
            ordered[fname] = fields[fname]

    # 2️⃣ Luego cualquier extra (custom, lookup, etc.)
    for fname, value in fields.items():
        if fname not in ordered:
            ordered[fname] = value

    return ordered


def action_trigger_creation_type_with_llm(user_message):

    # -----------------------------------------------------
    # ✅ SYSTEM PROMPT
    # -----------------------------------------------------
    system_prompt = """
    Your job is simple:
    Review the user's message and determine what type of action trigger creation they want to perform:

    1. Graphic Mode:  
    The user does NOT specify details of the action trigger such as event type, conditions, or actions to execute.  
    These messages are usually simple, for example:  
    - "Create an action trigger"  
    - "I want to create an action trigger"  
    - "I want to create a workflow"  
    And any phrases related to action trigger, workflow, automation.

    2. Text Mode:  
    The user DOES specify action trigger details in the message.

        Text Operation:
        Add the "action" key to the JSON object specifying the exact action the user wants to perform after the conditions 
        in the action trigger are met. Do not consider "action" to be the action of creating the action trigger itself. 
        "Action" refers to what the user wants the engine to do after the action trigger executes. The options are: CREATE, CLONE, UPDATE, DELETE, and EMAIL.

    Your task is to return the following JSON:
    If mode = graphic
    {
        "mode": "graphic"
    }

    If mode = text
    {
        "mode": "text",
        "action": "CREATE | CLONE | UPDATE | DELETE | EMAIL"
    }
    """

    # -----------------------------------------------------
    # ✅ User Prompt
    # -----------------------------------------------------
    user_prompt = f"""
        User message: "{user_message}"

        Return ONLY valid JSON. No text outside the JSON.
        """

    # -----------------------------------------------------
    # ✅ LLM CALL
    # -----------------------------------------------------
    response = chat_json(client,
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

    return result

def get_cpq_model_schema():
    schema = {}

    for model in apps.get_app_config("cpq").get_models():
        model_name = model.__name__
        object_name = model_name.lower()

        if model_name == "QuoteLine":
            object_name = "quote_line"

        fields = {}

        for field in model._meta.get_fields():

            # 🔹 ForeignKey (navegable)
            if field.is_relation and field.many_to_one and field.related_model:
                fields[field.name] = {
                    "type": "fk",
                    "target": field.related_model.__name__.lower()
                }

            # 🔹 Campo normal
            elif field.concrete:
                fields[field.name] = {
                    "type": "number"
                        if field.get_internal_type() in [
                            "IntegerField",
                            "DecimalField",
                            "FloatField"
                        ]
                        else "string"
                }

        schema[object_name] = {
            "fields": fields
        }

    return schema


# ---------------------------------------------------------------------------
# Lead → Account + Contact + Opportunity conversion trigger
# ---------------------------------------------------------------------------

LEAD_CONVERSION_EVENT_TYPE = {"object_name": "lead", "action": "update"}
LEAD_CONVERSION_CONDITIONS = {
    "logic": "AND",
    "items": [
        {
            "alias": None,
            "source": {"object": "lead", "field_name": "status"},
            "operator": "==",
            "target": {"type": "static", "value": "qualified"},
        }
    ],
}
LEAD_CONVERSION_ACTIONS = [
    {"operation": "CREATE", "mode": "lead_conversion", "target": "account"}
]
LEAD_CONVERSION_DESCRIPTION = (
    "Auto-convert a Lead into Account, Contact and Opportunity when the Lead becomes Qualified."
)


def _is_lead_conversion_request(user_message: str) -> bool:
    text = (user_message or "").lower()
    if "lead" not in text:
        return False
    if not re.search(r"\b(convert|conversion|converted)\b", text):
        return False
    if not re.search(r"\b(account|contact|opportunit)\b", text):
        return False
    return True


def create_lead_conversion_trigger(user):
    """Create (or refresh) the single active lead-conversion trigger. Returns (trigger, created)."""
    existing = None
    for t in ActionTrigger.objects.filter(active=True):
        for a in (t.actions or []):
            if isinstance(a, dict) and (a.get("mode") or "").lower() == "lead_conversion":
                existing = t
                break
        if existing:
            break

    if existing:
        existing.event_type = LEAD_CONVERSION_EVENT_TYPE
        existing.conditions = LEAD_CONVERSION_CONDITIONS
        existing.actions = LEAD_CONVERSION_ACTIONS
        existing.description = LEAD_CONVERSION_DESCRIPTION
        existing.schedule_type = "immediate"
        existing.save()
        return existing, False

    max_number = 0
    for name in ActionTrigger.objects.filter(name__startswith="AT-").values_list("name", flat=True):
        m = re.match(r"AT-(\d+)", name)
        if m:
            max_number = max(max_number, int(m.group(1)))

    trigger = ActionTrigger.objects.create(
        name=f"AT-{max_number + 1:03d}",
        description=LEAD_CONVERSION_DESCRIPTION,
        event_type=LEAD_CONVERSION_EVENT_TYPE,
        conditions=LEAD_CONVERSION_CONDITIONS,
        actions=LEAD_CONVERSION_ACTIONS,
        active=True,
        created_by=user,
        schedule_type="immediate",
    )
    return trigger, True


def build_lead_conversion_trigger_response(user, user_message):
    trigger, created = create_lead_conversion_trigger(user)
    details = get_action_triggers_details([trigger])
    verb = "created" if created else "already active and refreshed"
    message = (
        f"✅ Lead conversion automation {verb}.<br>"
        "When a Lead's status is set to <b>Qualified</b>, it will automatically create an "
        "<b>Account</b>, a linked <b>Contact</b>, and an <b>Opportunity</b>, and mark the Lead as <b>Converted</b>."
    )
    return {
        "message": message,
        "action_triggers_details": details,
        "hiddenMessage": "True",
    }