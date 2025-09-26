import logging
import json
from django.db.models import Q
from cpq.models import Product
from django.forms.models import model_to_dict
from cpq.models import BusinessRule, QuoteLine, Quote

# Validation Helpers
from .validation_helpers import validate_rule_update_request

# General Helpers
from .general_helpers import generate_conditions_format

# Record Helpers
from .record_helpers import update_rule_record


def check_for_rules_quote_line_level(target_type, rule_type, quote, product, quote_line):
    #   Accept one rule type (str) or many types (list)
    if isinstance(rule_type, str):
        rule_type = [rule_type]

    rules = BusinessRule.objects.filter(
        active=True,
        rule_type__in=rule_type
        ).filter(
        Q(target_type=target_type) | Q(target_type="multiple")
    ).order_by('-priority')


    triggered_rules = []

    #data = model_to_dict(quote_line)
    #formatted = json.dumps(data, indent=4, default=str)
    #print(f"\n🧾 Formatted QuoteLine:\n{formatted}")

    for rule in rules:
        try:
            conditions = rule.conditions
        except Exception as e:
            logging.warning(f"Error: {e}")
            continue # Skip the rules with conditions bad formed

        print(f"\n📜 Evaluating rule: {rule.name} ('{rule.description}')")
        if rule.rule_type == "validation":
            if check_validation_conditions(conditions, quote, product, quote_line):
                logging.warning(f"🚫 Validation Rule: ({rule.name}) {rule.error_message}")
                triggered_rules.append(f"(Rule: {rule.name}) {rule.error_message}")
            else:
                logging.info(f"✅ No problems with rule {rule.name} ('{rule.description}')\n\n")

    return triggered_rules

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

def check_inclusion_rules_for_quote_level(user, target_type, rule_type, quote, product):


    rules = BusinessRule.objects.filter(
        active=True,
        rule_type=rule_type
        ).filter(
        Q(target_type=target_type) | Q(target_type="multiple")
    ).order_by('-priority')


    triggered_rules = ""


    for rule in rules:
        try:
            conditions = rule.conditions
        except Exception as e:
            logging.warning(f"Error: {e}")
            continue # Skip the rules with conditions bad formed

        print(f"\n📜 Evaluating inclusion rule: {rule.name} ('{rule.description}')")
        if rule.rule_type == "inclusion":
            logging.warning("Comprobando si la regla aplica")
            success, result = check_inclusion_rule(user, conditions, quote, product)

            if success:
                logging.warning(f"La rule {rule.name} se ha triggereado")
                triggered_rules += f"Rule: {rule.name} has been triggered -> {rule.error_message}."
            else:
                logging.warning("La regla no aplica.")

    return triggered_rules

def check_inclusion_rule(user, conditions, quote, product):
    # Handle products to add
    from ..quote_agent.handle_helpers import handle_products_to_add

    trigger_product = conditions.get("trigger_product")
    
    if (trigger_product["sku"] == product.sku) or (trigger_product["name"] == product.sku) or (trigger_product["name"] == product.name) or (trigger_product["sku"] == product.name):
        included_products = conditions.get("included_products")

        result = handle_products_to_add(user, included_products, quote, allow_updates=True)

        return "success", result

    return "failed", None
            

def check_for_rules_quote_level(target_type, rule_type, quote):
    #   Accept one rule type (str) or many types (list)
    if isinstance(rule_type, str):
        rule_type = [rule_type]

    rules = BusinessRule.objects.filter(
        active=True,
        rule_type__in=rule_type
        ).filter(
        Q(target_type=target_type) #| Q(target_type="multiple") (Just target_type = quote for MVP)
    ).order_by('-priority')

    print(f"\n\nRules: {rules}\n\n")


    triggered_rules = []

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
        if rule.rule_type == "validation":
            if check_validation_conditions_for_quote_level(conditions, quote):
                logging.warning(f"🚫 Validation Rule: ({rule.name}) {rule.error_message}")
                triggered_rules.append(f"(Rule: {rule.name}) {rule.error_message}")
            else:
                logging.info(f"✅ No problems with rule {rule.name}\n\n")

    return triggered_rules

def check_validation_conditions_for_quote_level(data, quote, depth=1):
    indent = "  " * depth  # For console indentation

    if isinstance(data, dict):
        if "logic" in data and "items" in data:
            logic = data["logic"]

            results = []
            for item in data["items"]:
                result = check_validation_conditions_for_quote_level(item, quote, depth + 1)
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
            obj = {"quote": quote}.get(model_name)

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
        results = [check_validation_conditions_for_quote_level(item, quote, depth) for item in data]
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
    temp_line.check_term_is_not_null_for_subscriptions()
    temp_line.update_discount_fields()
    temp_line.update_subtotal()
    temp_line.update_total_price()

    return temp_line

