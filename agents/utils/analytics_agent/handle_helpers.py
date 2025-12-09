from decimal import Decimal, InvalidOperation
from datetime import datetime, date, timedelta

from django.core.exceptions import FieldError
from django.db.models import ForeignKey, OuterRef, Subquery, Q, Sum, Avg, Count, Min, Max, CharField, TextField
from django.db.models.functions import Cast
from django.db.models import DecimalField, DateField
from django.db.models.functions import TruncMonth, TruncWeek, TruncDay
from django.utils.dateparse import parse_date
from django.utils.timezone import now
from dateutil.relativedelta import relativedelta

from cpq.models import (
    Product,
    Lead,
    Account,
    Contact,
    Opportunity,
    Quote,
    CustomObject,
    CustomRecord,
    CustomField,
    CustomFieldValue,
)


BASE_MODEL_MAP = {
    "Product": Product,
    "Lead": Lead,
    "Account": Account,
    "Contact": Contact,
    "Opportunity": Opportunity,
    "Quote": Quote,
}

TEXT_LIKE_TYPES = {"text", "textarea", "dropdown", "lookup"}
NUMERIC_TYPES = {"number"}
DATE_TYPES = {"date"}
BOOLEAN_TYPES = {"boolean"}

def get_object_metadata(object_name):
    base_model = BASE_MODEL_MAP.get(object_name)
    if base_model:
        custom_fields = list(
            CustomField.objects.filter(object_type=object_name, custom_object__isnull=True)
        )
        return {
            "model": base_model,
            "custom_object": None,
            "custom_fields": custom_fields,
        }

    try:
        custom_object = CustomObject.objects.prefetch_related("custom_fields").get(name=object_name)
    except CustomObject.DoesNotExist:
        return None

    return {
        "model": CustomRecord,
        "custom_object": custom_object,
        "custom_fields": list(custom_object.custom_fields.all()),
    }


