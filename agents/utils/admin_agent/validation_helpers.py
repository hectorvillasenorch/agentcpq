from cpq.models import BusinessRule


def validate_rule_update_request(name, field, value):
    response_message = ""

    if name is None:
        response_message += f"⚠️ Error: No rule name to update was detected in your request. Please specify the rule name.<br><br>"

        return False, response_message, None

    try:
        rule = BusinessRule.objects.get(name=name)
    except BusinessRule.DoesNotExist:
        response_message += f"⚠️ Error: The rule with the name <strong>{name}</strong> does not exist.<br><br>"

        return False, response_message, None

    if field is None:
        response_message += f"⚠️ Error: No field to update was detected in your request. Please specify which attribute (e.g., rule type, target type, priority, error message, active, description or conditions) you want to modify.<br><br>"

        return False, response_message, None

    available_fields = ["rule_type", "target_type", "priority", "error_message", "active", "conditions", "description"]

    if field not in available_fields:
        response_message += f"⚠️ Error: '{field}' is not a recognized field. Allowed fields are: {', '.join(available_fields)}.<br><br>"

        return False, response_message, None

    if value is None:
        response_message += f"⚠️ Error: No value to update was detected in your request.<br><br>"

        return False, response_message, None

    string_fields = ["rule_type", "target_type", "error_message", "description"]
    if field in string_fields and not isinstance(value, str):
        response_message += f"⚠️ Error: The field '{field}' must be updated with a string value.<br><br>"

        return False, response_message, None

    if field == "rule_type":
        allowed_rule_types = ["validation", "inclusion", "exclusion"]
        if value not in allowed_rule_types:
            response_message += f"⚠️ Error: The field 'rule type' must be one of: {', '.join(allowed_rule_types)}.<br><br>"

            return False, response_message, None

    if field == "target_type":
        allowed_target_types = ["quote", "quote_line", "multiple"]
        if value not in allowed_target_types:
            response_message += f"⚠️ Error: The field 'target type' must be one of: {', '.join(allowed_target_types)}.<br><br>"

            return False, response_message, None

    if field == "priority" and not isinstance(value, int):
        response_message += "⚠️ Error: The field 'priority' must be an integer (e.g., 1, 5, 10).<br><br>"

        return False, response_message, None

    if field == "active" and not isinstance(value, bool):
        response_message += "⚠️ Error: The field 'active' must be a boolean value: use `true` to enable the rule, or `false` to disable it.<br><br>"

        return False, response_message, None

    if field == "conditions":
        if not isinstance(value, dict):
            response_message += "⚠️ Error: The field 'conditions' must be a JSON object with a 'logic' key and an 'items' list.<br><br>"

            return False, response_message, None

        if "logic" not in value or "items" not in value:
            response_message += "⚠️ Error: The 'conditions' object must include both 'logic' (e.g., 'AND') and 'items' (a list of condition objects).<br><br>"

            return False, response_message, None

        if not isinstance(value["logic"], str) or not isinstance(value["items"], list):
            response_message += "⚠️ Error: In the 'conditions' object, 'logic' must be a string (e.g., 'AND'), and 'items' must be a list of conditions.<br><br>"

            return False, response_message, None

    return True, "", rule
