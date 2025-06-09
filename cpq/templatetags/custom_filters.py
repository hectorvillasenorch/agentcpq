from django import template

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