def handle_show_metrics(user, completed_metrics):
    response_message = ""
    results = {}
    object_labels = {}

    for metric in completed_metrics:
        object_name = metric.get("object")
        conditions = metric.get("conditions", [])
        aggregate = metric.get("aggregate") if isinstance(metric.get("aggregate"), dict) else None
        if aggregate:
            rng = aggregate.get("range")
            if not rng or rng in ("custom", "", None):
                aggregate["range"] = "this_year"

        if (not object_name) and conditions:
            first_condition = conditions[0]
            raw_field = first_condition.get("field")
            raw_value = first_condition.get("value")

            if raw_field and raw_value:
                lowered_field = str(raw_field).lower()
                lowered_value = str(raw_value).lower()

                if lowered_field in {"product", "product_sku", "product_name", "sku", "name"}:
                    object_name = "Product"
                    first_condition["field"] = "sku"
                    first_condition["value"] = raw_value

        object_name = object_name or metric.get("object")
        method = metric.get("method", "read")
        limit = metric.get("limit", 100)
        try:
            limit = int(limit) if limit is not None else 100
        except (TypeError, ValueError):
            limit = 100
        conditions = metric.get("conditions", [])
        sort = metric.get("sort", None)

        if not object_name:
            response_message += "⚠️ Missing object name in metrics request.<br>"
            continue

        metadata = get_object_metadata(object_name)
        if not metadata:
            response_message += f"⚠️ Unknown object '{object_name}'.<br>"
            continue

        if method != "read":
            response_message += f"⚠️ Unsupported method '{method}' for {object_name}.<br>"
            continue

        model = metadata["model"]
        custom_object = metadata["custom_object"]
        custom_fields = metadata["custom_fields"]

        if custom_object:
            qs = model.objects.filter(object_type=custom_object).prefetch_related(
                "custom_field_values__field",
                "created_by",
                "updated_by",
            )
        else:
            qs = model.objects.all()

        display_name = (custom_object.label or custom_object.name) if custom_object else object_name
        object_labels[object_name] = display_name

        filters = {}
        exclude_filters = {}
        all_conditions_valid = True

        custom_field_lookup = {}
        if custom_object:
            for field in custom_fields:
                custom_field_lookup[field.name.lower()] = field
                if field.label:
                    custom_field_lookup[field.label.lower()] = field

        for cond in conditions:
            field = cond.get("field")
            operator = cond.get("operator")
            value = cond.get("value")

            if not field or not operator:
                continue

            custom_field = None
            if custom_object and isinstance(field, str):
                custom_field = custom_field_lookup.get(field.lower())

            # Special handling for Product SKU/Name overlap
            if (
                not custom_field
                and object_name == "Product"
                and isinstance(field, str)
                and isinstance(value, str)
            ):
                lowered_field = field.lower()
                if lowered_field in {"name", "product", "product_name", "product_sku", "sku"}:
                    operator_lower = operator.lower()
                    if operator_lower in {"equals", "contains", "starts_with", "ends_with"}:
                        lookup_map = {
                            "equals": ("iexact", "iexact"),
                            "contains": ("icontains", "icontains"),
                            "starts_with": ("istartswith", "istartswith"),
                            "ends_with": ("iendswith", "iendswith"),
                        }
                        name_lookup, sku_lookup = lookup_map[operator_lower]
                        condition_q = Q(**{f"name__{name_lookup}": value}) | Q(**{f"sku__{sku_lookup}": value})
                        qs = qs.filter(condition_q)
                        continue

            if custom_field:
                success, error_msg, qs = apply_custom_field_condition(qs, custom_field, operator, value)
                if not success:
                    response_message += (
                        f"⚠️ Condition failed for {object_name}: "
                        f"field='{field}', operator='{operator}', value='{value}'. "
                        f"Error: {error_msg}. Skipping this object.<br>"
                    )
                    all_conditions_valid = False
                    break
            else:
                supported, error_msg = apply_operator(field, operator, value, filters, exclude_filters, model=model)
                if not supported:
                    response_message += (
                        f"⚠️ Condition failed for {object_name}: "
                        f"field='{field}', operator='{operator}', value='{value}'. "
                        f"Error: {error_msg}. Skipping this object.<br>"
                    )
                    all_conditions_valid = False
                    break

        if not all_conditions_valid:
            continue

        if filters:
            qs = qs.filter(**filters)
        if exclude_filters:
            qs = qs.exclude(**exclude_filters)

        qs = qs.distinct()

        order_applied = False
        if sort and sort.get("field"):
            sort_field = sort.get("field")
            user_order = (sort.get("order") or "").lower()

            custom_sort_field = None
            if custom_object and isinstance(sort_field, str):
                custom_sort_field = custom_field_lookup.get(sort_field.lower())

            if custom_sort_field:
                qs, sort_error = apply_custom_field_sort(qs, custom_sort_field, user_order)
                if sort_error:
                    response_message += f"⚠️ Unable to sort {object_name} by '{sort_field}': {sort_error}.<br>"
                    continue
                order_applied = True
            else:
                order_expression = sort_field
                if not user_order or user_order == "desc":
                    order_expression = f"-{order_expression}"
                try:
                    qs = qs.order_by(order_expression)
                    order_applied = True
                except FieldError as exc:
                    response_message += f"⚠️ Unable to sort {object_name} by '{sort_field}': {exc}.<br>"
                    continue

        if not order_applied and hasattr(model, "created_at"):
            qs = qs.order_by("-created_at")

        if aggregate:
            agg_payload, agg_error = execute_aggregate(qs, aggregate, model, object_name)
            if agg_error:
                response_message += f"⚠️ Aggregate failed for {display_name}: {agg_error}.<br>"
                continue
            results[object_name] = {"aggregate": agg_payload}
            # Build a short human-friendly note
            if agg_payload.get("series"):
                response_message += f"📈 {display_name} {agg_payload.get('function')}({agg_payload.get('field')}) over {agg_payload.get('range') or 'all time'} with {len(agg_payload['series'])} points.<br>"
            else:
                response_message += f"📈 {display_name} {agg_payload.get('function')}({agg_payload.get('field')}) = {agg_payload.get('value')}.<br>"
            continue

        if limit:
            qs = qs[:limit]

        serialized = safe_serialize_queryset(qs, object_name, custom_object=custom_object, custom_fields=custom_fields)
        record_count = len(serialized)

        results[object_name] = serialized
        response_message += f"📊 Retrieved {record_count} {display_name}(s).<br>"

    return response_message, results, object_labels


