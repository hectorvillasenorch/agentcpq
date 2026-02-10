from decimal import Decimal, InvalidOperation
from datetime import datetime, date, timedelta

import difflib
import json
import re
import unicodedata

from django.apps import apps
from django.core.exceptions import FieldError
from django.db.models import ForeignKey, OuterRef, Subquery, Q, Sum, Avg, Count, Min, Max, CharField, TextField
from django.db.models.functions import Cast, Coalesce
from django.db.models import DecimalField, DateField, DateTimeField
from django.db import models
from django.db.models.functions import TruncMonth, TruncWeek, TruncDay
from django.utils.dateparse import parse_date
from django.utils.timezone import now
from dateutil.relativedelta import relativedelta
from django.contrib.contenttypes.models import ContentType

from cpq.permissions import apply_partner_access_filter, partner_label_for_user
from cpq.models import (
    Product,
    Lead,
    Account,
    Contact,
    Opportunity,
    Quote,
    Activity,
    Contract,
    Subscription,
    Option,
    Tenant,
    Knowledge,
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
    "Activity": Activity,
    "Contract": Contract,
    "Subscription": Subscription,
    "Option": Option,
    "Tenant": Tenant,
    "Knowledge": Knowledge,
}

TEXT_LIKE_TYPES = {"text", "textarea", "dropdown", "lookup"}
NUMERIC_TYPES = {"number", "currency", "percent"}
DATE_TYPES = {"date", "datetime", "date_time"}
BOOLEAN_TYPES = {"boolean"}


def _normalize_lookup_text(value: str) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

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

    try:
        notes_exists = CustomField.objects.filter(
            custom_object=custom_object,
        ).filter(
            Q(name__iexact="notes") | Q(label__iexact="notes")
        ).exists()
        if not notes_exists:
            CustomField.objects.create(
                label="Notes",
                name="notes",
                crm="AgentCPQ",
                object_type=custom_object.name,
                data_type="textarea",
                required=False,
                custom_object=custom_object,
            )
    except Exception:
        pass

    return {
        "model": CustomRecord,
        "custom_object": custom_object,
        "custom_fields": list(custom_object.custom_fields.all()),
    }


