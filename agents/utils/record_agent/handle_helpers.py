from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple, Union

from django.core.exceptions import FieldDoesNotExist
from django.db.models import (
    Model,
    Field,
    ForeignKey,
    DateField as DJDateField,
    DateTimeField as DJDateTimeField,
    BooleanField as DJBooleanField,
    DecimalField as DJDecimalField,
    IntegerField,
    BigIntegerField,
    SmallIntegerField,
    PositiveIntegerField,
    PositiveSmallIntegerField,
    FloatField,
    TextField,
    CharField,
)
from django.contrib.contenttypes.models import ContentType
from django.utils.dateparse import parse_date, parse_datetime

from ..analytics_agent.handle_helpers import ALLOWED_FIELDS, get_object_metadata
from ..message_formatters import SUCCESS_ICON
from cpq.models import CustomFieldValue
from agents.models import SingleRecordLayout

logger = logging.getLogger(__name__)


DEFAULT_LOOKUPS = {
    "Account": ["name", "custom_identifier", "id"],
    "Contact": ["email", "custom_identifier", "id"],
    "Lead": ["email", "phone", "first_name", "last_name", "id"],
    "Opportunity": ["name", "id"],
    "Product": ["sku", "name", "id"],
    "Quote": ["name", "id"],
    "CustomRecord": ["custom_identifier", "record_id", "id"],
}

PRIMARY_FIELD_MAP = {
    "Account": "name",
    "Contact": "email",
    "Lead": "email",
    "Opportunity": "name",
    "Product": "name",
    "Quote": "name",
}

_NUMERIC_FIELD_TYPES = (
    IntegerField,
    BigIntegerField,
    SmallIntegerField,
    PositiveIntegerField,
    PositiveSmallIntegerField,
    FloatField,
    DJDecimalField,
)


def get_single_record_payload(user, request_payload: Dict[str, Union[str, int]]) -> Tuple[str, Optional[Dict[str, object]]]:
    """Fetch a single record and format it for UI consumption."""

    object_name = request_payload.get("object")
    identifier = request_payload.get("identifier")
    record_id = request_payload.get("record_id")
    lookup_field = request_payload.get("lookup_field") or request_payload.get("identifier_field")

    if isinstance(identifier, str):
        identifier = identifier.strip().strip('"').strip("'")

    if not object_name:
        return ("⚠️ I need to know which object you want to open.", None)

    metadata = get_object_metadata(object_name)
    if not metadata:
        return (f"⚠️ I don’t recognize the object <strong>{object_name}</strong>.", None)

    model = metadata["model"]
    custom_object = metadata["custom_object"]
    custom_fields = metadata["custom_fields"]

    record = None

    if record_id:
        try:
            record = _get_record_by_id(model, record_id, custom_object)
        except model.DoesNotExist:
            record = None

    if record is None:
        if not identifier:
            return ("⚠️ I couldn’t find the record name or identifier to use.", None)
        record = _find_record(model, identifier, lookup_field, custom_object=custom_object)

    if record is None:
        return (
            f"⚠️ I wasn’t able to find a {object_name} record matching <strong>{identifier}</strong>.",
            None,
        )

    payload = serialize_record(record, object_name, custom_object, custom_fields, user=user)
    return ("", payload)


def _find_record(
    model: Model,
    identifier: str,
    lookup_field: Optional[str],
    *,
    custom_object=None,
):
    """Attempt to locate a record by trying multiple lookup fields."""

    queryset = model.objects.all()
    if custom_object:
        queryset = queryset.filter(object_type=custom_object)

    lookup_candidates = []
    if lookup_field:
        lookup_candidates.append(lookup_field)

    model_name = model.__name__
    lookup_candidates.extend(DEFAULT_LOOKUPS.get(model_name, []))

    for field in lookup_candidates:
        field_obj: Optional[Field] = None
        try:
            field_obj = model._meta.get_field(field)
        except FieldDoesNotExist:
            field_obj = None

        # Prefer an exact match first, then fall back to case-insensitive/contains
        filter_attempts = [{field: identifier}]
        if field_obj is None or isinstance(field_obj, (CharField, TextField)):
            filter_attempts.insert(0, {f"{field}__iexact": identifier})
            filter_attempts.append({f"{field}__icontains": identifier})

        try:
            for attempt in filter_attempts:
                record = queryset.filter(**attempt).first()
                if record:
                    return record
        except Exception as exc:
            logger.debug("Lookup field '%s' failed for %s: %s", field, model_name, exc)

    return None