def _apply_date_range(qs, date_field, range_key):
    if not range_key or range_key == "null":
        return qs

    now_dt = now()
    start = None
    end = now_dt

    # Explicit start/end tuple
    if isinstance(range_key, (list, tuple)) and len(range_key) == 2:
        start, end = range_key
        return qs.filter(**{f"{date_field}__gte": start, f"{date_field}__lte": end})

    # Named ranges
    if range_key == "last_3_months":
        start = (now_dt - relativedelta(months=3)).replace(day=1)
    elif range_key == "last_month":
        first_this_month = now_dt.replace(day=1)
        start = (first_this_month - relativedelta(months=1)).replace(day=1)
        end = first_this_month
    elif range_key == "last_90_days":
        start = now_dt - timedelta(days=90)
    elif range_key == "this_year":
        start = now_dt.replace(month=1, day=1)
        end = now_dt.replace(month=12, day=31)
    elif range_key == "next_year":
        next_year = now_dt.year + 1
        start = now_dt.replace(year=next_year, month=1, day=1)
        end = now_dt.replace(year=next_year, month=12, day=31)
    elif range_key == "this_month":
        start = now_dt.replace(day=1)
        end = (start + relativedelta(months=1)) - timedelta(days=1)
    elif range_key in {"three_months", "3_months"}:
        start = (now_dt - relativedelta(months=3)).replace(day=1)
    elif range_key in {"six_months", "6_months"}:
        start = (now_dt - relativedelta(months=6)).replace(day=1)
    elif range_key in {"nine_months", "9_months"}:
        start = (now_dt - relativedelta(months=9)).replace(day=1)
    elif range_key in {"twelve_months", "12_months"}:
        start = (now_dt - relativedelta(months=12)).replace(day=1)

    if start:
        return qs.filter(**{f"{date_field}__gte": start, f"{date_field}__lte": end})
    return qs


def execute_aggregate(qs, aggregate_def, model, object_name):
    """
    Execute aggregate functions with optional date range and time bucketing.
    Returns (payload, error).
    """
    if not aggregate_def:
        return None, "missing aggregate definition"

    func_name = (aggregate_def.get("function") or "sum").lower()
    field = aggregate_def.get("field")
    group_by = (aggregate_def.get("group_by") or "").lower()
    date_field = aggregate_def.get("date_field") or ("updated_at" if hasattr(model, "updated_at") else None)
    range_key = aggregate_def.get("range")

    if not field:
        return None, "aggregate field is required"

    agg_map = {
        "sum": Sum,
        "count": Count,
        "avg": Avg,
        "average": Avg,
        "min": Min,
        "max": Max,
    }
    agg_fn = agg_map.get(func_name)
    if not agg_fn:
        return None, f"unsupported aggregate function '{func_name}'"

    if range_key and date_field:
        qs = _apply_date_range(qs, date_field, range_key)

    # Time bucketed series
    if group_by in {"month", "week", "day"} and date_field:
        trunc_map = {
            "month": TruncMonth,
            "week": TruncWeek,
            "day": TruncDay,
        }
        trunc_fn = trunc_map.get(group_by)
        if not trunc_fn:
            return None, f"unsupported group_by '{group_by}'"

        qs = qs.annotate(period=trunc_fn(date_field))
        aggregated = qs.values("period").annotate(value=agg_fn(field)).order_by("period")

        series = []
        for entry in aggregated:
            period_val = entry.get("period")
            if period_val is None:
                continue
            # period might be datetime/date; normalize to ISO date
            if hasattr(period_val, "date"):
                period_str = period_val.date().isoformat()
            else:
                period_str = str(period_val)
            val = entry.get("value")
            series.append({
                "period": period_str,
                "value": float(val) if val is not None else None,
            })

        total_value = sum([item.get("value") or 0 for item in series])
        return {
            "function": func_name,
            "field": field,
            "group_by": group_by,
            "date_field": date_field,
            "range": range_key,
            "series": series,
            "total": float(total_value) if total_value is not None else None,
        }, None

    # Simple aggregate
    agg_value = qs.aggregate(value=agg_fn(field)).get("value")
    return {
        "function": func_name,
        "field": field,
        "date_field": date_field,
        "range": range_key,
        "value": float(agg_value) if agg_value is not None else None,
    }, None


