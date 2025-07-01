import logging
import json
from django.db.models import Q
from django.forms.models import model_to_dict
from cpq.models import BusinessRule, QuoteLine

def check_for_rules(target_type, quote, product, quote_line):


    rules = BusinessRule.objects.filter(active=True, rule_type="validation").filter(
        Q(target_type=target_type) | Q(target_type="multiple")
    ).order_by('-priority')


    validations = []

    #data = model_to_dict(quote_line)
    #formatted = json.dumps(data, indent=4, default=str)
    #print(f"\n🧾 Formatted QuoteLine:\n{formatted}")

    for rule in rules:
        try:
            conditions = rule.conditions
        except Exception as e:
            logging.warning(f"Error: {e}")
            continue # Skip the rules with conditions bad formed

        print(f"\n📜 Evaluating rule: {rule.name}")
        if check_validation_conditions(conditions, quote, product, quote_line):
            logging.warning(f"🚫 Violation: {rule.error_message}")
            validations.append(rule.error_message)
        else:
            logging.info(f"✅ No problems with rule {rule.name}\n\n")

    return validations

def check_validation_conditions(data, quote, product, quote_line, depth=1):
    indent = "  " * depth  # For console indentation

    if isinstance(data, dict):
        if "logic" in data and "items" in data:
            logic = data["logic"]

            results = []
            for item in data["items"]:
                result = check_validation_conditions(item, quote, product, quote_line, depth + 1)
                results.append(result)

            if logic == "AND":
                return all(results)
            elif logic == "OR":
                return any(results)
            else:
                logging.warning(f"{indent}❌ Unknown logical operator: {logic}")
                return False

        elif all(key in data for key in ["fieldName", "operator", "value"]):
            field = data["fieldName"]
            operator = data["operator"]
            value = data["value"]

            model_name, attr = field.split(".", 1)
            obj = {"quote": quote, "quote_line": quote_line, "product": product}.get(model_name)

            if not obj:
                logging.warning(f"{indent}❌ Object not found for: {model_name}")
                return False

            actual_value = getattr(obj, attr, None)

            if actual_value is None:
                logging.warning(f"{indent}❌ Attribute '{attr}' not found in {model_name}")
                return False

            logging.info(f"{indent}🔍 Comparing: {actual_value} {operator} {value}")

            try:
                if operator == "==":
                    result = actual_value == value
                    logging.info(f"Result: {result}\n")
                    return result
                elif operator == "!=":
                    result = actual_value != value
                    logging.info(f"Result: {result}\n")
                    return result
                elif operator == ">":
                    result = actual_value > value
                    logging.info(f"Result: {result}\n")
                    return result
                elif operator == ">=":
                    result = actual_value >= value
                    logging.info(f"Result: {result}\n")
                    return result
                elif operator == "<":
                    result = actual_value < value
                    logging.info(f"Result: {result}\n")
                    return result
                elif operator == "<=":
                    result = actual_value <= value
                    logging.info(f"Result: {result}\n")
                    return result
                else:
                    logging.warning(f"{indent}❌ Unsupported operator: {operator}")
                    return False
            except Exception as e:
                logging.warning(f"{indent}❌ Error during comparison: {e}")
                return False
        else:
            logging.warning(f"{indent}⚠️ Unknown dictionary structure: {data}")
            return False

    elif isinstance(data, list):
        results = [check_validation_conditions(item, quote, product, quote_line, depth) for item in data]
        return all(results)

    else:
        logging.warning(f"{indent}❌ Unexpected data type: {type(data).__name__}")
        return False
    

def build_temp_quote_line(quote, product, quantity, discount_type, discount_amount, term):
    """
    Builds a temporary instance of QuoteLine without saving it to the database.
    Used to validate rules before creating it.
    """
    temp_line = QuoteLine(
        quote=quote,
        product=product,
        quantity=quantity,
        discount_type=discount_type,
        discount_percentage=discount_amount if discount_type == "percentage" else 0,
        discount_amount=discount_amount if discount_type == "amount" else 0,
        unit_price=product.price,
        is_subscription=product.is_subscription,
        term=term
    )

    if not temp_line.product_name:
        temp_line.product_name = product.name
    if not temp_line.sku:
        temp_line.sku = product.sku

    # Aplica los cálculos de descuento, subtotal y total
    temp_line.update_discount_fields()
    temp_line.update_subtotal()
    temp_line.update_total_price()

    return temp_line