from django import template
import json
from django.utils.safestring import mark_safe

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
    data = {}
    for v in values:
        data[v.field.id] = v.value
    return mark_safe(json.dumps(data))