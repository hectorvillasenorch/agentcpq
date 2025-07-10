from cpq.models import BusinessRule
import logging

def update_rule_record(update_request):
    try:
        rule = update_request.get("rule", None)
        field = update_request.get("field", None)
        new_value = update_request.get("value", None)

        # ✅ Update based on the field dynamically
        string_fields = ["rule_type", "target_type", "error_message", "description"]

        if field in string_fields:
            setattr(rule, field, str(new_value))
        elif field == "priority":
            setattr(rule, field, int(new_value))
        elif field == "active":
            setattr(rule, field, bool(new_value))
        elif field == "conditions":
            setattr(rule, field, new_value)

        rule.save()

        response_message = "✅ Rule updated successfully."

        return {
            "message": response_message,
            "success": True
        }
    
    except ValueError as ve:
        return {
            "message": str(ve),
            "success": False
        }

    except Exception as e:
        logging.warning(f"⚠️ Error updating rule: {str(e)}")
        return {
            "message": f"Error updating rule: {str(e)}",
            "success": False
        }