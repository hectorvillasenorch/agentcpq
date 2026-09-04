from django.contrib.auth.models import User, Group
from cpq.action_trigger.helpers.helpers_and_format import normalize_model_name


def resolve_recipients(recipients_def, instance, context):
    emails = set()

    emails |= _resolve_users(recipients_def.get("users", []))
    emails |= _resolve_roles(recipients_def.get("roles", []))
    emails |= _resolve_fields(recipients_def.get("fields", []), instance, context)
    emails |= set(recipients_def.get("external", []))

    emails = {e for e in emails if e}
    return _filter_email_opted_out(emails)


def _filter_email_opted_out(emails):
    """Drop any recipient whose Lead/Contact has opted out of email (compliance)."""
    if not emails:
        return emails
    from cpq.models import Lead, Contact

    opted_out = set(
        Lead.objects.filter(email__in=emails, email_opt_out=True).values_list("email", flat=True)
    )
    opted_out |= set(
        Contact.objects.filter(email__in=emails, email_opt_out=True).values_list("email", flat=True)
    )
    return {e for e in emails if e not in opted_out}


def _resolve_users(usernames):
    if not usernames:
        return set()

    return set(
        User.objects
        .filter(username__in=usernames)
        .exclude(email__isnull=True)
        .values_list("email", flat=True)
    )


def _resolve_roles(role_names):
    if not role_names:
        return set()

    return set(
        User.objects
        .filter(groups__name__in=role_names)
        .exclude(email__isnull=True)
        .values_list("email", flat=True)
    )


def _resolve_fields(fields_defs, instance, context):
    emails = set()

    for f in fields_defs:
        if not isinstance(f, dict):
            continue

        if f.get("type") != "field":
            continue

        obj = f.get("object")
        path = f.get("field_name")

        if not obj or not path:
            continue

        value = _resolve_field_path(obj, path, instance, context)

        if isinstance(value, list):
            emails |= set(value)
        elif isinstance(value, str):
            emails.add(value)

    return emails


def _resolve_field_path(obj_name, path, instance, context):
    from cpq.action_trigger.trigger_engine import engine

    fake_ref = {
        "type": "field",
        "object": obj_name,
        "field_name": path,
    }

    # Alias map mínimo correcto
    alias_map = {
        None: instance,
        **{k: v for k, v in context.items() if hasattr(v, "__class__")}
    }

    return engine._resolve_value_from_reference(fake_ref, alias_map, instance)
