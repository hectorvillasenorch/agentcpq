import logging
import json
from django.db.models import Q
from cpq.models import Product
from django.forms.models import model_to_dict
from cpq.models import BusinessRule, QuoteLine, Quote
from decimal import Decimal

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

def check_inclusion_rules_for_quote_level(user, target_type, rule_type, quote, product, skip_existing=False, quote_line=None):


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

        logging.info("📜 ################################# Evaluating inclusion rule: %s (%s)", rule.name, rule.description)
        if rule.rule_type == "inclusion":
            success, result = check_inclusion_rule(user, conditions, quote, product, rule, skip_existing, quote_line)

            if success == "success":
                logging.warning(f"Rule {rule.name} has been triggered.")
                triggered_rules += f"Rule: {rule.name} has been triggered -> {rule.error_message}."
            else:
                logging.warning("###################################### Inclusion rule %s did not apply.", rule.name)

    return triggered_rules

def check_inclusion_rule(user, conditions, quote, product, rule=None, skip_existing=False, quote_line=None):
    # Handle products to add
    from ..quote_agent.handle_helpers import handle_products_to_add

    def _compare_values(left, right, operator):
        try:
            # Try numeric comparison if both look like numbers
            lnum = float(left)
            rnum = float(right)
            left, right = lnum, rnum
        except (TypeError, ValueError):
            pass

        if operator == "==":
            return left == right
        if operator == "!=":
            return left != right
        if operator == ">":
            try:
                return left > right
            except Exception:
                return False
        if operator == "<":
            try:
                return left < right
            except Exception:
                return False
        if operator == ">=":
            try:
                return left >= right
            except Exception:
                return False
        if operator == "<=":
            try:
                return left <= right
            except Exception:
                return False
        if operator == "contains":
            try:
                return right in left
            except Exception:
                return False
        return False

    def _get_value(scope, field):
        if scope == "quote":
            return getattr(quote, field, None)
        if scope == "product":
            return getattr(product, field, None)
        if scope == "quote_line" and quote_line is not None:
            return getattr(quote_line, field, None)
        return None

    trigger_product = conditions.get("trigger_product")
    applies_to = conditions.get("applies_to") or None
    extra_conditions = conditions.get("conditions") if isinstance(conditions, dict) else None

    # Build a list of conditions to evaluate (supports both legacy applies_to and a conditions list)
    to_evaluate = []
    if applies_to and isinstance(applies_to, dict):
        cond = {
            "scope": applies_to.get("scope", "quote"),
            "field": applies_to.get("field"),
            "operator": applies_to.get("operator", "=="),
            "value": applies_to.get("value"),
        }
        to_evaluate.append(cond)

    if isinstance(extra_conditions, list):
        for item in extra_conditions:
            if not isinstance(item, dict):
                continue
            scope = item.get("scope", "quote")
            field = item.get("field")
            operator = item.get("operator", "==")
            value = item.get("value")
            to_evaluate.append({"scope": scope, "field": field, "operator": operator, "value": value})

    # Evaluate all conditions; if any fail, rule does not apply
    for cond in to_evaluate:
        field = cond.get("field")
        if not field:
            return "failed", None
        scope = cond.get("scope", "quote")
        operator = cond.get("operator", "==")
        target_value = cond.get("value")
        current_value = _get_value(scope, field)
        if not _compare_values(current_value, target_value, operator):
            return "failed", None

    if trigger_product["sku"] is not None:
        if (trigger_product["sku"] == product.sku) or (trigger_product["sku"] == product.name):
            included_products = conditions.get("included_products") or []
            if skip_existing:
                filtered = []
                for inc in included_products:
                    inc_sku = inc.get("sku") or inc.get("name")
                    if not inc_sku:
                        continue
                    exists = QuoteLine.objects.filter(quote=quote).filter(
                        Q(product__sku__iexact=inc_sku) | Q(product__name__iexact=inc_sku) | Q(sku__iexact=inc_sku)
                    ).exists()
                    if not exists:
                        filtered.append(inc)
                included_products = filtered
                if not included_products:
                    return "failed", None

            result = handle_products_to_add(user, included_products, quote, allow_updates=True, parent_line=quote_line)

            logging.info("################################# Inclusion rule fired")
            logging.info(
                "Rule=%s QuoteID=%s Trigger=%s Included=%s",
                getattr(rule, "name", None) if 'rule' in locals() else None,
                getattr(quote, "id", None),
                trigger_product,
                included_products,
            )

            return "success", result
    elif trigger_product["name"] is not None:
        if (trigger_product["name"] == product.sku) or (trigger_product["name"] == product.name):
            included_products = conditions.get("included_products") or []
            if skip_existing:
                filtered = []
                for inc in included_products:
                    inc_sku = inc.get("sku") or inc.get("name")
                    if not inc_sku:
                        continue
                    exists = QuoteLine.objects.filter(quote=quote).filter(
                        Q(product__sku__iexact=inc_sku) | Q(product__name__iexact=inc_sku) | Q(sku__iexact=inc_sku)
                    ).exists()
                    if not exists:
                        filtered.append(inc)
                included_products = filtered
                if not included_products:
                    return "failed", None

            result = handle_products_to_add(user, included_products, quote, allow_updates=True, parent_line=quote_line)

            logging.info(
                "################################# Inclusion rule fired",
                extra={
                    "rule": getattr(rule, "name", None) if 'rule' in locals() else None,
                    "quote_id": getattr(quote, "id", None),
                    "trigger": trigger_product,
                    "included": included_products,
                },
            )

            return "success", result

    return "failed", None

