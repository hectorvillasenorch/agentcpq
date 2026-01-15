import logging

from .models import FeatureFlag, MetricDefinition, ThresholdRule, SlaConfig
from .spec import BUSINESS_OWNED_INPUTS, FEATURE_FLAG_KEY, LEAD_METRICS, THRESHOLD_RULES_SEED

logger = logging.getLogger(__name__)


def ensure_intelligence_defaults(tenant_id: str) -> None:
    if not tenant_id:
        logger.warning("Intelligence seed skipped: missing tenant_id")
        return

    FeatureFlag.objects.get_or_create(
        tenant_id=tenant_id,
        key=FEATURE_FLAG_KEY,
        defaults={"enabled": False},
    )

    sla_config = BUSINESS_OWNED_INPUTS.get("sla_config", {})
    sla_key = sla_config.get("key", "LEADS_NEW_SLA_DAYS")
    sla_default = int(sla_config.get("default", 1))
    SlaConfig.objects.get_or_create(
        tenant_id=tenant_id,
        key=sla_key,
        defaults={"value": sla_default},
    )

    metric_created = 0
    for metric in LEAD_METRICS:
        _, created = MetricDefinition.objects.get_or_create(
            tenant_id=tenant_id,
            domain="leads",
            metric_key=metric["metric_key"],
            defaults={
                "display_name": metric["display_name"],
                "description": metric.get("description"),
                "unit": metric.get("unit"),
                "compute_method": metric["compute_method"],
                "compute_spec": metric.get("compute_spec"),
                "is_active": True,
            },
        )
        if created:
            metric_created += 1

    rule_created = 0
    for rule in THRESHOLD_RULES_SEED:
        _, created = ThresholdRule.objects.get_or_create(
            tenant_id=tenant_id,
            domain=rule["domain"],
            rule_key=rule["rule_key"],
            defaults={
                "severity": rule["severity"],
                "condition": rule["condition"],
                "message_template": rule["message_template"],
                "audience_roles": rule["audience_roles"],
                "is_active": True,
            },
        )
        if created:
            rule_created += 1

    if metric_created or rule_created:
        logger.info(
            "Seeded intelligence defaults tenant_id=%s metrics_created=%s rules_created=%s",
            tenant_id,
            metric_created,
            rule_created,
        )