def _get_record_by_id(model: Model, record_id: Union[str, int], custom_object=None):
    filters = {"id": record_id}
    if custom_object:
        filters["object_type"] = custom_object
    return model.objects.get(**filters)


def serialize_record(record: Model, object_name: str, custom_object, custom_fields, *, user=None) -> Dict[str, object]:
    return _serialize_record(record, object_name, custom_object, custom_fields, user=user)


def _serialize_record(record: Model, object_name: str, custom_object, custom_fields, *, user=None) -> Dict[str, object]:
    """Build a normalized payload for front-end rendering."""

    model_name = record.__class__.__name__
    display_label = getattr(custom_object, "label", None) or object_name
    content_type = ContentType.objects.get_for_model(record.__class__)

    standard_fields = _collect_standard_fields(record, model_name)
    custom_field_rows = _collect_custom_fields(record, custom_fields, content_type=content_type)

    all_fields = standard_fields + custom_field_rows

    primary_field_name = PRIMARY_FIELD_MAP.get(model_name)
    primary_value = None
    primary_label = None

    for field in all_fields:
        if field["name"] == (primary_field_name or "name"):
            primary_value = field.get("display_value", field.get("value"))
            primary_label = field["label"]
            break

    if primary_value is None:
        primary_value = getattr(record, "id", None)
        primary_label = "ID"

    default_order = [build_field_key(field["name"], field.get("is_custom"), field.get("field_id")) for field in all_fields]
    layout = _get_saved_layout(user, object_name, default_order)

    return {
        "object": object_name,
        "display_label": display_label,
        "record_label": primary_label,
        "record_value": primary_value,
        "record_id": getattr(record, "id", None),
        "fields": all_fields,
        "related": [],
        "is_custom_object": bool(custom_object),
        "layout": layout,
    }


def build_field_key(name: Optional[str], is_custom: bool, field_id: Optional[int]) -> str:
    base = f"{name or ''}::{'custom' if is_custom else 'standard'}"
    return f"{base}::{field_id or ''}" if is_custom else base


def _get_saved_layout(user, object_name: str, default_order: List[str]) -> Dict[str, List[str]]:
    base = {
        "order": default_order or [],
        "hidden": [],
    }
    if not user or not object_name:
        return base

    try:
        layout_obj = SingleRecordLayout.objects.filter(user=user, object_name=object_name).first()
    except Exception:
        return base

    if not layout_obj or not isinstance(layout_obj.layout, dict):
        return base

    stored_order = layout_obj.layout.get("order")
    stored_hidden = layout_obj.layout.get("hidden")

    order = stored_order if isinstance(stored_order, list) else base["order"]
    hidden = stored_hidden if isinstance(stored_hidden, list) else []

    return {
        "order": order,
        "hidden": hidden,
    }


def _collect_standard_fields(record: Model, model_name: str) -> List[Dict[str, object]]:
    allowed_fields = ALLOWED_FIELDS.get(model_name, [])
    rows: List[Dict[str, object]] = []

    for field_name in allowed_fields:
        try:
            field_obj: Optional[Field] = record._meta.get_field(field_name)
        except FieldDoesNotExist:
            field_obj = None

        value = getattr(record, field_name, None)

        if hasattr(value, "all"):
            related_items = list(value.all())
            formatted_value = ", ".join(str(item) for item in related_items)
            raw_value = [str(item.pk) for item in related_items]
            data_type = "related"
            is_editable = False
        else:
            formatted_value = _format_display_value(value, field_obj)
            raw_value = _coerce_raw_value(value, field_obj)
            data_type = _infer_data_type(field_obj, raw_value)
            is_editable = True if field_obj is None else bool(getattr(field_obj, "editable", True))

        if field_obj is not None and (getattr(field_obj, "auto_now", False) or getattr(field_obj, "auto_now_add", False)):
            is_editable = False

        options = _get_field_options(field_obj)

        rows.append(
            {
                "name": field_name,
                "label": _to_label(field_name),
                "value": formatted_value,
                "display_value": formatted_value,
                "raw_value": raw_value,
                "data_type": data_type,
                "is_custom": False,
                "field_id": None,
                "options": options,
                "is_multiline": isinstance(field_obj, TextField),
                "is_editable": is_editable and data_type != "related",
            }
        )

    return rows