def check_exclusion_rules_for_quote_level(user,quote, product):


    rules = BusinessRule.objects.filter(
        active=True,
        rule_type="exclusion"
        ).filter(
        Q(target_type="quote_line") | Q(target_type="multiple")
    ).order_by('-priority')


    triggered_rules = ""


    for rule in rules:
        try:
            conditions = rule.conditions
        except Exception as e:
            logging.warning(f"Error in rule {rule.name} with conditions: {e}")
            continue # Skip the rules with conditions bad formed

        logging.info(f"\n📜 Evaluating exclusion rule: {rule.name} ('{rule.description}')")

        result = check_exclusion_rule(user, conditions, quote, product)

        # ✅ Si la función devolvió None o no hubo conflicto, continuar
        if not result or result.get("valid", True):
            continue

        # 🚫 Si se encontró conflicto
        error_msg = (
            f"❌ Exclusion rule triggered: {rule.name}<br>"
            f"Details: {result.get('error')}<br>"
            f"Rule message: {rule.error_message}<br>"
        )

        logging.warning(error_msg)
        triggered_rules += error_msg

        # 💡 Puedes decidir si detener en el primer conflicto o seguir evaluando
        # return triggered_rules  # <-- descomenta esto si quieres detener en el primer conflicto

    # Si no se violó ninguna regla
    if not triggered_rules:
        return None

    return triggered_rules

def check_exclusion_rule(user, conditions, quote, product):
    excluded_products = conditions.get("excluded_products", [])

    # Si no hay productos de exclusión, salir
    if not excluded_products:
        return None

    # 1️⃣ Verificar si el producto que se intenta agregar está en la lista de exclusión
    product_names_or_skus = [p.lower() for p in excluded_products]
    if product.name.lower() not in product_names_or_skus and product.sku.lower() not in product_names_or_skus:
        # No forma parte de la regla, entonces no aplica esta validación
        return None

    # 2️⃣ Buscar si algún otro producto de exclusión ya está presente en la cotización
    for line in quote.quote_lines.all():
        line_product = line.product
        if not line_product:
            continue

        # Si el producto en la línea coincide con otro de los excluidos
        if (
            line_product.name.lower() in product_names_or_skus
            or line_product.sku.lower() in product_names_or_skus
        ):
            # Y no es el mismo que el producto actual
            if line_product.id != product.id:
                # 🚫 Regla violada: ambos productos no pueden coexistir
                return {
                    "valid": False,
                    "error": f"❌ The products '{product.name}' and '{line_product.name}' cannot coexist in the quote.",
                    "conflicting_product": line_product.name,
                }

    # ✅ Si no hay conflicto, entonces todo bien
    return {"valid": True}


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