def _normalize_object_token(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"__(c|r|x)$", "", text)
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def resolve_metrics_object_name(raw_object: str) -> str | None:
    if not raw_object:
        return None
    cleaned = str(raw_object).strip()
    if not cleaned:
        return None

    lowered = cleaned.lower()
    lowered = re.sub(r"\b(do|did|does)\s+(i|we|you)\s+have\b", "", lowered)
    lowered = re.sub(r"\b(i|we|you)\s+have\b", "", lowered)
    lowered = re.sub(r"\b(my|our|your|the)\b", "", lowered)
    lowered = re.sub(r"\b(total|overall|currently|right\s+now|in\s+total)\b", "", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    if lowered:
        cleaned = lowered

    alias_map = {
        "deal": "Opportunity",
        "deals": "Opportunity",
        "opp": "Opportunity",
        "opps": "Opportunity",
        "opportunity": "Opportunity",
        "opportunities": "Opportunity",
        "company": "Account",
        "companies": "Account",
        "customer": "Account",
        "customers": "Account",
    }
    alias_target = alias_map.get(cleaned.lower())
    if alias_target and get_object_metadata(alias_target):
        return alias_target

    candidates = []
    def add_candidate(value: str) -> None:
        if not value:
            return
        candidates.append(value)
        if value.lower().endswith("s"):
            candidates.append(value[:-1])

    add_candidate(cleaned)
    add_candidate(cleaned.title())
    add_candidate(cleaned.replace(" ", "_"))
    add_candidate(cleaned.title().replace(" ", "_"))

    for candidate in candidates:
        if get_object_metadata(candidate):
            return candidate

    normalized = _normalize_object_token(cleaned)
    normalized_singular = normalized[:-1] if normalized.endswith("s") else normalized

    try:
        for custom_object in CustomObject.objects.all():
            name_norm = _normalize_object_token(custom_object.name)
            label_norm = _normalize_object_token(custom_object.label or "")
            if normalized in {name_norm, label_norm} or normalized_singular in {name_norm, label_norm}:
                return custom_object.name
    except Exception:
        return None

    return None


def handle_show_metrics(user, completed_metrics):
    response_message = ""
    results = {}
    object_labels = {}

    for metric in completed_metrics:
        object_name = metric.get("object")
        conditions = metric.get("conditions", [])
        aggregate = metric.get("aggregate") if isinstance(metric.get("aggregate"), dict) else None

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

        resolved_object = resolve_metrics_object_name(object_name)
        if resolved_object:
            object_name = resolved_object

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

        qs = apply_partner_access_filter(user, object_name, qs, custom_object=custom_object)

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
            agg_payload, agg_error = execute_aggregate(
                qs,
                aggregate,
                model,
                object_name,
                custom_object=custom_object,
                custom_fields=custom_fields,
            )
            if agg_error:
                response_message += f"⚠️ Aggregate failed for {display_name}: {agg_error}.<br>"
                continue
            results[object_name] = {"aggregate": agg_payload}
            agg_func = (aggregate.get("function") or "").lower()
            agg_group_by = (aggregate.get("group_by") or "").lower()
            agg_group_field = aggregate.get("group_field")
            if agg_func == "count" and not agg_group_by and not agg_group_field:
                list_qs = qs
                if limit:
                    list_qs = list_qs[:limit]
                serialized = safe_serialize_queryset(
                    list_qs,
                    object_name,
                    custom_object=custom_object,
                    custom_fields=custom_fields,
                )
                partner_label = partner_label_for_user(user)
                if partner_label:
                    for record in serialized:
                        record["_partner_label"] = partner_label
                results[object_name]["records"] = serialized
            # Build a short human-friendly note
            if agg_payload.get("series"):
                response_message += f"📈 {display_name} {agg_payload.get('function')}({agg_payload.get('field')}) over {agg_payload.get('range') or 'all time'} with {len(agg_payload['series'])} points.<br>"
            else:
                response_message += f"📈 {display_name} {agg_payload.get('function')}({agg_payload.get('field')}) = {agg_payload.get('value')}.<br>"
            continue

        if limit:
            qs = qs[:limit]

        serialized = safe_serialize_queryset(qs, object_name, custom_object=custom_object, custom_fields=custom_fields)
        partner_label = partner_label_for_user(user)
        if partner_label:
            for record in serialized:
                record["_partner_label"] = partner_label
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

    def _quarter_bounds(reference_date, quarter_offset=0):
        fiscal_start_month = 1
        try:
            tenant = Tenant.safe_first()
            raw_start = getattr(tenant, "fiscal_year_start_month", None)
            fiscal_start_month = int(raw_start) if raw_start else 1
        except Exception:
            fiscal_start_month = 1
        if fiscal_start_month < 1 or fiscal_start_month > 12:
            fiscal_start_month = 1

        month = reference_date.month
        year = reference_date.year
        fiscal_year = year if month >= fiscal_start_month else year - 1
        offset = (month - fiscal_start_month) % 12
        quarter_index = offset // 3
        start_month = ((fiscal_start_month - 1) + quarter_index * 3) % 12 + 1
        start_year = fiscal_year if start_month >= fiscal_start_month else fiscal_year + 1

        quarter_start = date(start_year, start_month, 1) + relativedelta(months=quarter_offset * 3)
        quarter_end = (quarter_start + relativedelta(months=3)) - timedelta(days=1)
        return quarter_start, quarter_end

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
    elif range_key in {"this_quarter", "current_quarter"}:
        start, end = _quarter_bounds(now_dt.date(), quarter_offset=0)
    elif range_key in {"last_quarter", "previous_quarter"}:
        start, end = _quarter_bounds(now_dt.date(), quarter_offset=-1)
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


def execute_aggregate(qs, aggregate_def, model, object_name, custom_object=None, custom_fields=None):
    """
    Execute aggregate functions with optional date range and time bucketing.
    Returns (payload, error).
    """
    if not aggregate_def:
        return None, "missing aggregate definition"

    func_name = (aggregate_def.get("function") or "sum").lower()
    field = aggregate_def.get("field")
    group_by = (aggregate_def.get("group_by") or "").lower()
    group_field = aggregate_def.get("group_field")
    if group_by in {"qtr", "quarterly"}:
        group_by = "quarter"
    if not group_field and group_by and group_by not in {"month", "week", "day", "quarter", "field"}:
        group_field = aggregate_def.get("group_by")
    date_field = aggregate_def.get("date_field") or ("updated_at" if hasattr(model, "updated_at") else None)
    range_key = aggregate_def.get("range")

    if not field and func_name == "count":
        field = "id"
    if isinstance(field, str) and field.strip().lower() in {"*", "all"} and func_name == "count":
        field = "id"

    if not field:
        return None, "aggregate field is required"

    if model.__name__ == "Opportunity" and isinstance(field, str):
        normalized_field = field.strip().lower()
        if normalized_field in {"forecast_amount", "expected_revenue", "net_amount"}:
            qs = qs.annotate(
                _forecast_value=Coalesce("primary_quote__net_amount", "amount")
            )
            field = "_forecast_value"
    if model.__name__ == "Opportunity" and isinstance(date_field, str):
        normalized_date_field = date_field.strip().lower()
        if normalized_date_field == "expected_close_date":
            # Keep forecast/reporting usable when expected close date is missing.
            qs = qs.annotate(
                _effective_close_date=Coalesce(
                    "expected_close_date",
                    Cast("created_at", output_field=DateField()),
                )
            )
            date_field = "_effective_close_date"

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

    # Detect if the target field is a custom field
    custom_field_lookup = {}
    for cf in custom_fields or []:
        if cf.name:
            custom_field_lookup[cf.name.lower()] = cf
            custom_field_lookup[_normalize_lookup_text(cf.name)] = cf
        if cf.label:
            custom_field_lookup[cf.label.lower()] = cf
            custom_field_lookup[_normalize_lookup_text(cf.label)] = cf

    def _resolve_custom_field(key):
        if not key:
            return None
        raw = str(key).strip()
        return (
            custom_field_lookup.get(raw.lower())
            or custom_field_lookup.get(_normalize_lookup_text(raw))
        )

    date_custom_field = None
    if date_field:
        annotated_date_fields = set(getattr(getattr(qs, "query", None), "annotations", {}).keys())
        if date_field not in annotated_date_fields:
            try:
                model._meta.get_field(date_field)
            except Exception:
                date_custom_field = _resolve_custom_field(date_field)
                if date_custom_field:
                    date_data_type = (date_custom_field.data_type or "").lower()
                    if date_data_type not in DATE_TYPES:
                        return None, f"date_field '{date_field}' is not a date field"
                else:
                    return None, f"date_field '{date_field}' does not exist"

    custom_field = None
    if isinstance(field, str):
        custom_field = _resolve_custom_field(field)

    def _annotate_custom_date_on_records(base_qs, date_field_obj):
        if not date_field_obj:
            return base_qs, None
        if custom_object:
            date_values = CustomFieldValue.objects.filter(
                field=date_field_obj,
                record_id=OuterRef("pk"),
            )
        else:
            try:
                ct = ContentType.objects.get_for_model(model)
            except Exception:
                return base_qs, "unable to resolve content type for date field"
            date_values = CustomFieldValue.objects.filter(
                field=date_field_obj,
                content_type=ct,
                object_id=OuterRef("pk"),
            )
        annotated = base_qs.annotate(
            _date_value=Subquery(date_values.values("value")[:1])
        ).annotate(
            _date_cast=Cast("_date_value", output_field=DateField())
        )
        return annotated, None

    def _annotate_custom_date_on_values(values_qs, date_field_obj):
        if not date_field_obj:
            return values_qs, None
        if custom_object:
            date_values = CustomFieldValue.objects.filter(
                field=date_field_obj,
                record_id=OuterRef("record_id"),
            )
        else:
            try:
                ct = ContentType.objects.get_for_model(model)
            except Exception:
                return values_qs, "unable to resolve content type for date field"
            date_values = CustomFieldValue.objects.filter(
                field=date_field_obj,
                content_type=ct,
                object_id=OuterRef("object_id"),
            )
        annotated = values_qs.annotate(
            _date_value=Subquery(date_values.values("value")[:1])
        ).annotate(
            _date_cast=Cast("_date_value", output_field=DateField())
        )
        return annotated, None

    if range_key and date_field and date_custom_field:
        qs, date_error = _annotate_custom_date_on_records(qs, date_custom_field)
        if date_error:
            return None, date_error
        qs = _apply_date_range(qs, "_date_cast", range_key)
    elif range_key and date_field:
        qs = _apply_date_range(qs, date_field, range_key)

    # Time bucketed series
    if group_by == "quarter" and not date_field:
        return None, "date_field is required when group_by='quarter'"

    if group_by == "quarter" and date_field:
        if func_name not in {"sum", "count", "avg", "average", "min", "max"}:
            return None, f"unsupported aggregate function '{func_name}'"

        fiscal_start_month = 1
        fiscal_label_mode = "start"
        try:
            tenant = Tenant.safe_first()
            raw_start = getattr(tenant, "fiscal_year_start_month", None)
            fiscal_start_month = int(raw_start) if raw_start else 1
            raw_label_mode = getattr(tenant, "fiscal_year_label_mode", None)
            if raw_label_mode in {"start", "end"}:
                fiscal_label_mode = raw_label_mode
        except Exception:
            fiscal_start_month = 1
        if fiscal_start_month < 1 or fiscal_start_month > 12:
            fiscal_start_month = 1

        def _quarter_bucket(period_val):
            period_date = period_val.date() if hasattr(period_val, "date") else period_val
            if not isinstance(period_date, date):
                return None
            month = period_date.month
            year = period_date.year
            fiscal_year = year if month >= fiscal_start_month else year - 1
            offset = (month - fiscal_start_month) % 12
            quarter = (offset // 3) + 1
            return fiscal_year, quarter

        def _quarter_label(fy_year, quarter):
            label_year = fy_year + (1 if fiscal_label_mode == "end" else 0)
            label_year_short = str(label_year % 100).zfill(2)
            return f"FY{label_year_short} Q{quarter}"

        if custom_field:
            data_type = (custom_field.data_type or "").lower()
            if data_type not in NUMERIC_TYPES:
                return None, f"aggregate not supported for non-numeric custom field '{field}'"

            values_qs = CustomFieldValue.objects.filter(field=custom_field)
            date_prefix = "record__" if custom_object else "content_object__"

            if custom_object:
                values_qs = values_qs.filter(record_id__in=qs.values_list("id", flat=True))
            else:
                try:
                    ct = ContentType.objects.get_for_model(model)
                    values_qs = values_qs.filter(content_type=ct, object_id__in=qs.values_list("id", flat=True))
                except Exception:
                    return None, "unable to resolve content type for custom field aggregation"

            values_qs = values_qs.annotate(value_cast=Cast("value", output_field=DecimalField(max_digits=30, decimal_places=10)))
            if date_custom_field:
                values_qs, date_error = _annotate_custom_date_on_values(values_qs, date_custom_field)
                if date_error:
                    return None, date_error
                if range_key and date_field:
                    values_qs = _apply_date_range(values_qs, "_date_cast", range_key)
                values_qs = values_qs.annotate(period=TruncMonth("_date_cast"))
            else:
                if range_key and date_field:
                    date_field_path = f"{date_prefix}{date_field}"
                    values_qs = _apply_date_range(values_qs, date_field_path, range_key)
                values_qs = values_qs.annotate(period=TruncMonth(date_prefix + date_field))
            if func_name in {"avg", "average"}:
                aggregated = values_qs.values("period").annotate(
                    sum_val=Sum("value_cast"),
                    count_val=Count("value_cast"),
                ).order_by("period")
            elif func_name == "min":
                aggregated = values_qs.values("period").annotate(value=Min("value_cast")).order_by("period")
            elif func_name == "max":
                aggregated = values_qs.values("period").annotate(value=Max("value_cast")).order_by("period")
            elif func_name == "count":
                aggregated = values_qs.values("period").annotate(value=Count("value_cast")).order_by("period")
            else:
                aggregated = values_qs.values("period").annotate(value=Sum("value_cast")).order_by("period")
        else:
            if date_custom_field:
                qs, date_error = _annotate_custom_date_on_records(qs, date_custom_field)
                if date_error:
                    return None, date_error
                qs = qs.annotate(period=TruncMonth("_date_cast"))
            else:
                qs = qs.annotate(period=TruncMonth(date_field))
            if func_name in {"avg", "average"}:
                aggregated = qs.values("period").annotate(
                    sum_val=Sum(field),
                    count_val=Count(field),
                ).order_by("period")
            elif func_name == "min":
                aggregated = qs.values("period").annotate(value=Min(field)).order_by("period")
            elif func_name == "max":
                aggregated = qs.values("period").annotate(value=Max(field)).order_by("period")
            else:
                aggregated = qs.values("period").annotate(value=agg_fn(field)).order_by("period")

        buckets = {}
        for entry in aggregated:
            period_val = entry.get("period")
            if period_val is None:
                continue
            quarter_key = _quarter_bucket(period_val)
            if not quarter_key:
                continue
            bucket = buckets.setdefault(quarter_key, {"sum": 0, "count": 0, "min": None, "max": None})

            if func_name in {"avg", "average"}:
                bucket["sum"] += entry.get("sum_val") or 0
                bucket["count"] += entry.get("count_val") or 0
            elif func_name == "min":
                val = entry.get("value")
                if val is None:
                    continue
                bucket["min"] = val if bucket["min"] is None or val < bucket["min"] else bucket["min"]
            elif func_name == "max":
                val = entry.get("value")
                if val is None:
                    continue
                bucket["max"] = val if bucket["max"] is None or val > bucket["max"] else bucket["max"]
            else:
                bucket["sum"] += entry.get("value") or 0

        series = []
        for fy_year, quarter in sorted(buckets.keys()):
            bucket = buckets[(fy_year, quarter)]
            if func_name in {"avg", "average"}:
                value = (bucket["sum"] / bucket["count"]) if bucket["count"] else None
            elif func_name == "min":
                value = bucket["min"]
            elif func_name == "max":
                value = bucket["max"]
            else:
                value = bucket["sum"]
            series.append({
                "period": _quarter_label(fy_year, quarter),
                "value": float(value) if value is not None else None,
            })

        total_value = sum([item.get("value") or 0 for item in series])
        return {
            "function": func_name,
            "field": field,
            "group_by": "quarter",
            "date_field": date_field,
            "range": range_key,
            "series": series,
            "total": float(total_value) if total_value is not None else None,
        }, None

    if group_by in {"month", "week", "day"} and date_field:
        trunc_map = {
            "month": TruncMonth,
            "week": TruncWeek,
            "day": TruncDay,
        }
        trunc_fn = trunc_map.get(group_by)
        if not trunc_fn:
            return None, f"unsupported group_by '{group_by}'"

        # Custom field aggregation path
        if custom_field:
            data_type = (custom_field.data_type or "").lower()
            if data_type not in NUMERIC_TYPES:
                return None, f"aggregate not supported for non-numeric custom field '{field}'"

            values_qs = CustomFieldValue.objects.filter(field=custom_field)
            date_prefix = "record__" if custom_object else "content_object__"

            # Filter to the records in the base queryset
            if custom_object:
                values_qs = values_qs.filter(record_id__in=qs.values_list("id", flat=True))
            else:
                try:
                    ct = ContentType.objects.get_for_model(model)
                    values_qs = values_qs.filter(content_type=ct, object_id__in=qs.values_list("id", flat=True))
                except Exception:
                    return None, "unable to resolve content type for custom field aggregation"

            values_qs = values_qs.annotate(value_cast=Cast("value", output_field=DecimalField(max_digits=30, decimal_places=10)))
            if date_custom_field:
                values_qs, date_error = _annotate_custom_date_on_values(values_qs, date_custom_field)
                if date_error:
                    return None, date_error
                if range_key and date_field:
                    values_qs = _apply_date_range(values_qs, "_date_cast", range_key)
                values_qs = values_qs.annotate(period=trunc_fn("_date_cast"))
            else:
                if range_key and date_field:
                    date_field_path = f"{date_prefix}{date_field}"
                    values_qs = _apply_date_range(values_qs, date_field_path, range_key)
                values_qs = values_qs.annotate(period=trunc_fn(date_prefix + date_field))
            aggregated = values_qs.values("period").annotate(value=agg_fn("value_cast")).order_by("period")
        else:
            if date_custom_field:
                qs, date_error = _annotate_custom_date_on_records(qs, date_custom_field)
                if date_error:
                    return None, date_error
                qs = qs.annotate(period=trunc_fn("_date_cast"))
            else:
                qs = qs.annotate(period=trunc_fn(date_field))
            aggregated = qs.values("period").annotate(value=agg_fn(field)).order_by("period")

        series = []
        for entry in aggregated:
            period_val = entry.get("period")
            if period_val is None:
                continue
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

    if group_by == "field" and not group_field:
        return None, "group_field is required when group_by='field'"

    # Categorical grouping
    if group_field:
        group_field_name = str(group_field)
        group_label = group_field_name
        group_custom_field = None
        field_obj = None
        try:
            field_obj = model._meta.get_field(group_field_name)
            if getattr(field_obj, "verbose_name", None):
                group_label = str(field_obj.verbose_name).title()
        except Exception:
            field_obj = None

        if not field_obj:
            group_custom_field = custom_field_lookup.get(group_field_name.lower())
            if group_custom_field:
                group_field_name = group_custom_field.name
                group_label = group_custom_field.label or group_field_name
            else:
                return None, f"group_by field '{group_field_name}' does not exist"

        content_type = None
        if not custom_object and (group_custom_field or (custom_field and func_name != "count")):
            try:
                content_type = ContentType.objects.get_for_model(model)
            except Exception:
                return None, "unable to resolve content type for custom field aggregation"

        def build_custom_subquery(field_obj, cast_field=None):
            values_qs = CustomFieldValue.objects.filter(field=field_obj)
            if custom_object:
                values_qs = values_qs.filter(record_id=OuterRef("pk"))
            else:
                values_qs = values_qs.filter(content_type=content_type, object_id=OuterRef("pk"))
            if cast_field:
                values_qs = values_qs.annotate(value_cast=Cast("value", output_field=cast_field))
                return Subquery(values_qs.values("value_cast")[:1])
            return Subquery(values_qs.values("value")[:1])

        agg_target = field
        if func_name == "count":
            agg_target = "id"
        elif custom_field:
            data_type = (custom_field.data_type or "").lower()
            if data_type not in NUMERIC_TYPES:
                return None, f"aggregate not supported for non-numeric custom field '{field}'"
            agg_expr = build_custom_subquery(
                custom_field,
                DecimalField(max_digits=30, decimal_places=10),
            )
            qs = qs.annotate(_agg_value=agg_expr)
            agg_target = "_agg_value"

        group_field_key = group_field_name
        group_data_type = ""
        if group_custom_field:
            group_data_type = (group_custom_field.data_type or "").lower()
            group_cast = None
            if group_data_type in DATE_TYPES:
                group_cast = DateField()
            elif group_data_type in NUMERIC_TYPES:
                group_cast = DecimalField(max_digits=30, decimal_places=10)
            group_expr = build_custom_subquery(group_custom_field, group_cast)
            qs = qs.annotate(_group_value=group_expr)
            group_field_key = "_group_value"

        aggregated = list(
            qs.values(group_field_key)
            .annotate(value=agg_fn(agg_target))
            .order_by("-value")
        )

        lookup_labels = {}
        if group_custom_field and group_data_type == "lookup":
            raw_ids = [
                str(entry.get(group_field_key))
                for entry in aggregated
                if entry.get(group_field_key) not in (None, "")
            ]
            if raw_ids:
                lookup_model = None
                target_custom_object = None
                model_ref = group_custom_field.lookup_model
                if isinstance(model_ref, str) and "." in model_ref:
                    try:
                        app_label, model_name = model_ref.split(".", 1)
                        lookup_model = apps.get_model(app_label, model_name)
                    except Exception:
                        lookup_model = None
                if lookup_model is None and model_ref:
                    try:
                        target_custom_object = CustomObject.objects.get(name=model_ref)
                        lookup_model = CustomRecord
                    except CustomObject.DoesNotExist:
                        lookup_model = None
                if lookup_model is not None:
                    lookup_qs = lookup_model.objects.filter(pk__in=raw_ids)
                    if lookup_model is CustomRecord and target_custom_object:
                        lookup_qs = lookup_qs.filter(object_type=target_custom_object)
                    lookup_labels = {str(obj.pk): str(obj) for obj in lookup_qs}

        series = []
        for entry in aggregated:
            label = entry.get(group_field_key)
            if label is None or label == "":
                label = "Unknown"
            else:
                if isinstance(label, datetime):
                    label = label.date().isoformat()
                elif isinstance(label, date):
                    label = label.isoformat()
                label = str(label)
                if lookup_labels:
                    label = lookup_labels.get(label, label)
            val = entry.get("value")
            series.append({
                "period": label,
                "value": float(val) if val is not None else None,
            })

        total_value = sum([item.get("value") or 0 for item in series])
        return {
            "function": func_name,
            "field": field,
            "group_by": "field",
            "group_field": group_field_name,
            "group_label": group_label,
            "range": range_key,
            "series": series,
            "total": float(total_value) if total_value is not None else None,
        }, None

    # Simple aggregate
    if custom_field:
        data_type = (custom_field.data_type or "").lower()
        if data_type not in NUMERIC_TYPES:
            return None, f"aggregate not supported for non-numeric custom field '{field}'"

        values_qs = CustomFieldValue.objects.filter(field=custom_field)
        if custom_object:
            values_qs = values_qs.filter(record_id__in=qs.values_list("id", flat=True))
            date_prefix = "record__"
        else:
            try:
                ct = ContentType.objects.get_for_model(model)
                values_qs = values_qs.filter(content_type=ct, object_id__in=qs.values_list("id", flat=True))
            except Exception:
                return None, "unable to resolve content type for custom field aggregation"
            date_prefix = "content_object__"

        values_qs = values_qs.annotate(value_cast=Cast("value", output_field=DecimalField(max_digits=30, decimal_places=10)))
        if date_custom_field:
            values_qs, date_error = _annotate_custom_date_on_values(values_qs, date_custom_field)
            if date_error:
                return None, date_error
            if range_key and date_field:
                values_qs = _apply_date_range(values_qs, "_date_cast", range_key)
        else:
            if range_key and date_field:
                date_field_path = f"{date_prefix}{date_field}"
                values_qs = _apply_date_range(values_qs, date_field_path, range_key)
        agg_value = values_qs.aggregate(value=agg_fn("value_cast")).get("value")
    else:
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
        tzinfo = now_dt.tzinfo

        def _expand_day_bounds(day):
            start_dt = datetime.combine(day, datetime.min.time())
            end_dt = datetime.combine(day, datetime.max.time())
            if tzinfo and start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=tzinfo)
                end_dt = end_dt.replace(tzinfo=tzinfo)
            return start_dt, end_dt

        def _coerce_dates(start_raw, end_raw):
            try:
                start_dt = parse_date(str(start_raw))
                end_dt = parse_date(str(end_raw))
            except Exception:
                start_dt = end_dt = None

            if start_dt and end_dt:
                if isinstance(field_obj, DateTimeField):
                    start_dt, _ = _expand_day_bounds(start_dt)
                    _, end_dt = _expand_day_bounds(end_dt)
                    return start_dt, end_dt
                return start_dt, end_dt
            return start_raw, end_raw

        if isinstance(val, str):
            key = val.strip().lower()
            if key == "today":
                start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
                end = now_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                return start, end
            if key == "yesterday":
                day = (now_dt - timedelta(days=1)).date()
                start, end = _expand_day_bounds(day)
                return start, end
            if key == "tomorrow":
                day = (now_dt + timedelta(days=1)).date()
                start, end = _expand_day_bounds(day)
                return start, end
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
            start_dt = parse_date(str(start_raw))
            end_dt = parse_date(str(end_raw))

            # If it's a full-year range but not the current year, reinterpret as current year
            if start_dt and end_dt:
                if start_dt.month == 1 and start_dt.day == 1 and end_dt.month == 12 and end_dt.day in (31, 30):
                    current_start = now_dt.replace(month=1, day=1)
                    current_end = now_dt.replace(month=12, day=31)
                    return current_start, current_end
                return _coerce_dates(start_raw, end_raw)
            return start_raw, end_raw

        if isinstance(val, dict):
            start = val.get("start_date") or val.get("start")
            end = val.get("end_date") or val.get("end")
            if start and end:
                return _coerce_dates(start, end)
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

    def _resolve_lookup_ids(raw_value):
        """Map a lookup filter value (label/name/id) to matching record IDs stored in CFV.value."""
        val_str = str(raw_value).strip()
        ids = []
        model = None
        target_custom_object = None

        # Resolve lookup target model
        model_ref = getattr(custom_field, "lookup_model", None)
        if model_ref:
            if isinstance(model_ref, str) and "." in model_ref:
                try:
                    app_label, model_name = model_ref.split(".", 1)
                    model = apps.get_model(app_label, model_name)
                except Exception:
                    model = None
            if model is None:
                # Maybe it is a CustomObject name
                try:
                    target_custom_object = CustomObject.objects.get(name=model_ref)
                    model = CustomRecord
                except CustomObject.DoesNotExist:
                    model = None

        if model is None:
            return [val_str]

        if val_str.isdigit():
            return [val_str]

        def _resolve_custom_record_id_by_name():
            if model is not CustomRecord or not target_custom_object:
                return []

            try:
                all_fields = list(CustomField.objects.filter(custom_object=target_custom_object))
                if not all_fields:
                    return []

                # Prefer "name"/"nombre"/"title"/"titulo" fields for display matching
                preferred = []
                for f in all_fields:
                    name = (f.name or "").lower()
                    label = (f.label or "").lower()
                    haystack = f"{name} {label}"
                    if any(token in haystack for token in ("name", "nombre", "title", "titulo")):
                        preferred.append(f)

                candidate_fields = preferred
                if not candidate_fields:
                    candidate_fields = [f for f in all_fields if (f.data_type or "").lower() in {"text", "textarea", "dropdown"}]
                if not candidate_fields:
                    return []

                candidate_values = (
                    CustomFieldValue.objects.filter(
                        record__object_type=target_custom_object,
                        field__in=candidate_fields,
                    )
                    .exclude(value="")
                    .exclude(value__isnull=True)
                )

                exact_ids = list(candidate_values.filter(value__iexact=val_str).values_list("record_id", flat=True).distinct())
                if exact_ids:
                    return [str(exact_ids[0])]

                query_norm = _normalize_lookup_text(val_str)
                if not query_norm:
                    return []

                # Fuzzy match against up to N candidate labels
                rows = list(candidate_values.values_list("record_id", "value")[:1200])
                best_by_record = {}
                for record_id, candidate_value in rows:
                    cand_norm = _normalize_lookup_text(candidate_value)
                    if not cand_norm:
                        continue
                    score = difflib.SequenceMatcher(None, query_norm, cand_norm).ratio()
                    if score > best_by_record.get(record_id, 0):
                        best_by_record[record_id] = score

                if not best_by_record:
                    return []

                ranked = sorted(best_by_record.items(), key=lambda item: item[1], reverse=True)
                best_id, best_score = ranked[0]
                second_score = ranked[1][1] if len(ranked) > 1 else 0

                # Only accept a confident single match
                if best_score >= 0.86 and (best_score - second_score) >= 0.06:
                    return [str(best_id)]
            except Exception:
                return []

            return []

        try:
            qs_lookup = model.objects.all()
            if model is CustomRecord and target_custom_object:
                qs_lookup = qs_lookup.filter(object_type=target_custom_object)

            # Direct PK match
            ids.extend(list(qs_lookup.filter(pk=val_str).values_list("pk", flat=True)))

            # Name-like matches
            name_filter_exact = Q()
            name_filter_contains = Q()
            has_name_filters = False
            if hasattr(model, "name"):
                name_filter_exact |= Q(name__iexact=val_str)
                name_filter_contains |= Q(name__icontains=val_str)
                has_name_filters = True
            if hasattr(model, "custom_identifier"):
                name_filter_exact |= Q(custom_identifier__iexact=val_str)
                name_filter_contains |= Q(custom_identifier__icontains=val_str)
                has_name_filters = True
            if hasattr(model, "email"):
                name_filter_exact |= Q(email__iexact=val_str)
                name_filter_contains |= Q(email__icontains=val_str)
                has_name_filters = True
            if hasattr(model, "first_name") and hasattr(model, "last_name"):
                name_filter_exact |= Q(first_name__iexact=val_str) | Q(last_name__iexact=val_str)
                name_filter_contains |= Q(first_name__icontains=val_str) | Q(last_name__icontains=val_str)
                has_name_filters = True

            if has_name_filters:
                exact_hits = list(qs_lookup.filter(name_filter_exact).values_list("pk", flat=True))
                ids.extend(exact_hits)
                if not exact_hits:
                    ids.extend(list(qs_lookup.filter(name_filter_contains).values_list("pk", flat=True)))

            if model is CustomRecord:
                ids.extend(_resolve_custom_record_id_by_name())
        except Exception:
            return []

        ids = [str(i) for i in ids if i is not None]
        return ids

    def _resolve_lookup_ids_from_candidates(raw_value):
        """
        Resolve a human-friendly lookup value (e.g. project name) to IDs by looking only at
        lookup IDs already referenced by the current queryset.
        """
        raw_str = str(raw_value or "").strip()
        if not raw_str:
            return [], []
        if raw_str.isdigit():
            return [raw_str], []

        # Candidate lookup ids present in the filtered records
        candidate_ids = list(
            values_qs.filter(record_id__in=qs.values_list("id", flat=True))
            .exclude(value="")
            .exclude(value__isnull=True)
            .values_list("value", flat=True)
            .distinct()[:500]
        )
        if not candidate_ids:
            return [], []

        # Resolve lookup target model (best-effort)
        model_ref = getattr(custom_field, "lookup_model", None)
        model = None
        target_custom_object = None

        if model_ref and isinstance(model_ref, str) and "." in model_ref:
            try:
                app_label, model_name = model_ref.split(".", 1)
                model = apps.get_model(app_label, model_name)
            except Exception:
                model = None
        if model is None and model_ref:
            try:
                target_custom_object = CustomObject.objects.get(name=model_ref)
                model = CustomRecord
            except Exception:
                model = None

        if model is None:
            # Default to CustomRecord for custom-object lookups
            model = CustomRecord

        # Fetch referenced objects and build a label map
        objects_qs = model.objects.filter(pk__in=candidate_ids)
        if model is CustomRecord and target_custom_object:
            objects_qs = objects_qs.filter(object_type=target_custom_object)

        id_to_label = {}
        try:
            for obj in objects_qs[:500]:
                label = str(obj).strip()
                if label:
                    id_to_label[str(obj.pk)] = label
        except Exception:
            id_to_label = {}

        if not id_to_label:
            return [], []

        query_norm = _normalize_lookup_text(raw_str)
        if not query_norm:
            return [], []

        # Exact normalized match first
        exact_matches = [
            rec_id
            for rec_id, label in id_to_label.items()
            if _normalize_lookup_text(label) == query_norm
        ]
        if exact_matches:
            return exact_matches, sorted(set(id_to_label.values()))[:10]

        # Safe contains match (only if unambiguous)
        contains_matches = []
        for rec_id, label in id_to_label.items():
            label_norm = _normalize_lookup_text(label)
            if not label_norm:
                continue
            if query_norm in label_norm or label_norm in query_norm:
                contains_matches.append(rec_id)
        if len(contains_matches) == 1:
            return contains_matches, sorted(set(id_to_label.values()))[:10]

        # Fuzzy match within the referenced set
        scored = []
        for rec_id, label in id_to_label.items():
            score = difflib.SequenceMatcher(None, query_norm, _normalize_lookup_text(label)).ratio()
            scored.append((rec_id, score))
        scored.sort(key=lambda t: t[1], reverse=True)

        best_id, best_score = scored[0]
        second_score = scored[1][1] if len(scored) > 1 else 0
        if best_score >= 0.86 and (best_score - second_score) >= 0.06:
            return [best_id], sorted(set(id_to_label.values()))[:10]
        return [], sorted(set(id_to_label.values()))[:10]

    try:
        # Special handling for lookup fields: allow matching by ID or readable label
        if data_type == "lookup":
            # First try resolving against referenced IDs in the current queryset (more reliable for CustomRecord lookups).
            target_ids, suggestions = _resolve_lookup_ids_from_candidates(value)
            if not target_ids:
                target_ids = _resolve_lookup_ids(value)
            if isinstance(value, str) and not value.strip().isdigit() and not target_ids:
                suggestion_text = f" Available options include: {', '.join(suggestions[:8])}." if suggestions else ""
                return False, f"could not resolve lookup value '{value}' to a record id.{suggestion_text}", qs
            if operator == "equals":
                updated_qs = include_records(values_qs.filter(value__in=target_ids))
            elif operator == "not_equals":
                updated_qs = exclude_records(values_qs.filter(value__in=target_ids))
            elif operator == "in":
                normalized = []
                for item in value if isinstance(value, (list, tuple)) else [value]:
                    ids_for_item, _ = _resolve_lookup_ids_from_candidates(item)
                    normalized.extend(ids_for_item or _resolve_lookup_ids(item))
                if isinstance(value, (list, tuple)) and all(isinstance(v, str) and not v.strip().isdigit() for v in value) and not normalized:
                    return False, "could not resolve lookup values to record ids", qs
                updated_qs = include_records(values_qs.filter(value__in=normalized))
            elif operator == "not_in":
                normalized = []
                for item in value if isinstance(value, (list, tuple)) else [value]:
                    ids_for_item, _ = _resolve_lookup_ids_from_candidates(item)
                    normalized.extend(ids_for_item or _resolve_lookup_ids(item))
                if isinstance(value, (list, tuple)) and all(isinstance(v, str) and not v.strip().isdigit() for v in value) and not normalized:
                    return False, "could not resolve lookup values to record ids", qs
                updated_qs = exclude_records(values_qs.filter(value__in=normalized))
            else:
                return False, f"operator '{operator}' not supported for lookup", qs

            return True, "", updated_qs

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
    field_lookup = {field.name: field for field in custom_fields}
    lookup_field_models = {}
    model_to_ids = {}
    record_values = []
    serialized = []

    def _resolve_lookup_model(model_ref):
        if not model_ref or not isinstance(model_ref, str) or "." not in model_ref:
            return None
        try:
            app_label, model_name = model_ref.split(".", 1)
            return apps.get_model(app_label, model_name)
        except Exception:
            return None

    def _normalize_lookup_values(raw_value):
        if raw_value is None:
            return []
        if isinstance(raw_value, (list, tuple)):
            return list(raw_value)
        raw_str = str(raw_value).strip()
        if not raw_str:
            return []
        if raw_str.startswith("[") and raw_str.endswith("]"):
            try:
                parsed = json.loads(raw_str)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        if "," in raw_str:
            return [item.strip() for item in raw_str.split(",") if item.strip()]
        return [raw_str]

    def _format_lookup_display(obj):
        if obj is None:
            return None
        if hasattr(obj, "name") and obj.name:
            return obj.name
        if hasattr(obj, "custom_identifier") and obj.custom_identifier:
            return obj.custom_identifier
        if hasattr(obj, "record_id") and obj.record_id:
            return obj.record_id
        if hasattr(obj, "first_name") and hasattr(obj, "last_name"):
            full = f"{obj.first_name} {obj.last_name}".strip()
            if full:
                return full
        if hasattr(obj, "email") and obj.email:
            return obj.email
        return str(obj.pk)

    def _resolve_lookup_display(raw_value, display_map):
        values = _normalize_lookup_values(raw_value)
        if not values:
            return serialize_value(raw_value)
        resolved = []
        for val in values:
            lookup = display_map.get(str(val))
            resolved.append(lookup if lookup is not None else val)
        if len(resolved) == 1:
            return serialize_value(resolved[0])
        return [serialize_value(item) for item in resolved]

    for field_name, field in field_lookup.items():
        if not field.lookup_model:
            continue
        model = _resolve_lookup_model(field.lookup_model)
        if model:
            lookup_field_models[field_name] = model

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

        record_values.append((row, values_map))

        for field_name, model in lookup_field_models.items():
            raw_value = values_map.get(field_name)
            for lookup_value in _normalize_lookup_values(raw_value):
                if lookup_value in (None, ""):
                    continue
                model_to_ids.setdefault(model, set()).add(lookup_value)

    model_display_map = {}
    for model, raw_ids in model_to_ids.items():
        if not raw_ids:
            continue
        pk_field = model._meta.pk
        numeric_pk = isinstance(
            pk_field,
            (
                models.AutoField,
                models.IntegerField,
                models.BigIntegerField,
                models.PositiveIntegerField,
                models.PositiveSmallIntegerField,
                models.SmallIntegerField,
                models.BigAutoField,
            ),
        )
        ids = []
        for raw in raw_ids:
            if raw is None or raw == "":
                continue
            if numeric_pk:
                try:
                    ids.append(int(str(raw)))
                except (TypeError, ValueError):
                    continue
            else:
                ids.append(str(raw))
        if not ids:
            continue
        display_map = {}
        try:
            for obj in model.objects.filter(pk__in=ids):
                display_map[str(obj.pk)] = _format_lookup_display(obj)
        except Exception:
            display_map = {}
        model_display_map[model] = display_map

    for row, values_map in record_values:
        for field_name in field_names:
            if field_name in lookup_field_models:
                model = lookup_field_models[field_name]
                row[field_name] = _resolve_lookup_display(values_map.get(field_name), model_display_map.get(model, {}))
            else:
                row[field_name] = serialize_value(values_map.get(field_name))

        serialized.append(row)

    return serialized


from datetime import datetime, date
from django.db.models import ForeignKey

# Allowed fields per model
ALLOWED_FIELDS = {
    "Lead": ["id", "leadId", "external_id", "first_name", "last_name", "phone", "email", "source", "contact", "status", "notes", "assigned_to", "created_at", "activities"],
    "Product": ["id", "prdid", "external_id", "name", "sku", "price", "fixed_price", "price_mode", "is_subscription", "term", "is_bundle", "family", "is_active", "created_at", "description"],
    "Account": ["id", "accid", "external_id", "name", "industry", "website", "phone", "street", "city", "state", "zip_code"],
    "Contact": ["id", "contactId", "external_id", "first_name", "last_name", "email", "phone", "company", "job_title", "notes", "account", "is_primary"],
    "Opportunity": ["id", "oppid", "external_id", "hs_deal_id", "name", "account", "amount", "stage", "expected_close_date", "primary_quote", "owner", "created_by"],
    "Quote": ["id", "qteid", "external_id", "name", "account", "opportunity", "subtotal", "net_amount", "tax_percentage", "tax_amount", "status",
              "discount_percentage", "discount_amount", "expiration_date", "notes", "created_at"],
    "Activity": ["id", "activityid", "external_id", "subject", "activity_type", "status", "due_date", "lead", "opportunity", "contact", "notes", "created_at"],
    "Contract": ["id", "external_id", "opportunity", "start_date", "end_date", "contract_status"],
    "Subscription": ["id", "external_id", "quote", "quote_line", "product", "contract", "start_date", "end_date", "billing_cycle", "price_per_cycle", "term"],
    "Option": ["id", "parent_product", "product_option", "quantity", "is_required", "min_quantity", "max_quantity", "default_selected", "group_name"],
    "Tenant": ["id", "tenant_id", "name", "domain", "contact_email", "phone_number", "plan", "version", "created_at"],
    "Knowledge": ["id", "title", "content_text", "video_url", "image_url", "tags", "language", "is_active", "created_at", "updated_at"],
    "CustomRecord": ["custom_identifier"],
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
