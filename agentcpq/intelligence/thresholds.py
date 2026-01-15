from __future__ import annotations

from decimal import Decimal


SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


def _resolve_operand(operand, metrics: dict):
    if isinstance(operand, dict) and "metric" in operand:
        return metrics.get(operand["metric"])
    return operand


def evaluate_condition(condition: dict, metrics: dict) -> bool:
    if not condition:
        return False
    op = (condition.get("op") or "").lower()
    if op in {"and", "or"}:
        args = condition.get("args", [])
        results = [evaluate_condition(arg, metrics) for arg in args]
        return all(results) if op == "and" else any(results)

    left = _resolve_operand(condition.get("left"), metrics)
    right = _resolve_operand(condition.get("right"), metrics)
    try:
        left_val = Decimal(str(left))
        right_val = Decimal(str(right))
    except Exception:
        left_val = left
        right_val = right

    if op == "<":
        return left_val < right_val
    if op == "<=":
        return left_val <= right_val
    if op == ">":
        return left_val > right_val
    if op == ">=":
        return left_val >= right_val
    if op == "==":
        return left_val == right_val
    if op == "!=":
        return left_val != right_val
    return False


def render_template(template: str, context: dict) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


def select_top_risk_sentence(triggered_rules: list, metrics: dict) -> str:
    if not triggered_rules:
        return ""
    ordered = sorted(
        triggered_rules,
        key=lambda rule: SEVERITY_RANK.get(rule.get("severity", "low"), 0),
        reverse=True,
    )
    top = ordered[0]
    return render_template(top.get("message_template", ""), metrics)