def apply_operator(field, operator, value, filters, exclude_filters, model=None):
    """
    Aplica un operador específico y actualiza filters/exclude_filters.
    Resuelve automáticamente ForeignKeys si se pasa un string.
    Retorna (True, "") si el operador es soportado,
    o (False, mensaje_error) si falla.
    """
    # --- Automatically resolve ForeignKeys and normalize string comparisons ---
    field_obj = None
    if model:
        try:
            field_obj = model._meta.get_field(field)
            if isinstance(field_obj, ForeignKey) and isinstance(value, str):
                rel_model = field_obj.related_model
                lookup_field = 'username' if hasattr(rel_model, 'username') else 'name'
                try:
                    related_obj = rel_model.objects.get(**{lookup_field: value})
                    value = related_obj.pk
                except rel_model.DoesNotExist:
                    return False, f"related object with {lookup_field}='{value}' does not exist"
        except Exception as e:
            return False, f"field '{field}' does not exist or is invalid"

    # Normalize Opportunity.stage values (stored lowercase, no spaces)
    if model and model.__name__ == "Opportunity" and field == "stage" and isinstance(value, str):
        value = value.strip().lower().replace(" ", "")

    def _is_text_field():
        return isinstance(field_obj, (CharField, TextField)) if field_obj else False

    # Normalize common date range keywords to explicit ranges
    def _resolve_date_range(val):
        """
        Accepts:
        - string keywords: this_year, this_month, three_months, six_months, nine_months, twelve_months, 3_months, 6_months, 9_months, 12_months
        - list/tuple of two ISO dates
        - dict with start_date/end_date
        Returns (start, end) or None
        """
        now_dt = now()
        if isinstance(val, str):
            key = val.strip().lower()
            if key == "this_year":
                return now_dt.replace(month=1, day=1), now_dt.replace(month=12, day=31)
            if key == "next_year":
                next_year = now_dt.year + 1
                return now_dt.replace(year=next_year, month=1, day=1), now_dt.replace(year=next_year, month=12, day=31)
            if key == "this_month":
                start = now_dt.replace(day=1)
                end = (start + relativedelta(months=1)) - timedelta(days=1)
                return start, end
            if key in {"three_months", "3_months"}:
                return (now_dt - relativedelta(months=3)).replace(day=1), now_dt
            if key in {"six_months", "6_months"}:
                return (now_dt - relativedelta(months=6)).replace(day=1), now_dt
            if key in {"nine_months", "9_months"}:
                return (now_dt - relativedelta(months=9)).replace(day=1), now_dt
            if key in {"twelve_months", "12_months"}:
                return (now_dt - relativedelta(months=12)).replace(day=1), now_dt

        if isinstance(val, (list, tuple)) and len(val) == 2:
            start_raw, end_raw = val[0], val[1]
            try:
                start_dt = parse_date(str(start_raw))
                end_dt = parse_date(str(end_raw))
            except Exception:
                start_dt = end_dt = None

            # If it's a full-year range but not the current year, reinterpret as current year
            if start_dt and end_dt:
                if start_dt.month == 1 and start_dt.day == 1 and end_dt.month == 12 and end_dt.day in (31, 30):
                    current_start = now_dt.replace(month=1, day=1)
                    current_end = now_dt.replace(month=12, day=31)
                    return current_start, current_end
                return start_raw, end_raw
            return start_raw, end_raw

        if isinstance(val, dict):
            start = val.get("start_date") or val.get("start")
            end = val.get("end_date") or val.get("end")
            if start and end:
                return start, end
        return None

    # Operators dictionary
    operator_funcs = {
        "equals": lambda f, v: filters.update({f"{f}__iexact": v}) if _is_text_field() and isinstance(v, str) else filters.update({f"{f}__exact": v}),
        "not_equals": lambda f, v: exclude_filters.update({f"{f}__iexact": v}) if _is_text_field() and isinstance(v, str) else exclude_filters.update({f"{f}__exact": v}),
        "contains": lambda f, v: filters.update({f"{f}__icontains": v}),
        "starts_with": lambda f, v: filters.update({f"{f}__istartswith": v}),
        "ends_with": lambda f, v: filters.update({f"{f}__iendswith": v}),
        "greater_than": lambda f, v: filters.update({f"{f}__gt": v}),
        "greater_or_equal": lambda f, v: filters.update({f"{f}__gte": v}),
        "less_than": lambda f, v: filters.update({f"{f}__lt": v}),
        "less_or_equal": lambda f, v: filters.update({f"{f}__lte": v}),
        "before_date": lambda f, v: filters.update({f"{f}__lt": v}),
        "after_date": lambda f, v: filters.update({f"{f}__gt": v}),
        "in": lambda f, v: filters.update({f"{f}__in": v if isinstance(v, list) else [v]}),
        "not_in": lambda f, v: exclude_filters.update({f"{f}__in": v if isinstance(v, list) else [v]}),
        "is_true": lambda f, v: filters.update({f: True}),
        "is_false": lambda f, v: filters.update({f: False}),
        "within_last": lambda f, v: filters.update({
            f"{f}__gte": now() - timedelta(**(v if isinstance(v, dict) else {"days": int(v)}))
        }),
        "within_range": lambda f, v: filters.update({
            f"{f}__gte": _resolve_date_range(v)[0], f"{f}__lte": _resolve_date_range(v)[1]
        }) if _resolve_date_range(v) else None,
    }

    func = operator_funcs.get(operator)
    if not func:
        return False, f"unsupported operator '{operator}'"

    func(field, value)
    return True, ""