def _collect_custom_fields(record: Model, custom_fields: Iterable, *, content_type: Optional[ContentType] = None) -> List[Dict[str, object]]:
    """Collect custom fields for both CustomRecord and standard objects."""
    if not custom_fields:
        return []

    values_manager = getattr(record, "custom_field_values", None)
    existing_values = {}

    if values_manager is not None:
        try:
            for value_instance in values_manager.all():
                existing_values[value_instance.field_id] = value_instance.value
        except Exception:  # pragma: no cover - defensive guard
            existing_values = {}
    elif content_type is not None:
        try:
            qs = CustomFieldValue.objects.filter(
                content_type=content_type,
                object_id=record.pk,
                field_id__in=[field.id for field in custom_fields],
            )
            for value_instance in qs:
                existing_values[value_instance.field_id] = value_instance.value
        except Exception:
            existing_values = {}

    rows: List[Dict[str, object]] = []
    for field in custom_fields:
        stored_value = existing_values.get(field.id)
        raw_value = _coerce_custom_raw_value(stored_value, field.data_type)
        formatted_value = _format_custom_display_value(raw_value, field.data_type)

        rows.append(
            {
                "name": field.name,
                "label": field.label or _to_label(field.name),
                "value": formatted_value,
                "display_value": formatted_value,
                "raw_value": raw_value,
                "data_type": _map_custom_data_type(field.data_type),
                "is_custom": True,
                "field_id": field.id,
                "options": field.options or [],
                "is_multiline": (field.data_type or "").lower() in {"textarea"},
                "is_editable": True,
            }
        )

    return rows


def _format_display_value(value, field_obj: Optional[Field]):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(field_obj, ForeignKey):
        if value is None:
            return ""
        return getattr(value, "name", str(value))
    if hasattr(value, "__str__"):
        return str(value)
    return str(value)


def _to_label(field_name: str) -> str:
    return field_name.replace("_", " ").strip().title()


def _infer_data_type(field_obj: Optional[Field], raw_value) -> str:
    if field_obj is None:
        if isinstance(raw_value, bool):
            return "boolean"
        if isinstance(raw_value, (list, tuple)):
            return "related"
        return "text"

    choices = getattr(field_obj, "choices", None)
    if choices:
        return "choice"

    if isinstance(field_obj, DJBooleanField):
        return "boolean"
    if isinstance(field_obj, DJDateTimeField):
        return "datetime"
    if isinstance(field_obj, DJDateField):
        return "date"
    if isinstance(field_obj, ForeignKey):
        return "lookup"
    if isinstance(field_obj, _NUMERIC_FIELD_TYPES):
        return "number"
    if isinstance(field_obj, TextField):
        return "text"
    if isinstance(field_obj, CharField):
        return "text"
    return "text"


def _coerce_raw_value(value, field_obj: Optional[Field]):
    if value is None:
        return None
    if isinstance(field_obj, DJBooleanField):
        if value in (None, ""):
            return ""
        return "true" if bool(value) else "false"
    if isinstance(field_obj, DJDateField):
        if isinstance(value, date):
            return value.isoformat()
        return str(value)
    if isinstance(field_obj, DJDateTimeField):
        if isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        return str(value)
    if isinstance(field_obj, DJDecimalField):
        return str(value)
    if isinstance(field_obj, _NUMERIC_FIELD_TYPES):
        return value
    if isinstance(field_obj, ForeignKey):
        if value is None:
            return None
        # Prefer human-readable name/string; fall back to PK if missing
        return getattr(value, "name", None) or getattr(value, "custom_identifier", None) or getattr(value, "email", None) or getattr(value, "id", getattr(value, "pk", None)) or str(value)
    if hasattr(value, "__str__"):
        return str(value)
    return value


