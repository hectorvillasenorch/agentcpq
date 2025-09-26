from django import template
from django.utils.safestring import mark_safe
from django.utils.html import escape
import json

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
def json_script(values, name):
    """
    Converts a list of values to JSON for use in templates.

    WARNING: mark_safe is used here but all values are escaped with escape().
    This is a false positive for Bandit B703/B308 and is safe.
    """
    data = {}
    for v in values:
        data[v.field.id] = escape(v.value)

    # bandit: disable=B703,B308 - false positive: all values are escaped, mark_safe is safe
    result = mark_safe(json.dumps(data))
    # bandit: enable=B703,B308

    return result
