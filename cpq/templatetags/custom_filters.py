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