def _normalize_for_compare(actual_value, rule_value):
    """Devuelve (actual_normalized, rule_normalized, type_tag)"""
    # None handling
    if actual_value is None:
        return None, rule_value, "none"

    # If actual_value is a Django model instance or any object with attributes,
    # try to extract a sensible primitive (name, title, value, id) before comparing.
    # Avoid importing Django here to keep lazo débil.
    if hasattr(actual_value, "__dict__") and not isinstance(actual_value, (str, bytes, int, float, Decimal, bool)):
        # prefer common "name" or "title" attributes
        for candidate in ("name", "title", "label"):
            candidate_val = getattr(actual_value, candidate, None)
            if candidate_val is not None:
                actual_value = candidate_val
                break
        else:
            # Fallback to str()
            actual_value = str(actual_value)

    # Numbers: normalize to Decimal for safe comparisons
    if isinstance(actual_value, Decimal):
        try:
            return actual_value, Decimal(str(rule_value)), "number"
        except Exception:
            return actual_value, rule_value, "mixed"
    if isinstance(actual_value, (int, float)):
        try:
            return Decimal(str(actual_value)), Decimal(str(rule_value)), "number"
        except Exception:
            return actual_value, rule_value, "mixed"

    # Strings: strip whitespace and compare as strings
    if isinstance(actual_value, (str, bytes)):
        actual_s = actual_value.decode() if isinstance(actual_value, bytes) else actual_value
        rule_s = rule_value.decode() if isinstance(rule_value, bytes) else str(rule_value)
        return actual_s.strip(), rule_s.strip(), "string"

    # Booleans
    if isinstance(actual_value, bool):
        return actual_value, bool(rule_value), "bool"

    # Fallback: compare their string forms
    return str(actual_value), str(rule_value), "string"

def check_validation_conditions_for_quote_level(data, quote, depth=1):
    indent = "  " * depth

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

            # allow nested attributes: "quote.account.name" etc.
            model_name, attr_path = field.split(".", 1)
            obj = {"quote": quote}.get(model_name)

            if not obj:
                logging.warning(f"{indent}❌ Object not found for: {model_name}")
                return False

            # traverse nested attributes safely
            actual_value = obj
            for part in attr_path.split("."):
                actual_value = getattr(actual_value, part, None)
                if actual_value is None:
                    logging.warning(f"{indent}❌ Attribute '{part}' not found when traversing '{attr_path}'")
                    return False

            logging.info(f"{indent}🔍 Comparing: {actual_value} {operator} {value}")

            # normalize types
            actual_norm, rule_norm, ttag = _normalize_for_compare(actual_value, value)

            try:
                if operator == "==":
                    result = actual_norm == rule_norm
                elif operator == "!=":
                    result = actual_norm != rule_norm
                elif operator == ">":
                    result = actual_norm > rule_norm
                elif operator == ">=":
                    result = actual_norm >= rule_norm
                elif operator == "<":
                    result = actual_norm < rule_norm
                elif operator == "<=":
                    result = actual_norm <= rule_norm
                else:
                    logging.warning(f"{indent}❌ Unsupported operator: {operator}")
                    return False

                logging.info(f"{indent}Result: {result}\n")
                return result
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
                err_message = (
                    "⚠️ For security reasons, we cannot show all the rules. "
                    "If you want to render all rules, please type: show all rules.<br><br>"
                    "🔍 Available search methods:<br>"
                    "- By name: e.g., VR-00653, ER-87098, or IR-000654.<br>"
                    "- By rule type: validation, exclusion, or inclusion.<br>"
                    "- By target type: quote or quote line item.<br>"
                    "- By priority: numerical value of the rule’s priority (default priority is 10).<br>"
                    "- By status: active or inactive."
                )

                logging.warning(err_message)

                return {"message": err_message}

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
