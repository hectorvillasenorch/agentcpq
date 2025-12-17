from cpq.models import ActionTrigger
import logging

def handle_create_action_trigger(user, completed_action_triggers, response_message):
    from cpq.models import ActionTrigger
    import logging
    import re

    action_triggers_created = []

    # 🧮 Obtener el número más alto actual (ej. AT-087 → 87)
    existing_names = (
        ActionTrigger.objects.values_list("name", flat=True)
        .filter(name__startswith="AT-")
    )

    max_number = 0
    pattern = re.compile(r"AT-(\d+)")
    for name in existing_names:
        match = pattern.match(name)
        if match:
            num = int(match.group(1))
            max_number = max(max_number, num)

    for trigger_data in completed_action_triggers:
        try:

            description = trigger_data.get("description") or trigger_data.get("name")
            event_type = trigger_data.get("event_type", {})
            conditions = trigger_data.get("conditions", {})
            actions = trigger_data.get("actions", [])
            active = trigger_data.get("active", True)
            priority = trigger_data.get("priority", 100)

            # --- 🔍 VALIDACIONES ---
            if not description:
                response_message += "❌ Missing description or name for Action Trigger.<br>"
                continue

            if not isinstance(event_type, dict):
                response_message += f"❌ event_type must be a dictionary, got {type(event_type).__name__}.<br>"
                continue

            object_name = event_type.get("object_name")
            action_name = event_type.get("action")

            if not object_name or not action_name:
                response_message += "❌ event_type must contain 'object_name' and 'action'.<br>"
                continue

            if not isinstance(object_name, str) or not isinstance(action_name, str):
                response_message += f"❌ object_name and action must be strings. Got {event_type}.<br>"
                continue

            if not object_name.isidentifier() or not action_name.isidentifier():
                response_message += f"❌ Invalid identifiers in event_type: {event_type}.<br>"
                continue

            # ✅ If conditions is None → skip this validation (valid)
            if conditions is not None:
                if not isinstance(conditions, dict):
                    response_message += "❌ conditions must be null or a dictionary.<br>"
                    continue

                valid_logic = ["AND", "OR"]
                logic_val = conditions.get("logic", "AND").upper()
                if logic_val not in valid_logic:
                    response_message += f"❌ Invalid logic '{logic_val}'. Must be 'AND' or 'OR'.<br>"
                    continue

            if not isinstance(actions, list) or len(actions) == 0:
                response_message += f"❌ No actions defined for trigger '{description}'.<br>"
                continue

            # --- 🆕 GENERAR NOMBRE SECUENCIAL ---
            max_number += 1
            new_name = f"AT-{max_number:03d}"  # Formato con ceros: AT-001, AT-087, etc.

            # --- ✅ CREAR TRIGGER ---
            new_trigger = ActionTrigger.objects.create(
                name=new_name,
                description=description,
                event_type=event_type,
                conditions=conditions,
                actions=actions,
                active=active,
                created_by=user,
                priority=priority
            )

            action_triggers_created.append(new_trigger)
            response_message += f"✅ Action Trigger '{new_name}' created successfully.<br>"

        except Exception as e:
            logging.error(f"❌ Error creating Action Trigger: {str(e)}")
            response_message += f"❌ Error creating Action Trigger: {str(e)}<br>"
            continue

    return response_message, action_triggers_created