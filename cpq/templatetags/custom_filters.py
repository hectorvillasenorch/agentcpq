from django import template
from django.utils.safestring import mark_safe
from django.utils.html import escape
import json
from django.utils.html import json_script as django_json_script
import re
from decimal import Decimal, InvalidOperation

register = template.Library()

@register.filter
def get_item(dictionary, key):
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None

@register.filter
def dict_get(d, key):
    try:
        return d.get(key, {})
    except Exception:
        return {}

@register.filter
def get_field_value(values, field):
    for val in values:
        if val.field_id == field.id:
            return val.value
    return ''

@register.filter
def json_script(values, element_id):
    """
    Converts a list of values into safe JSON for the template.
    Uses django.utils.html.json_script to automatically escape everything.
    """
    data = {v.field.id: v.value for v in values}
    return django_json_script(data, element_id)


@register.filter
def label_from_options(options, raw_value):
    """
    Given a list of option dicts (with id/label), return the matching label for the value.
    Falls back to the raw value when no match is found.
    """
    if raw_value is None:
        return ""

    try:
        for opt in options or []:
            if str(opt.get("id")) == str(raw_value):
                return opt.get("label") or raw_value
    except Exception:
        pass
    return raw_value


def _parse_loose_decimal(value) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    text = re.sub(r"[^0-9,.\-]+", "", text)
    if not text:
        return None

    has_dot = "." in text
    has_comma = "," in text

    if has_dot and has_comma:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "")
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma and not has_dot:
        parts = text.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            text = ".".join(parts)
        else:
            text = text.replace(",", "")

    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


@register.filter
def format_custom_value(raw_value, data_type):
    t = (data_type or "").lower().strip()
    if raw_value is None:
        return ""

    text = str(raw_value).strip()
    if text == "":
        return ""

    if t == "currency":
        amount = _parse_loose_decimal(text)
        if amount is None:
            return raw_value
        return f"${amount.quantize(Decimal('0.01')):,.2f}"

    if t in {"percent", "percentage"}:
        amount = _parse_loose_decimal(text)
        if amount is None:
            return raw_value
        amount = amount.quantize(Decimal("0.01"))
        display = f"{amount:.2f}".rstrip("0").rstrip(".")
        return f"{display}%"

    return raw_value