def handle_extracted_rules_details(extracted_rules_details):
    try:

        resulting_rules = []

        for index, rule in enumerate(extracted_rules_details):
            name = rule.get("name")
            rule_type = rule.get("rule_type")
            target_type = rule.get("target_type")
            priority = rule.get("priority")
            active = rule.get("active")
            request_description = rule.get("request_description")

            # Make sure priority is int and active is bool
            if isinstance(priority, str) and priority.isdigit():
                priority = int(priority)

            if isinstance(active, str):
                active = active.lower() == "true"

            # Return a warning message to the user to avoid displaying all rules.
            if all(value is None for value in [name, rule_type, target_type, priority, active, request_description]):
                logging.warning("⚠️ For security reasons, we cannot show all the rules. If you want to render all rules, please type: show all rules.")
                return {
                    "message": "⚠️ For security reasons, we cannot show all the rules. If you want to render all rules, please type: show all rules."
                }

            # If name exists, found just by name
            if name:
                if isinstance(name, list):
                    query = BusinessRule.objects.filter(name__in=name)
                else:
                    query = BusinessRule.objects.filter(name=name)
            else:
                # Build dynamic filter
                query = BusinessRule.objects.all()

                # If no rule type is specified, search in all rule types
                if not rule_type:
                    query = query.filter(rule_type__in=["validation", "inclusion", "exclusion"])
                elif isinstance(rule_type, list):
                    query = query.filter(rule_type__in=rule_type)
                else:
                    query = query.filter(rule_type=rule_type)

                # If no target type is specified, search in all target types
                if not target_type:
                    query = query.filter(target_type__in=["quote", "quote_line", "multiple"])
                elif isinstance(target_type, list):
                    query = query.filter(target_type__in=target_type)
                else:
                    query = query.filter(target_type=target_type)

                # Priority
                if priority is not None:
                    # Puede ser lista o entero
                    if isinstance(priority, list):
                        query = query.filter(priority__in=priority)
                    else:
                        query = query.filter(priority=priority)

                # Active
                if active is not None:
                    query = query.filter(active=active)

            resulting_rules.append({
                "rules_request_description": request_description,
                "rules": list(query)
            })


        return list(resulting_rules)
    except Exception as e:
        logging.warning(f"❌ Error in handle_extracted_rules_details: {e}")
        return e

def handle_rules_updates(extracted_updates, response_message):
    logging.info("🔧 Handling rule updates...")

    updated_rules = []

    for index, update in enumerate(extracted_updates, start=1):
        name = update.get("name", None)
        field = update.get("field", None)
        value = update.get("value", None)

        response_message += f"<b>🔄 <u>Rule Update Request #{index}</u> 🔄</b><br>"
        # ✅ Format response message
        field_labels = {
            "rule_type": "Rule Type",
            "target_type": "Target Type",
            "prioriy": "Priority",
            "error_message": "Error Message",
            "active": "Active",
            "description": "Description",
            "conditions": "Conditions"
        }

        response_message += f"🧾 Rule: {name}<br>"
        response_message += f"🏷️ Field: {field_labels.get(field, field.capitalize())}<br>"
        response_message += f"✏️ Value: {value if field != 'conditions' else generate_conditions_format(value)}<br><br>"

        # Validate request informatio
        is_valid, feedback, rule = validate_rule_update_request(name, field, value)

        if not is_valid:
            response_message += feedback
            logging.warning(response_message)
            continue

        update_payload = {
            "rule": rule,
            "field": field,
            "value": value
        }

        logging.warning(f"=>>>>>>>>>>>>>>>>>>>> Trying to update rule: {update_payload}")

        # Try to update rule

        response = update_rule_record(update_payload)

        if response.get("success"):
            response_message += f"{response.get('message')}<br><br>"
            updated_rules.append(update_payload)
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> {response.get('message')}")
        else:
            error_msg = response.get("message", "Unknown error.")
            response_message += f"{error_msg}<br>"

            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> ⚠️ {error_msg}")

    return response_message, updated_rules

def handle_rules_deletes(extracted_deletes, response_message):
    logging.info("🔧 Handling rule deletions...")

    deleted_rules = []

    for index, update in enumerate(extracted_deletes, start=1):
        name = update.get("name", None)

        response_message += f"<b>🔄 <u>Rule Delete Request #{index}</u> 🔄</b><br>"
        # ✅ Format response message

        response_message += f"🧾 Rule: {name}<br><br>"

        try:
            logging.warning(f"=>>>>>>>>>>>>>>>>>>>> Trying to delete rule: {name}")
            rule = BusinessRule.objects.get(name=name)
            rule.delete()
            deleted_rules.append(name)
            response_message += f"✅ The rule with name '{name}' was successfully deleted.<br><br>"
            continue
        except BusinessRule.DoesNotExist:
            logging.warning(f"⚠️ Error: The rule with the name {name} does not exist.")
            response_message += f"⚠️ Error: The rule with the name <strong>{name}</strong> does not exist.<br><br>"

            continue

    return response_message, deleted_rules
