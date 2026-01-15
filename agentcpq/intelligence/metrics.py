from __future__ import annotations

from datetime import date
from decimal import Decimal
import logging

from django.db.models import Count, Q
from django.utils import timezone

from cpq.models import Lead, Tenant

from .identifiers import tenant_uuid_from_value
from .models import MetricDefinition, PlanningConfig, SlaConfig
from .spec import BUSINESS_OWNED_INPUTS
from .seed import ensure_intelligence_defaults
from .timeframes import previous_period_range, current_period_range


LEAD_FIELD_MAP = {
    "created_date": "created_at",
    "updated_date": "updated_at",
}

logger = logging.getLogger(__name__)


def _tenant_lead_queryset(tenant: Tenant | None):
    if tenant and getattr(tenant, "tenant_id", None):
        return Lead.objects.filter(
            Q(contact__account__tenant_id=tenant.tenant_id) | Q(contact__isnull=True)
        ).distinct()
    return Lead.objects.all()


def _normalize_in_values(values):
    if not isinstance(values, list):
        return values
    normalized = []
    for value in values:
        if isinstance(value, str):
            normalized.append(value.lower())
        else:
            normalized.append(value)
    return normalized


def _apply_filters(
    qs,
    filters,
    timeframe_key: str,
    period_start: date,
    period_end: date,
    *,
    year_span: int = 1,
    use_fiscal: bool = False,
    fiscal_start_month: int = 1,
    fiscal_label_mode: str = "start",
):
    for filt in filters or []:
        field = filt.get("field")
        op = filt.get("op")
        value = filt.get("value")
        if not field or not op:
            continue
        field = LEAD_FIELD_MAP.get(field, field)
        if op == "between_period":
            qs = qs.filter(**{f"{field}__date__gte": period_start, f"{field}__date__lte": period_end})
            continue
        if op == "between_previous_period":
            prev_start, prev_end = previous_period_range(
                timeframe_key,
                period_start,
                period_end,
                year_span=year_span,
                use_fiscal=use_fiscal,
                fiscal_start_month=fiscal_start_month,
                fiscal_label_mode=fiscal_label_mode,
            )
            qs = qs.filter(**{f"{field}__date__gte": prev_start, f"{field}__date__lte": prev_end})
            continue
        if op == "in":
            normalized = _normalize_in_values(value)
            qs = qs.filter(**{f"{field}__in": normalized})
            continue
    return qs


def compute_sql_metric(
    metric_def,
    tenant: Tenant | None,
    timeframe_key: str,
    period_start: date,
    period_end: date,
    *,
    year_span: int = 1,
    use_fiscal: bool = False,
    fiscal_start_month: int = 1,
    fiscal_label_mode: str = "start",
):
    spec = metric_def.compute_spec or {}
    table = spec.get("table")
    if table != "cpq_lead":
        return None, None
    qs = _tenant_lead_queryset(tenant)
    qs = _apply_filters(
        qs,
        spec.get("filters", []),
        timeframe_key,
        period_start,
        period_end,
        year_span=year_span,
        use_fiscal=use_fiscal,
        fiscal_start_month=fiscal_start_month,
        fiscal_label_mode=fiscal_label_mode,
    )
    group_by = spec.get("group_by")
    aggregation = spec.get("aggregation")

    if group_by:
        group_by = LEAD_FIELD_MAP.get(group_by, group_by)
        grouped = qs.values(group_by).annotate(total=Count("id"))
        value_json = [
            {"label": row.get(group_by) or "Unknown", "value": row.get("total", 0)}
            for row in grouped
        ]
        return None, value_json

    if aggregation == "count":
        return qs.count(), None
    return None, None


def _safe_divide(numerator, denominator):
    if denominator in (0, None):
        return Decimal("0")
    return Decimal(numerator) / Decimal(denominator)


