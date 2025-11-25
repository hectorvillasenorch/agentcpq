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
            "name": trigger.name,
            "description": trigger.description,    # Mostrar label legible
            "event_type": trigger.event_type,  # Mostrar label legible
            "conditions": trigger.conditions or {},
            "actions": trigger.actions or {},
            "active": trigger.active,
            "created_by": trigger.created_by.username,
            "created_at": trigger.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        })

    return trigger_details