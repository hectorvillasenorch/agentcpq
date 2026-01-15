from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from cpq.models import Tenant

from .feature_flags import is_intelligence_enabled, tenant_uuid_from_tenant
from .metrics import compute_leads_metrics, get_sla_days
from .models import MetricSnapshot, ThresholdRule
from .notifications import record_notifications
from .thresholds import evaluate_condition
from .timeframes import current_period_range


def _normalize_value(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return value


def _store_snapshot(
    *,
    tenant_uuid,
    domain: str,
    metric_key: str,
    timeframe_key: str,
    period_start,
    period_end,
    value_number,
    value_json,
):
    MetricSnapshot.objects.update_or_create(
        tenant_id=tenant_uuid,
        domain=domain,
        metric_key=metric_key,
        timeframe_key=timeframe_key,
        period_start=period_start,
        period_end=period_end,
        defaults={
            "value_number": value_number,
            "value_json": value_json,
            "generated_at": timezone.now(),
            "source_fingerprint": f"{metric_key}:{period_start}:{period_end}",
        },
    )


def run_leads_metric_snapshot(timeframe_key: str):
    for tenant in Tenant.objects.all():
        if not is_intelligence_enabled(tenant):
            continue

        tenant_uuid = tenant_uuid_from_tenant(tenant)
        period_start, period_end = current_period_range(timeframe_key, timezone.now().date())
        metrics, snapshots = compute_leads_metrics(tenant, timeframe_key, period_start, period_end)
        metrics["sla_days"] = get_sla_days(tenant)

        for snapshot in snapshots:
            value_number = snapshot.get("value_number")
            value_json = snapshot.get("value_json")
            _store_snapshot(
                tenant_uuid=tenant_uuid,
                domain="leads",
                metric_key=snapshot.get("metric_key"),
                timeframe_key=timeframe_key,
                period_start=period_start,
                period_end=period_end,
                value_number=_normalize_value(value_number) if value_number is not None else None,
                value_json=value_json,
            )

        rules = ThresholdRule.objects.filter(
            tenant_id=tenant_uuid,
            domain="leads",
            is_active=True,
        )
        triggered = [rule for rule in rules if evaluate_condition(rule.condition, metrics)]
        record_notifications(
            tenant_uuid=tenant_uuid,
            domain="leads",
            period_key=f"{timeframe_key}:{period_start}:{period_end}",
            triggered_rules=[{"rule_key": r.rule_key, "severity": r.severity, "message_template": r.message_template, "audience_roles": r.audience_roles} for r in triggered],
            metrics={k: (float(v) if isinstance(v, Decimal) else v) for k, v in metrics.items()},
        )