def _get_planning_config(tenant_uuid, timeframe_key: str, period_start: date, period_end: date):
    base_qs = PlanningConfig.objects.filter(
        tenant_id=tenant_uuid,
        domain="leads",
    )
    timeframe_qs = base_qs.filter(timeframe_key=timeframe_key)
    logger.info(
        "PlanningConfig lookup tenant_id=%s timeframe=%s period=%s..%s base_count=%s timeframe_count=%s",
        tenant_uuid,
        timeframe_key,
        period_start,
        period_end,
        base_qs.count(),
        timeframe_qs.count(),
    )
    exact = timeframe_qs.filter(
        period_start=period_start,
        period_end=period_end,
    ).order_by("-updated_at").first()
    if exact:
        logger.info(
            "PlanningConfig exact match id=%s period=%s..%s pipeline_required_leads=%s",
            exact.id,
            exact.period_start,
            exact.period_end,
            exact.pipeline_required_leads,
        )
        return exact
    today = timezone.now().date()
    active = timeframe_qs.filter(
        period_start__lte=today,
        period_end__gte=today,
    ).order_by("-updated_at").first()
    if active:
        logger.info(
            "PlanningConfig active match id=%s period=%s..%s pipeline_required_leads=%s",
            active.id,
            active.period_start,
            active.period_end,
            active.pipeline_required_leads,
        )
        return active
    fallback = timeframe_qs.order_by("-updated_at").first()
    if fallback:
        logger.info(
            "PlanningConfig timeframe fallback id=%s period=%s..%s pipeline_required_leads=%s",
            fallback.id,
            fallback.period_start,
            fallback.period_end,
            fallback.pipeline_required_leads,
        )
        return fallback
    fallback = base_qs.order_by("-updated_at").first()
    if fallback:
        logger.info(
            "PlanningConfig cross-timeframe fallback id=%s timeframe=%s period=%s..%s pipeline_required_leads=%s",
            fallback.id,
            fallback.timeframe_key,
            fallback.period_start,
            fallback.period_end,
            fallback.pipeline_required_leads,
        )
    else:
        logger.warning("PlanningConfig fallback missing for tenant_id=%s timeframe=%s", tenant_uuid, timeframe_key)
    return fallback


def _derive_pipeline_required_leads(config: PlanningConfig | None):
    if not config:
        return None
    if config.pipeline_required_leads is not None:
        return config.pipeline_required_leads
    derived = config.derived_spec or {}
    direct = derived.get("pipeline_required_leads")
    if isinstance(direct, (int, float)):
        return int(direct)
    return None


def get_sla_days(tenant: Tenant | None = None) -> int:
    config = BUSINESS_OWNED_INPUTS.get("sla_config", {})
    default_value = int(config.get("default", 1))
    sla_key = config.get("key", "LEADS_NEW_SLA_DAYS")
    if tenant is None:
        return default_value
    tenant_uuid = tenant_uuid_from_value(getattr(tenant, "tenant_id", None) or getattr(tenant, "pk", ""))
    record = SlaConfig.objects.filter(tenant_id=tenant_uuid, key=sla_key).first()
    if record and record.value is not None:
        try:
            return max(int(record.value), 0)
        except (TypeError, ValueError):
            return default_value
    return default_value


def compute_python_metric(metric_def, metrics: dict, tenant: Tenant | None, timeframe_key: str, period_start: date, period_end: date):
    metric_key = metric_def.metric_key
    spec = metric_def.compute_spec or {}

    if metric_key in {"qualification_rate", "lead_trend_percent", "coverage_health_ratio"}:
        formula = spec.get("formula")
        if formula:
            return _evaluate_formula(formula, metrics), None

    if metric_key == "avg_age_new_status_days":
        qs = _tenant_lead_queryset(tenant).filter(status__iexact="new")
        today = timezone.now().date()
        ages = [(today - lead.created_at.date()).days for lead in qs.only("created_at")]
        if not ages:
            return Decimal("0"), None
        return Decimal(sum(ages)) / Decimal(len(ages)), None

    if metric_key == "stale_new_count":
        today = timezone.now().date()
        sla_days = metrics.get("sla_days")
        if sla_days is None:
            sla_days = get_sla_days(tenant)
        qs = _tenant_lead_queryset(tenant).filter(status__iexact="new")
        count = sum(1 for lead in qs.only("created_at") if (today - lead.created_at.date()).days > sla_days)
        return count, None

    if metric_key == "pipeline_required_leads":
        tenant_uuid = tenant_uuid_from_value(getattr(tenant, "tenant_id", None) or getattr(tenant, "pk", ""))
        config = _get_planning_config(tenant_uuid, timeframe_key, period_start, period_end)
        derived = _derive_pipeline_required_leads(config)
        logger.info(
            "pipeline_required_leads tenant_id=%s timeframe=%s period=%s..%s config_id=%s derived=%s",
            tenant_uuid,
            timeframe_key,
            period_start,
            period_end,
            getattr(config, "id", None),
            derived,
        )
        return derived, None

    return None, None


