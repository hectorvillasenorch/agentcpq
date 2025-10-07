from django import template
from django.utils.safestring import mark_safe
from django.utils.html import escape
import json
from django.utils.html import json_script as django_json_script

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