def apply_custom_field_condition(qs, custom_field, operator, value):
    data_type = (custom_field.data_type or "").lower()
    values_qs = CustomFieldValue.objects.filter(field=custom_field)

    def include_records(filtered_qs):
        return qs.filter(id__in=filtered_qs.values_list("record_id", flat=True)).distinct()

    def exclude_records(filtered_qs):
        return qs.exclude(id__in=filtered_qs.values_list("record_id", flat=True)).distinct()

    try:
        if data_type in TEXT_LIKE_TYPES:
            if operator == "equals":
                updated_qs = include_records(values_qs.filter(value__iexact=str(value)))
            elif operator == "not_equals":
                updated_qs = exclude_records(values_qs.filter(value__iexact=str(value)))
            elif operator == "contains":
                updated_qs = include_records(values_qs.filter(value__icontains=str(value)))
            elif operator == "starts_with":
                updated_qs = include_records(values_qs.filter(value__istartswith=str(value)))
            elif operator == "ends_with":
                updated_qs = include_records(values_qs.filter(value__iendswith=str(value)))
            elif operator == "in":
                if not isinstance(value, (list, tuple)):
                    value = [value]
                normalized = [str(item) for item in value]
                updated_qs = include_records(values_qs.filter(value__in=normalized))
            elif operator == "not_in":
                if not isinstance(value, (list, tuple)):
                    value = [value]
                normalized = [str(item) for item in value]
                updated_qs = exclude_records(values_qs.filter(value__in=normalized))
            else:
                return False, f"operator '{operator}' not supported for data type '{data_type}'", qs

            return True, "", updated_qs

        if data_type in NUMERIC_TYPES:
            values_qs = values_qs.annotate(value_cast=Cast("value", output_field=DecimalField(max_digits=30, decimal_places=10)))
            values_qs = values_qs.filter(value_cast__isnull=False)

            def to_decimal(item):
                return Decimal(str(item))

            if operator == "equals":
                updated_qs = include_records(values_qs.filter(value_cast=to_decimal(value)))
            elif operator == "not_equals":
                updated_qs = exclude_records(values_qs.filter(value_cast=to_decimal(value)))
            elif operator == "greater_than":
                updated_qs = include_records(values_qs.filter(value_cast__gt=to_decimal(value)))
            elif operator == "greater_or_equal":
                updated_qs = include_records(values_qs.filter(value_cast__gte=to_decimal(value)))
            elif operator == "less_than":
                updated_qs = include_records(values_qs.filter(value_cast__lt=to_decimal(value)))
            elif operator == "less_or_equal":
                updated_qs = include_records(values_qs.filter(value_cast__lte=to_decimal(value)))
            elif operator == "within_range":
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    return False, "within_range expects two numeric values", qs
                lower = to_decimal(value[0])
                upper = to_decimal(value[1])
                updated_qs = include_records(values_qs.filter(value_cast__gte=lower, value_cast__lte=upper))
            elif operator == "in":
                if not isinstance(value, (list, tuple)):
                    value = [value]
                decimals = [to_decimal(item) for item in value]
                updated_qs = include_records(values_qs.filter(value_cast__in=decimals))
            elif operator == "not_in":
                if not isinstance(value, (list, tuple)):
                    value = [value]
                decimals = [to_decimal(item) for item in value]
                updated_qs = exclude_records(values_qs.filter(value_cast__in=decimals))
            else:
                return False, f"operator '{operator}' not supported for data type '{data_type}'", qs

            return True, "", updated_qs

        if data_type in DATE_TYPES:
            values_qs = values_qs.annotate(value_cast=Cast("value", output_field=DateField()))
            values_qs = values_qs.filter(value_cast__isnull=False)

            def to_date(item):
                if isinstance(item, datetime):
                    return item.date()
                if isinstance(item, date):
                    return item
                if isinstance(item, str):
                    parsed = parse_date(item)
                    if parsed:
                        return parsed
                raise ValueError(f"invalid date value '{item}'")

            if operator == "equals":
                updated_qs = include_records(values_qs.filter(value_cast=to_date(value)))
            elif operator == "not_equals":
                updated_qs = exclude_records(values_qs.filter(value_cast=to_date(value)))
            elif operator in {"greater_than", "after_date"}:
                updated_qs = include_records(values_qs.filter(value_cast__gt=to_date(value)))
            elif operator == "greater_or_equal":
                updated_qs = include_records(values_qs.filter(value_cast__gte=to_date(value)))
            elif operator in {"less_than", "before_date"}:
                updated_qs = include_records(values_qs.filter(value_cast__lt=to_date(value)))
            elif operator == "less_or_equal":
                updated_qs = include_records(values_qs.filter(value_cast__lte=to_date(value)))
            elif operator == "within_range":
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    return False, "within_range expects two date values", qs
                lower = to_date(value[0])
                upper = to_date(value[1])
                updated_qs = include_records(values_qs.filter(value_cast__gte=lower, value_cast__lte=upper))
            elif operator == "within_last":
                if isinstance(value, dict):
                    delta_kwargs = {k: int(v) for k, v in value.items()}
                else:
                    delta_kwargs = {"days": int(value)}
                starting_point = now().date() - timedelta(**delta_kwargs)
                updated_qs = include_records(values_qs.filter(value_cast__gte=starting_point))
            elif operator == "in":
                if not isinstance(value, (list, tuple)):
                    value = [value]
                parsed = [to_date(item) for item in value]
                updated_qs = include_records(values_qs.filter(value_cast__in=parsed))
            elif operator == "not_in":
                if not isinstance(value, (list, tuple)):
                    value = [value]
                parsed = [to_date(item) for item in value]
                updated_qs = exclude_records(values_qs.filter(value_cast__in=parsed))
            else:
                return False, f"operator '{operator}' not supported for data type '{data_type}'", qs

            return True, "", updated_qs

        if data_type in BOOLEAN_TYPES:
            def to_bool(item):
                if isinstance(item, bool):
                    return item
                if isinstance(item, str) and item.lower() in {"true", "false"}:
                    return item.lower() == "true"
                raise ValueError(f"invalid boolean value '{item}'")

            if operator == "equals":
                target = "True" if to_bool(value) else "False"
                updated_qs = include_records(values_qs.filter(value__iexact=target))
            elif operator == "not_equals":
                target = "True" if to_bool(value) else "False"
                updated_qs = exclude_records(values_qs.filter(value__iexact=target))
            elif operator == "is_true":
                updated_qs = include_records(values_qs.filter(value__iexact="True"))
            elif operator == "is_false":
                updated_qs = include_records(values_qs.filter(value__iexact="False"))
            elif operator == "in":
                if not isinstance(value, (list, tuple)):
                    value = [value]
                normalized = ["True" if to_bool(item) else "False" for item in value]
                updated_qs = include_records(values_qs.filter(value__in=normalized))
            elif operator == "not_in":
                if not isinstance(value, (list, tuple)):
                    value = [value]
                normalized = ["True" if to_bool(item) else "False" for item in value]
                updated_qs = exclude_records(values_qs.filter(value__in=normalized))
            else:
                return False, f"operator '{operator}' not supported for data type '{data_type}'", qs

            return True, "", updated_qs

        return False, f"unsupported data type '{custom_field.data_type}'", qs

    except (InvalidOperation, ValueError, TypeError) as exc:
        return False, str(exc), qs


