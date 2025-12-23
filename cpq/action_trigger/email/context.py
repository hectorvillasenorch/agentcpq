def resolve_email_context(context_def, instance, context):
    resolved = {
        "instance": instance
    }

    for key, value_def in (context_def or {}).items():
        if key == "instance":
            continue  # ya está

        resolved[key] = _resolve_value(value_def, instance, context)

    return resolved


def _resolve_value(value_def, instance, context):
    from cpq.action_trigger.trigger_engine import engine
    return engine._resolve_value_for_action(value_def, instance, context)
