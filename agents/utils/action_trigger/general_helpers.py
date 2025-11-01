from cpq.models import ActionTrigger


def get_action_triggers_details(action_triggers):
    """
    Recibe un queryset o lista de ActionTrigger y devuelve una lista JSON-serializable
    con los detalles listos para mostrar en el frontend.
    """

    if not action_triggers:
        return []

    # Aseguramos que siempre tengamos un queryset evaluable
    triggers_qs = (
        action_triggers
        if hasattr(action_triggers, "values")
        else ActionTrigger.objects.filter(id__in=[t.id for t in action_triggers])
    )

    trigger_details = []
    for trigger in triggers_qs:
        trigger_details.append({
            "trigger": trigger.get_trigger_display(),  # Mostrar label legible
            "action": trigger.get_action_display(),    # Mostrar label legible
            "object_name": trigger.get_object_name_display(),  # Mostrar label legible
            "action_params": trigger.action_params or {},
            "active": trigger.active,
            "created_at": trigger.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        })

    return trigger_details