def _evaluate_formula(formula: str, metrics: dict):
    from .safe_eval import safe_eval_expression

    context = {key: metrics.get(key) or 0 for key in metrics}
    return safe_eval_expression(formula, context)


def compute_leads_metrics(
    tenant: Tenant | None,
    timeframe_key: str,
    period_start: date,
    period_end: date,
    *,
    year_span: int = 1,
    use_fiscal: bool = False,
    fiscal_start_month: int = 1,
    fiscal_label_mode: str = "start",
):
    tenant_uuid = tenant_uuid_from_value(getattr(tenant, "tenant_id", None) or getattr(tenant, "pk", ""))
    metric_defs = MetricDefinition.objects.filter(
        tenant_id=tenant_uuid,
        domain="leads",
        is_active=True,
    )
    if not metric_defs.exists():
        logger.warning(
            "MetricDefinition missing; seeding defaults for tenant_id=%s",
            tenant_uuid,
        )
        ensure_intelligence_defaults(tenant_uuid)
        metric_defs = MetricDefinition.objects.filter(
            tenant_id=tenant_uuid,
            domain="leads",
            is_active=True,
        )
    logger.info(
        "Compute leads metrics tenant_id=%s timeframe=%s period=%s..%s defs=%s fiscal=%s",
        tenant_uuid,
        timeframe_key,
        period_start,
        period_end,
        metric_defs.count(),
        use_fiscal,
    )
    metrics: dict = {"sla_days": get_sla_days(tenant)}
    snapshots = []

    def _record_snapshot(metric_def, value_number, value_json):
        if value_number is not None:
            metrics[metric_def.metric_key] = value_number
        if value_json is not None:
            metrics[metric_def.metric_key] = value_json
        snapshots.append(
            {
                "metric_key": metric_def.metric_key,
                "value_number": value_number,
                "value_json": value_json,
            }
        )

    sql_defs = [metric for metric in metric_defs if metric.compute_method == "sql"]
    python_defs = [metric for metric in metric_defs if metric.compute_method == "python"]

    for metric_def in sql_defs:
        value_number, value_json = compute_sql_metric(
            metric_def,
            tenant,
            timeframe_key,
            period_start,
            period_end,
            year_span=year_span,
            use_fiscal=use_fiscal,
            fiscal_start_month=fiscal_start_month,
            fiscal_label_mode=fiscal_label_mode,
        )
        _record_snapshot(metric_def, value_number, value_json)

    for metric_def in python_defs:
        if metric_def.compute_spec and metric_def.compute_spec.get("formula"):
            continue
        value_number, value_json = compute_python_metric(metric_def, metrics, tenant, timeframe_key, period_start, period_end)
        _record_snapshot(metric_def, value_number, value_json)

    for metric_def in python_defs:
        if not (metric_def.compute_spec and metric_def.compute_spec.get("formula")):
            continue
        value_number, value_json = compute_python_metric(metric_def, metrics, tenant, timeframe_key, period_start, period_end)
        _record_snapshot(metric_def, value_number, value_json)

    return metrics, snapshots


def compute_leads_metrics_for_timeframe(
    tenant: Tenant | None,
    timeframe_key: str,
    *,
    year_span: int = 1,
    year_offset: int = 0,
    use_fiscal: bool = False,
    fiscal_start_month: int = 1,
    fiscal_label_mode: str = "start",
    fiscal_end_label_year: int | None = None,
):
    period_start, period_end = current_period_range(
        timeframe_key,
        timezone.now().date(),
        year_span=year_span,
        year_offset=year_offset,
        use_fiscal=use_fiscal,
        fiscal_start_month=fiscal_start_month,
        fiscal_label_mode=fiscal_label_mode,
        fiscal_end_label_year=fiscal_end_label_year,
    )
    metrics, snapshots = compute_leads_metrics(
        tenant,
        timeframe_key,
        period_start,
        period_end,
        year_span=year_span,
        use_fiscal=use_fiscal,
        fiscal_start_month=fiscal_start_month,
        fiscal_label_mode=fiscal_label_mode,
    )
    return metrics, snapshots, period_start, period_end
