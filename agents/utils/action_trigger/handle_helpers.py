from cpq.models import ActionTrigger
import logging

def handle_create_action_trigger(user, completed_action_triggers, response_message):
    action_triggers_created = []

    for action_trigger in completed_action_triggers:
        trigger = action_trigger.get("trigger", None)
        action = action_trigger.get("action", None)
        object_name = action_trigger.get("object_name", None)
        action_params = action_trigger.get("action_params", {})
        active = action_trigger.get("active", True)  # default True

        try:
            # --- Validations ---
            if trigger not in ["opportunity_closed_won"]:
                response_message += f"❌ Invalid trigger: {trigger}. Must be 'opportunity_closed_won'.<br>"
                continue

            if action not in ["create", "update", "delete"]:
                response_message += f"❌ Invalid action: {action}. Must be 'create', 'update', or 'delete'.<br>"
                continue

            if object_name not in ["renewal_task"]:
                response_message += f"❌ Invalid object_name: {object_name}. Must be 'renewal_task'.<br>"
                continue

            if object_name == "renewal_task":
                months_before = action_params.get("months_before")
                if months_before not in ["immediately", 3, 6]:
                    response_message += f"❌ Invalid months_before for renewal_task: {months_before}. Must be 'immediately', 3, or 6.<br>"
                    continue

            # --- Create ActionTrigger record ---
            new_trigger = ActionTrigger.objects.create(
                trigger=trigger,
                action=action,
                object_name=object_name,
                action_params=action_params,
                active=active
            )

            action_triggers_created.append(new_trigger)
            response_message += f"✅ Action trigger '{trigger} -> {action} {object_name}' created successfully.<br>"

        except Exception as e:
            logging.error(f"❌ Error creating action trigger: {str(e)}")
            response_message += f"❌ Error creating action trigger: {str(e)}<br>"

    return response_message, action_triggers_created