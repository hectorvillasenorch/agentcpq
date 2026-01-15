from django.db import migrations


FEATURE_FLAG_KEY = "INTELLIGENCE_ENABLED"

LEAD_METRICS = [
    {
        "metric_key": "total_leads_current",
        "display_name": "Total Leads",
        "unit": "count",
        "compute_method": "sql",
        "compute_spec": {
            "table": "cpq_lead",
            "filters": [{"field": "created_date", "op": "between_period"}],
            "aggregation": "count",
        },
    },
    {
        "metric_key": "total_leads_previous",
        "display_name": "Total Leads (Previous Period)",
        "unit": "count",
        "compute_method": "sql",
        "compute_spec": {
            "table": "cpq_lead",
            "filters": [{"field": "created_date", "op": "between_previous_period"}],
            "aggregation": "count",
        },
    },
    {
        "metric_key": "qualified_leads_current",
        "display_name": "Qualified Leads",
        "unit": "count",
        "compute_method": "sql",
        "compute_spec": {
            "table": "cpq_lead",
            "filters": [
                {"field": "status", "op": "in", "value": ["Qualified"]},
                {"field": "updated_date", "op": "between_period"},
            ],
            "aggregation": "count",
        },
    },
    {
        "metric_key": "qualification_rate",
        "display_name": "Qualified Lead %",
        "unit": "percent",
        "compute_method": "python",
        "compute_spec": {
            "formula": "qualified_leads_current / max(total_leads_current, 1)"
        },
    },
    {
        "metric_key": "lead_trend_percent",
        "display_name": "Lead Trend %",
        "unit": "percent",
        "compute_method": "python",
        "compute_spec": {
            "formula": "(total_leads_current - total_leads_previous) / max(total_leads_previous, 1) * 100"
        },
    },
    {
        "metric_key": "leads_by_status",
        "display_name": "Leads by Status",
        "unit": "json",
        "compute_method": "sql",
        "compute_spec": {
            "table": "cpq_lead",
            "group_by": "status",
            "aggregation": "count",
        },
    },
    {
        "metric_key": "avg_age_new_status_days",
        "display_name": "Avg Age in New (days)",
        "unit": "ratio",
        "compute_method": "python",
        "compute_spec": {
            "source": "cpq_lead",
            "logic": "average(today - created_date) for leads where status='New'",
        },
    },
    {
        "metric_key": "stale_new_count",
        "display_name": "Stale New Leads",
        "unit": "count",
        "compute_method": "python",
        "compute_spec": {
            "source": "cpq_lead",
            "logic": "count leads where status='New' and (today - created_date) > sla_days",
        },
    },
    {
        "metric_key": "pipeline_required_leads",
        "display_name": "Pipeline Required Leads",
        "unit": "count",
        "compute_method": "python",
        "compute_spec": {
            "source": "intelligence_planningconfig",
            "logic": "use PlanningConfig.pipeline_required_leads if set; else derive from derived_spec",
        },
    },
    {
        "metric_key": "coverage_health_ratio",
        "display_name": "Lead Coverage Ratio",
        "unit": "ratio",
        "compute_method": "python",
        "compute_spec": {
            "formula": "total_leads_current / max(pipeline_required_leads, 1)"
        },
    },
]

THRESHOLD_RULES_SEED = [
    {
        "rule_key": "exec_lead_drop_high",
        "domain": "leads",
        "severity": "high",
        "condition": {
            "op": "and",
            "args": [
                {"op": "<=", "left": {"metric": "lead_trend_percent"}, "right": -15}
            ],
        },
        "message_template": "Lead volume is down {{lead_trend_percent}}% this period, creating a potential pipeline risk.",
        "audience_roles": ["executive"],
    },
    {
        "rule_key": "exec_coverage_risk_high",
        "domain": "leads",
        "severity": "high",
        "condition": {
            "op": "and",
            "args": [
                {"op": "<", "left": {"metric": "coverage_health_ratio"}, "right": 1.0}
            ],
        },
        "message_template": "Lead coverage is below target ({{coverage_health_ratio}}x). This may impact forecast confidence.",
        "audience_roles": ["executive"],
    },
    {
        "rule_key": "bizops_new_sla_breach",
        "domain": "leads",
        "severity": "medium",
        "condition": {
            "op": ">",
            "left": {"metric": "stale_new_count"},
            "right": 0,
        },
        "message_template": "{{stale_new_count}} new leads are past SLA ({{sla_days}} days). This can reduce conversion rate.",
        "audience_roles": ["bizops"],
    },
    {
        "rule_key": "sales_exec_followups_due",
        "domain": "leads",
        "severity": "medium",
        "condition": {
            "op": ">",
            "left": {"metric": "stale_new_count"},
            "right": 0,
        },
        "message_template": "You have {{stale_new_count}} new leads waiting past SLA. Follow up today to prevent staleness.",
        "audience_roles": ["sales_exec"],
    },
]


def _tenant_uuid(tenant):
    return str(getattr(tenant, "tenant_id", None) or getattr(tenant, "pk", ""))


def seed_intelligence_defaults(apps, schema_editor):
    FeatureFlag = apps.get_model("intelligence", "FeatureFlag")
    MetricDefinition = apps.get_model("intelligence", "MetricDefinition")
    ThresholdRule = apps.get_model("intelligence", "ThresholdRule")
    Tenant = apps.get_model("cpq", "Tenant")

    tenants = list(Tenant.objects.all())

    for tenant in tenants:
        tenant_uuid = _tenant_uuid(tenant)

        FeatureFlag.objects.get_or_create(
            tenant_id=tenant_uuid,
            key=FEATURE_FLAG_KEY,
            defaults={"enabled": False},
        )

        for metric in LEAD_METRICS:
            MetricDefinition.objects.get_or_create(
                tenant_id=tenant_uuid,
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

        for rule in THRESHOLD_RULES_SEED:
            ThresholdRule.objects.get_or_create(
                tenant_id=tenant_uuid,
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


def unseed_intelligence_defaults(apps, schema_editor):
    FeatureFlag = apps.get_model("intelligence", "FeatureFlag")
    MetricDefinition = apps.get_model("intelligence", "MetricDefinition")
    ThresholdRule = apps.get_model("intelligence", "ThresholdRule")

    FeatureFlag.objects.filter(key=FEATURE_FLAG_KEY).delete()
    MetricDefinition.objects.filter(domain="leads").delete()
    ThresholdRule.objects.filter(domain="leads").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("intelligence", "0001_initial"),
        ("cpq", "0026_closed_won_contract_trigger"),
    ]

    operations = [
        migrations.RunPython(seed_intelligence_defaults, unseed_intelligence_defaults),
    ]