def apply_custom_field_sort(qs, custom_field, order):
    data_type = (custom_field.data_type or "").lower()
    annotation_name = f"cf_sort_{custom_field.id}"

    value_qs = CustomFieldValue.objects.filter(field=custom_field, record=OuterRef("pk"))

    if data_type in NUMERIC_TYPES:
        value_qs = value_qs.annotate(value_cast=Cast("value", output_field=DecimalField(max_digits=30, decimal_places=10)))
        subquery = value_qs.values("value_cast")[:1]
    elif data_type in DATE_TYPES:
        value_qs = value_qs.annotate(value_cast=Cast("value", output_field=DateField()))
        subquery = value_qs.values("value_cast")[:1]
    else:
        subquery = value_qs.values("value")[:1]

    qs = qs.annotate(**{annotation_name: Subquery(subquery)})

    order = (order or "desc").lower()
    order_field = f"-{annotation_name}" if order == "desc" else annotation_name
    qs = qs.order_by(order_field, "id")
    return qs, None


def _format_user(user):
    if not user:
        return None
    if hasattr(user, "get_full_name"):
        full_name = user.get_full_name()
        if full_name:
            return full_name
    return getattr(user, "username", str(user))


def serialize_value(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        try:
            return float(value)
        except (TypeError, ValueError):
            return str(value)
    return value


def serialize_custom_records(qs, custom_object, custom_fields):
    field_names = [field.name for field in custom_fields]
    serialized = []

    for record in qs:
        row = {
            "id": record.id,
            "custom_identifier": record.custom_identifier,
            "record_id": str(record.record_id) if record.record_id else None,
            "created_at": serialize_value(record.created_at),
            "updated_at": serialize_value(record.updated_at),
            "created_by": _format_user(record.created_by),
            "updated_by": _format_user(record.updated_by),
        }

        values_map = {}
        related_values = getattr(record, "custom_field_values", None)
        if related_values is not None:
            for value_instance in related_values.all():
                field = value_instance.field
                if field and field.name in field_names:
                    values_map[field.name] = value_instance.value

        for field_name in field_names:
            row[field_name] = serialize_value(values_map.get(field_name))

        serialized.append(row)

    return serialized


from datetime import datetime, date
from django.db.models import ForeignKey

# Allowed fields per model
ALLOWED_FIELDS = {
    "Lead": ["first_name", "last_name", "phone", "email", "source", "contact", "status", "notes", "assigned_to", "created_at", "activities"],
    "Product": ["name", "sku", "price", "fixed_price", "price_mode", "is_subscription", "term", "is_bundle", "family", "created_at", "description"],
    "Account": ["name", "industry", "website", "phone", "street", "city", "state", "zip_code"],
    "Contact": ["first_name", "last_name", "email", "phone", "company", "job_title", "notes", "account", "is_primary"],
    "Opportunity": ["name", "account", "amount", "stage", "expected_close_date", "primary_quote"],
    "Quote": ["name", "account", "opportunity", "subtotal", "net_amount", "tax_percentage", "tax_amount", "status",
              "discount_percentage", "discount_amount", "expiration_date", "notes", "created_at"],
    "Activity": ["subject", "activity_type", "status", "due_date"]
}

def safe_serialize_queryset(qs, model_name, custom_object=None, custom_fields=None):
    if custom_object:
        return serialize_custom_records(qs, custom_object, custom_fields or [])

    allowed = ALLOWED_FIELDS.get(model_name, [])
    serialized = []

    for obj in qs:
        record = {}
        for field_name in allowed:
            value = getattr(obj, field_name, None)

            # Serialize ForeignKey as readable name
            field_obj = getattr(obj.__class__, field_name, None)
            if isinstance(field_obj, ForeignKey):
                if value is None:
                    value = None
                elif hasattr(value, "name"):
                    value = value.name
                elif hasattr(value, "first_name") and hasattr(value, "last_name"):
                    value = f"{value.first_name} {value.last_name}".strip()
                elif hasattr(value, "email"):
                    value = value.email
                else:
                    value = str(value.pk)

            # Serialize RelatedManager (reverse FK or M2M)
            elif hasattr(value, "all"):
                related_list = []
                for rel_obj in value.all():
                    rel_model = rel_obj.__class__.__name__
                    rel_allowed = ALLOWED_FIELDS.get(rel_model, [])
                    rel_data = {}
                    for f in rel_allowed:
                        v = getattr(rel_obj, f, None)
                        # Convert related object FKs to string
                        f_obj = getattr(rel_obj.__class__, f, None)
                        if isinstance(f_obj, ForeignKey):
                            if v is None:
                                v = None
                            elif hasattr(v, "name"):
                                v = v.name
                            elif hasattr(v, "first_name") and hasattr(v, "last_name"):
                                v = f"{v.first_name} {v.last_name}".strip()
                            elif hasattr(v, "email"):
                                v = v.email
                            else:
                                v = str(v.pk)
                        rel_data[f] = serialize_value(v)
                    related_list.append(rel_data)
                value = related_list

            record[field_name] = serialize_value(value)
        serialized.append(record)
    return serialized
