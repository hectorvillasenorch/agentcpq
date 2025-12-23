from datetime import datetime
from django.db.models import Model


def build_default_email_context(*, trigger, action, instance, engine_context):
    """
    Construye el contexto estándar para el template 'default'.

    - NO usa templates
    - NO usa SMTP
    - NO depende de modelos específicos
    """

    event_type = trigger.event_type or {}
    object_name = event_type.get("object_name", "record")
    action_name = event_type.get("action", "").lower()

    title = _build_title(object_name, action_name)
    message = _build_message(object_name, action_name, instance)

    return {
        "title": title,
        "message": message,

        "event": {
            "object": object_name,
            "action": action_name,
            "event_type": f"{object_name}.{action_name}",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },

        "trigger": {
            "name": trigger.name or f"{object_name} {action_name}",
            "conditions": _conditions_to_text(trigger.conditions),
        },

        "record": {
            "model": instance.__class__.__name__,
            "pk": instance.pk,
            "fields": _extract_fields(instance),
        }
    }


def _build_title(object_name, action):
    verb_map = {
        "create": "Created",
        "clone": "Cloned",
        "update": "Updated",
        "delete": "Deleted",
    }
    verb = verb_map.get(action, action.capitalize())
    return f"{object_name.replace('_', ' ').title()} {verb}"

def _build_message(object_name, action, instance):
    display = _get_display_name(instance)

    if action == "create":
        return (
            f"A new {object_name} named \"{display}\" has been created."
            if display else
            f"A new {object_name} record has been created."
        )

    if action == "clone":
        return (
            f"A new {object_name} named \"{display}\" has been cloned."
            if display else
            f"A new {object_name} record has been cloned."
        )

    if action == "update":
        return (
            f"The {object_name} \"{display}\" has been updated."
            if display else
            f"The {object_name} record has been updated."
        )

    if action == "delete":
        return f"The {object_name} record has been deleted."

    return f"The {object_name} record has been affected."


def _get_display_name(instance):
    for attr in ("name", "first_name", "title", "subject"):
        value = getattr(instance, attr, None)
        if value:
            return value
    return None


def _conditions_to_text(conditions):
    if not conditions:
        return None

    logic = conditions.get("logic", "AND")
    items = conditions.get("items", [])

    parts = []

    for c in items:
        src = c.get("source", {})
        field = src.get("field_name", "field")
        op = c.get("operator", "")
        target = c.get("target", {}).get("value", "")

        parts.append(f"{field} {op} {target}")

    if not parts:
        return None

    return f" {logic} ".join(parts)

def _extract_fields(instance: Model):
    fields = {}

    for f in instance._meta.get_fields():
        # ❌ No campos reales
        if not f.concrete or f.many_to_many:
            continue

        # ❌ Primary key
        if f.primary_key:
            continue

        # ❌ Unique (emails, usernames, external_ids, etc.)
        if getattr(f, "unique", False):
            continue

        name = f.name

        # ❌ Campos sensibles
        if name in ("password", "token", "secret"):
            continue

        try:
            value = getattr(instance, name)
            if value is not None:
                fields[name] = str(value)
        except Exception:
            continue

    return fields