def _get_field_options(field_obj: Optional[Field]):
    if not field_obj:
        return []
    if isinstance(field_obj, ForeignKey):
        return _get_lookup_options(field_obj)
    choices = getattr(field_obj, "choices", None)
    if not choices:
        return []
    return [
        {"value": choice_value, "label": str(choice_label)}
        for choice_value, choice_label in choices
    ]


def _get_lookup_options(field_obj: ForeignKey, limit: int = 50):
    try:
        model = field_obj.related_model
    except Exception:
        return []

    try:
        qs = model.objects.all()[:limit]
    except Exception:
        return []

    options = []
    for obj in qs:
        label = getattr(obj, "name", None) or getattr(obj, "custom_identifier", None) or getattr(obj, "email", None) or str(obj)
        if label is None:
            continue
        options.append({"value": label, "label": label})
    return options


def _coerce_custom_raw_value(value: Optional[str], data_type: Optional[str]):
    if value is None:
        return None
    data_type = (data_type or "").lower()
    if data_type == "number":
        try:
            return Decimal(value)
        except (ArithmeticError, ValueError, TypeError):
            return value
    if data_type == "boolean":
        lowered = str(value).strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
        return None
    if data_type == "date":
        parsed = parse_date(value)
        return parsed.isoformat() if parsed else value
    if data_type == "datetime":
        parsed = parse_datetime(value)
        return parsed.isoformat(timespec="seconds") if parsed else value
    return value


def _format_custom_display_value(value, data_type: Optional[str]):
    if value is None:
        return ""
    data_type = (data_type or "").lower()
    if data_type == "boolean":
        if isinstance(value, bool):
            return "Yes" if value else "No"
        lowered = str(value).lower()
        if lowered in {"true", "1", "yes"}:
            return "Yes"
        if lowered in {"false", "0", "no"}:
            return "No"
    return str(value)


def _map_custom_data_type(data_type: Optional[str]) -> str:
    mapping = {
        "text": "text",
        "textarea": "text",
        "number": "number",
        "date": "date",
        "datetime": "datetime",
        "boolean": "boolean",
        "dropdown": "choice",
        "lookup": "lookup",
    }
    return mapping.get((data_type or "").lower(), "text")


def update_record_field(
    record: Model,
    object_name: str,
    field_name: str,
    new_value,
    *,
    data_type: Optional[str],
    is_custom: bool,
    field_id: Optional[int],
    custom_fields: Iterable,
    user=None,
) -> Tuple[bool, str]:
    if is_custom:
        custom_field = None
        for field in custom_fields:
            if field.id == field_id:
                custom_field = field
                break
        if not custom_field:
            return False, f"Custom field not found for id {field_id}."

        return _update_custom_field_value(record, custom_field, new_value)

    try:
        field_obj = record._meta.get_field(field_name)
    except FieldDoesNotExist:
        return False, f"Field '{field_name}' does not exist on {object_name}."

    if not getattr(field_obj, "editable", True):
        return False, f"Field '{field_name}' cannot be edited."

    return _update_standard_field_value(record, field_obj, field_name, new_value, data_type)


def _update_standard_field_value(record: Model, field_obj: Field, field_name: str, new_value, data_type: Optional[str]) -> Tuple[bool, str]:
    try:
        coerced_value = _deserialize_input_value(field_obj, new_value, data_type)
    except ValueError as exc:
        return False, str(exc)

    try:
        if isinstance(field_obj, ForeignKey):
            related_model = field_obj.related_model
            if coerced_value in (None, ""):
                setattr(record, field_name, None)
            else:
                related_instance = _resolve_related_instance(related_model, coerced_value)
                if related_instance is None:
                    return False, f"Related record not found for value '{coerced_value}'."
                setattr(record, field_name, related_instance)
        else:
            setattr(record, field_name, coerced_value)

        record.save(update_fields=[field_name])
    except Exception as exc:
        logger.exception("Error updating field %s on %s", field_name, record.__class__.__name__)
        return False, f"Failed to update field '{field_name}': {exc}"

    return True, f"{SUCCESS_ICON} {field_name.replace('_', ' ').title()} updated successfully."


