import re
from decimal import Decimal
from django.db.models import Model
from typing import Any, Dict, Optional

# -------------------------------------------------------------------------
#                          Helpers and formatting
# -------------------------------------------------------------------------
def normalize_model_name(name: str) -> str:
    import re
    if not name:
        return name
    if name == name.lower() and "_" in name:
        return name
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def to_camel_case(snake: str) -> str:
    return ''.join(part.capitalize() for part in snake.split('_'))

def debug_alias_map(alias_map: Dict[Optional[str], Any]) -> Dict[str, str]:
    def lab(v: Any) -> str:
        if v is None:
            return "None"
        try:
            return f"{v.__class__.__name__}(pk={getattr(v, 'pk', '?')})"
        except Exception:
            return str(v)
    return {str(k): lab(v) for k, v in alias_map.items()}

def normalize_number(value):
    if value is None:
        return None
    if isinstance(value, bool):  # <-- agrega esto
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        val = value.strip().lower()
        # Boolean normalization
        if val in ("true", "1", "yes", "y", "t"):
            return True
        if val in ("false", "0", "no", "n", "f"):
            return False
        try:
            return float(val)
        except ValueError:
            return value
    return value

def make_json_safe(obj: Any) -> Any:
    """
    Converts any non-serializable object (Decimal, Model, etc.)
    into a JSON-safe representation (float, str, dict, list, etc.).
    """
    from decimal import Decimal
    from django.db.models import Model

    if obj is None:
        return None
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [make_json_safe(v) for v in obj]
    if isinstance(obj, Model):
        return f"{obj.__class__.__name__}(pk={obj.pk})"
    return str(obj)

def get_model_class(model_name_snake: str):
    """
    Converts a snake_case model name into its CamelCase Django model class.
    Compatible with both CPQ native models and custom object models.
    """
    from django.apps import apps

    try:
        # Example: quote_line → QuoteLine
        ModelClass = apps.get_model("cpq", to_camel_case(model_name_snake))
        return ModelClass
    except LookupError:
        # Fallback: try with the model name as-is
        try:
            return apps.get_model("cpq", model_name_snake)
        except LookupError:
            return None