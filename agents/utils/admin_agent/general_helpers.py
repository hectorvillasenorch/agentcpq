from cpq.models import BusinessRule
import re

def get_rules_details(handle_rules):
    return [
        {
            "rules_request_description": item["rules_request_description"],
            "rules": [
                {
                    "name": rule_obj.name,
                    "description": rule_obj.description,
                    "target_type": rule_obj.target_type,
                    "rule_type": rule_obj.rule_type,
                    "priority": rule_obj.priority,
                    "error_message": rule_obj.error_message,
                    "conditions": rule_obj.conditions,
                    "active": rule_obj.active,
                    "created_at": rule_obj.created_at.isoformat() if rule_obj.created_at else None
                }
                for rule_obj in item["rules"]
            ]
        }
        for item in handle_rules
    ]

def generate_conditions_format(data, depth=0):
    indent = "  " * depth

    field_labels = {
        "quote_line.discount_percentage": "discount",
        "quote_line.discount_amount": "discount",
        "quote_line.sku": "product",
        "quote_line.quantity": "quantity",
        "quote_line.price": "price",
        "quote_line.family": "product family",
        "quote_line.name": "product name",
        "quote_line.term_months": "term (months)",
    }

    operator_map = {
        "==": "is",
        "!=": "is not",
        ">=": "is at least",
        "<=": "is at most",
        ">": "is greater than",
        "<": "is less than"
    }

    def format_value(field, value):
        if isinstance(value, dict):
            return generate_conditions_format(value, depth + 1)
        elif "percentage" in field:
            return f"{value}%"
        elif "amount" in field or "price" in field:
            return f"${value}"
        else:
            return f"{value}"

    if isinstance(data, dict):
        if "logic" in data and "items" in data:
            logic = data["logic"].upper()
            connector = " and " if logic == "AND" else " or "
            sub_descriptions = [
                generate_conditions_format(item, depth + 1)
                for item in data["items"]
            ]
            return "(" + connector.join(sub_descriptions) + ")"

        elif all(key in data for key in ["fieldName", "operator", "value"]):
            field = data["fieldName"]
            operator = data["operator"]
            value = data["value"]

            label = field_labels.get(field, field.split(".")[-1].replace("_", " "))
            op_phrase = operator_map.get(operator, operator)
            formatted_value = format_value(field, value)

            return f"{label} {op_phrase} {formatted_value}"

    elif isinstance(data, list):
        return " and ".join(
            generate_conditions_format(item, depth) for item in data
        )

    return ""