def _deserialize_input_value(field_obj: Field, new_value, data_type: Optional[str]):
    if new_value in ("", None):
        if getattr(field_obj, "null", False):
            return None
        if isinstance(field_obj, (DJBooleanField, DJDateField, DJDateTimeField)):
            return None
        return ""

    inferred_type = data_type or _infer_data_type(field_obj, new_value)

    if isinstance(field_obj, DJBooleanField) or inferred_type == "boolean":
        if isinstance(new_value, bool):
            return new_value
        lowered = str(new_value).strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
        raise ValueError(f"Invalid boolean value '{new_value}'.")

    if isinstance(field_obj, DJDateField) or inferred_type == "date":
        parsed = parse_date(str(new_value))
        if parsed is None:
            raise ValueError(f"Invalid date value '{new_value}'. Expected YYYY-MM-DD.")
        return parsed

    if isinstance(field_obj, DJDateTimeField) or inferred_type == "datetime":
        parsed_dt = parse_datetime(str(new_value))
        if parsed_dt is None:
            raise ValueError(f"Invalid datetime value '{new_value}'. Expected ISO format.")
        return parsed_dt

    if isinstance(field_obj, DJDecimalField):
        try:
            return Decimal(str(new_value))
        except (ArithmeticError, ValueError) as exc:
            raise ValueError(f"Invalid decimal value '{new_value}'.") from exc

    if isinstance(field_obj, _NUMERIC_FIELD_TYPES):
        try:
            if isinstance(field_obj, FloatField):
                return float(new_value)
            return int(str(new_value)) if str(new_value).isdigit() else float(new_value)
        except ValueError as exc:
            raise ValueError(f"Invalid numeric value '{new_value}'.") from exc

    return str(new_value)


def _resolve_related_instance(model, value):
    try:
        return model.objects.get(pk=value)
    except (model.DoesNotExist, ValueError, TypeError):
        pass

    lookup_candidates = []
    if hasattr(model, "name"):
        lookup_candidates.append({"name__iexact": value})
        lookup_candidates.append({"name": value})
    if hasattr(model, "custom_identifier"):
        lookup_candidates.append({"custom_identifier__iexact": value})
    if hasattr(model, "email"):
        lookup_candidates.append({"email__iexact": value})

    for filters in lookup_candidates:
        try:
            return model.objects.get(**filters)
        except model.DoesNotExist:
            continue

    return None


def _update_custom_field_value(record: Model, custom_field, new_value) -> Tuple[bool, str]:
    data_type = (custom_field.data_type or "").lower()

    if new_value in (None, ""):
        coerced_value = ""
    elif data_type == "number":
        try:
            coerced_value = str(Decimal(str(new_value)))
        except (ArithmeticError, ValueError) as exc:
            return False, f"Invalid number '{new_value}' for custom field."
    elif data_type == "boolean":
        lowered = str(new_value).strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            coerced_value = "true"
        elif lowered in {"false", "0", "no", "n"}:
            coerced_value = "false"
        else:
            return False, f"Invalid boolean '{new_value}' for custom field."
    else:
        coerced_value = str(new_value)

    values_manager = getattr(record, "custom_field_values", None)
    value_instance = None

    if values_manager is not None:
        value_instance = values_manager.filter(field=custom_field).first()
    else:
        try:
            content_type = ContentType.objects.get_for_model(record.__class__)
            value_instance = CustomFieldValue.objects.filter(
                field=custom_field,
                content_type=content_type,
                object_id=record.pk,
            ).first()
        except Exception:
            value_instance = None

    if value_instance:
        value_instance.value = coerced_value
        value_instance.save()
        return True, f"{SUCCESS_ICON} {custom_field.label or custom_field.name} updated successfully."

    try:
        CustomFieldValue.objects.create(
            field=custom_field,
            record=record if values_manager is not None else None,
            content_type=None if values_manager is not None else ContentType.objects.get_for_model(record.__class__),
            object_id=None if values_manager is not None else record.pk,
            value=coerced_value,
        )
    except Exception as exc:
        logger.exception("Failed to store custom field value for %s", record)
        return False, f"Failed to save custom field: {exc}"

    return True, f"{SUCCESS_ICON} {custom_field.label or custom_field.name} updated successfully."
