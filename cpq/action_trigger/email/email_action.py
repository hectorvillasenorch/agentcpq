from cpq.action_trigger.email.recipients import resolve_recipients
from cpq.action_trigger.email.subject import resolve_subject
from cpq.action_trigger.email.context import resolve_email_context
from cpq.action_trigger.email.sender import send_email

from cpq.action_trigger.email.default_context import build_default_email_context
from django.template import Context, Engine, TemplateSyntaxError


class EmailActionError(Exception):
    """Error controlado de EMAIL action"""
    pass


def _render_inline_template(template_str: str, context_dict: dict) -> str:
    """
    Render a small inline Django-template string using the default template engine.
    This is intended for admin/trigger-authored content (subject/title/message).
    """
    if template_str is None:
        return ""
    if not isinstance(template_str, str):
        return str(template_str)

    try:
        template = Engine.get_default().from_string(template_str)
        return template.render(Context(context_dict, autoescape=True)).strip()
    except TemplateSyntaxError as exc:
        raise EmailActionError(f"Invalid inline template syntax: {exc}") from exc


def _normalize_model_name_for_engine(instance) -> str:
    name = instance.__class__.__name__
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _apply_selected_record_fields(*, email_def: dict, email_context: dict, instance, engine_context: dict):
    """
    Allows callers to control which fields appear in the default email's "Record Details" table.

    Supported formats:
    - email.fields: ["name", "amount", "account.name", "monto__c", "proyecto__c"]
        (paths are resolved relative to the triggering instance; custom fields supported via *__c*)
    - email.fields: [{"label": "Amount", "value": {"type": "field", "object": "opportunity", "path": "amount"}}]

    By default, if email.fields is provided we REPLACE record.fields.
    Set email.fields_mode="append" to merge with the auto-extracted fields.
    """
    fields_def = email_def.get("fields")
    if not fields_def:
        return

    if not isinstance(fields_def, list):
        raise EmailActionError("EMAIL 'fields' must be a list")

    from cpq.action_trigger.trigger_engine import engine

    inst_obj = _normalize_model_name_for_engine(instance)
    resolved_fields = {}

    for item in fields_def:
        if isinstance(item, str):
            path = item.strip()
            if not path:
                continue
            value_def = {"type": "field", "object": inst_obj, "path": path}
            resolved = engine._resolve_value_for_action(value_def, instance, engine_context)
            resolved_fields[path] = "" if resolved is None else str(resolved)
            continue

        if isinstance(item, dict):
            label = (item.get("label") or item.get("name") or "").strip()
            value_def = item.get("value")
            if not label or not isinstance(value_def, dict):
                raise EmailActionError("Each EMAIL 'fields' dict item must have 'label' and 'value'")
            resolved = engine._resolve_value_for_action(value_def, instance, engine_context)
            resolved_fields[label] = "" if resolved is None else str(resolved)
            continue

        raise EmailActionError("EMAIL 'fields' items must be strings or {label,value} objects")

    # Ensure record structure exists for templates that expect it
    email_context.setdefault("record", {})
    email_context["record"].setdefault("fields", {})

    mode = (email_def.get("fields_mode") or "replace").lower()
    if mode == "append":
        email_context["record"]["fields"].update(resolved_fields)
        return

    # Default: replace
    email_context["record"]["fields"] = resolved_fields


def execute_email_action(*, action, instance, context):
    email_def = action.get("email")
    if not email_def:
        raise EmailActionError("EMAIL action missing 'email' block")

    if "recipients" not in email_def:
        raise EmailActionError("EMAIL action missing 'recipients'")

    # Backwards-compatible: template is required unless the user provides an inline body.
    # If omitted but inline content exists, we default to the generic template.
    template_name = email_def.get("template")
    if not template_name:
        if email_def.get("message") is None and email_def.get("title") is None:
            raise EmailActionError("EMAIL action missing 'template'")
        template_name = "default"

    # -------------------------
    # Subject
    # -------------------------
    subject = resolve_subject(
        email_def.get("subject"),
        instance,
        context,
    )

    # -------------------------
    # Recipients
    # -------------------------
    recipients_def = email_def.get("recipients", {})

    recipients = resolve_recipients(
        recipients_def,
        instance,
        context,
    )

    if not recipients:
        raise EmailActionError("EMAIL action has no resolved recipients")

    # -------------------------
    # Context
    # -------------------------
    if template_name == "default":
        email_context = build_default_email_context(
            trigger=context.get("_trigger"),   # lo pone el engine
            action=action,
            instance=instance,
            engine_context=context,
        )
    else:
        email_context = resolve_email_context(
            email_def.get("context", {}),
            instance,
            context,
        )

    # Ensure consistent merge-field root
    email_context.setdefault("instance", instance)

    # Optional inline title/message with merge fields (Django template syntax)
    # Example: "Ingreso creado: {{ instance.custom_identifier }}"
    render_ctx = {
        **email_context,
        "action": action,
        "trigger_model": context.get("_trigger"),
        "engine_context": context,
    }
    if email_def.get("title") is not None:
        email_context["title"] = _render_inline_template(email_def.get("title"), render_ctx)
    if email_def.get("message") is not None:
        email_context["message"] = _render_inline_template(email_def.get("message"), render_ctx)

    # Optional: choose exactly which fields appear in the "Record Details" table
    _apply_selected_record_fields(
        email_def=email_def,
        email_context=email_context,
        instance=instance,
        engine_context=context,
    )

    # -------------------------
    # SEND
    # -------------------------
    send_email(
        template=template_name,
        subject=subject,
        recipients=recipients,
        context=email_context,
    )

    # -------------------------
    # RETURN METADATA
    # -------------------------
    return {
        "sent": True,
        "email": {
            "template": template_name,
            "subject": subject,
            "recipients": {
                "roles": recipients_def.get("roles", []),
                "users": recipients_def.get("users", []),
                "external": recipients_def.get("external", []),
                "fields": recipients_def.get("fields", []),
            },
            "resolved_recipients": sorted(recipients),
            "context_keys": list(email_context.keys()),
        }
    }
