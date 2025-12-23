from cpq.action_trigger.email.recipients import resolve_recipients
from cpq.action_trigger.email.subject import resolve_subject
from cpq.action_trigger.email.context import resolve_email_context
from cpq.action_trigger.email.sender import send_email

from cpq.action_trigger.email.default_context import build_default_email_context


class EmailActionError(Exception):
    """Error controlado de EMAIL action"""
    pass


def execute_email_action(*, action, instance, context):
    email_def = action.get("email")
    if not email_def:
        raise EmailActionError("EMAIL action missing 'email' block")

    if "recipients" not in email_def:
        raise EmailActionError("EMAIL action missing 'recipients'")

    if "template" not in email_def:
        raise EmailActionError("EMAIL action missing 'template'")

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
    template_name = email_def.get("template", "default")

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

    # -------------------------
    # SEND
    # -------------------------
    send_email(
        template=email_def.get("template"),
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
            "template": email_def.get("template"),
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
