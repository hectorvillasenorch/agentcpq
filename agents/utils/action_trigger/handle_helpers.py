from cpq.models import ActionTrigger
import logging

def handle_create_action_trigger(user, completed_action_triggers, response_message):
    from cpq.models import ActionTrigger
    import logging

    action_triggers_created = []

    for trigger_data in completed_action_triggers:
        try:
            data = trigger_data.get("data", {})
            description = data.get("description")
            event_type = data.get("event_type")
            conditions = data.get("conditions", {})
            actions = data.get("actions", [])
            active = data.get("active", True)

            # --- 🔍 Validations ---

            # 1. Required fields
            if not description:
                response_message += "❌ Missing description for Action Trigger.<br>"
                continue

            if not event_type:
                response_message += "❌ Missing event_type (e.g. 'quote_line.updated').<br>"
                continue

            if not isinstance(conditions, dict) or not conditions.get("items"):
                response_message += f"❌ Invalid or empty conditions: {conditions}.<br>"
                continue

            if not isinstance(actions, list) or len(actions) == 0:
                response_message += f"❌ No actions defined for trigger '{description}'.<br>"
                continue

            # 2. Validate event_type format
            if "." not in event_type:
                response_message += f"❌ Invalid event_type format: {event_type}. Must be like 'quote_line.updated'.<br>"
                continue

            event_parts = event_type.split(".")
            if len(event_parts) != 2:
                response_message += f"❌ Invalid event_type: {event_type}. Expected format '<object>.<action>'.<br>"
                continue

            object_part, action_part = event_parts
            if not object_part.isidentifier() or not action_part.isidentifier():
                response_message += f"❌ Invalid object or action in event_type: {event_type}.<br>"
                continue

            # 3. Validate conditions logic
            valid_logic = ["AND", "OR"]
            if conditions.get("logic", "AND").upper() not in valid_logic:
                response_message += f"❌ Invalid logic '{conditions.get('logic')}'. Must be 'AND' or 'OR'.<br>"
                continue

            # --- ✅ Create ActionTrigger record ---
            new_trigger = ActionTrigger.objects.create(
                description=description,
                event_type=event_type,
                conditions=conditions,
                actions=actions,
                active=active,
                created_by=user  # si tu modelo tiene este campo
            )

            action_triggers_created.append(new_trigger)
            response_message += f"✅ Action Trigger '{description}' created successfully.<br>"

        except Exception as e:
            logging.error(f"❌ Error creating Action Trigger: {str(e)}")
            response_message += f"❌ Error creating Action Trigger: {str(e)}<br>"
            continue

    return response_message, action_triggers_created