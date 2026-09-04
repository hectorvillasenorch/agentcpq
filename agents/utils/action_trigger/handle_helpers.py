from cpq.models import ActionTrigger
import logging
import re
from datetime import datetime


def _field_for_schedule_hint(rest):
    rest = (rest or "").lower()
    if "expir" in rest or "expires" in rest:
        return "expiration_date"
    if "renew" in rest or "ends" in rest or "end date" in rest:
        return "end_date"
    if "start" in rest or "begins" in rest:
        return "start_date"
    if "due" in rest or "deadline" in rest:
        return "due_date"
    if "close" in rest:
        return "expected_close_date"
    return None


def _extract_schedule(text):
    """Parse scheduling hints out of a natural-language trigger description.

    Returns (schedule_type, schedule_config).
    """
    if not text:
        return "immediate", None
    t = str(text)

    # Absolute date: "on/by 2026-09-15 [09:00]" or "on Sep 15 2026".
    m = re.search(
        r"\b(?:on|by|send\s+(?:it\s+)?on|send\s+on)\s+(\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?)",
        t,
        re.IGNORECASE,
    )
    if m:
        raw = m.group(1).replace(" ", "T")
        if "T" not in raw:
            raw += "T09:00:00"
        return "date", {"send_at": raw}

    m2 = re.search(
        r"\bon\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})",
        t,
        re.IGNORECASE,
    )
    if m2:
        try:
            dt = datetime.strptime(f"{m2.group(1)[:3].title()} {int(m2.group(2))} {int(m2.group(3))}", "%b %d %Y")
            return "date", {"send_at": dt.strftime("%Y-%m-%dT09:00:00")}
        except Exception:
            pass

    # Relative offset: "7 days before the quote expires" / "3 days after renewal".
    m3 = re.search(r"(\d+)\s+days?\s+(before|after|prior\s+to)\s+(.+)", t, re.IGNORECASE)
    if m3:
        try:
            n = int(m3.group(1))
        except ValueError:
            n = 0
        direction = -1 if m3.group(2).lower() in ("before", "prior to") else 1
        date_field = _field_for_schedule_hint(m3.group(3))
        if date_field:
            return "offset", {"date_field": date_field, "offset_days": direction * n}

    return "immediate", None


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
            signal_timing = trigger_data.get("signal_timing", "post_save")

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

            # --- 📅 SCHEDULING (from LLM fields if present, else parse the phrase) ---
            schedule_type = trigger_data.get("schedule_type")
            schedule_config = trigger_data.get("schedule_config")
            if schedule_type not in ("immediate", "offset", "date"):
                schedule_type, schedule_config = _extract_schedule(description)

            # --- ✅ CREAR TRIGGER ---
            new_trigger = ActionTrigger.objects.create(
                name=new_name,
                description=description,
                event_type=event_type,
                conditions=conditions,
                actions=actions,
                active=active,
                created_by=user,
                priority=priority,
                signal_timing=signal_timing,
                schedule_type=schedule_type,
                schedule_config=schedule_config,
            )

            action_triggers_created.append(new_trigger)
            response_message += f"✅ Action Trigger '{new_name}' created successfully.<br>"

        except Exception as e:
            logging.error(f"❌ Error creating Action Trigger: {str(e)}")
            response_message += f"❌ Error creating Action Trigger: {str(e)}<br>"
            continue

    return response_message, action_triggers_created