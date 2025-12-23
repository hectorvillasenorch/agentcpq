def resolve_subject(subject_def, instance, context):
    if not subject_def:
        return "Notification"

    from cpq.action_trigger.trigger_engine import engine
    value = engine._resolve_value_for_action(subject_def, instance, context)

    return str(value) if value else "Notification"
