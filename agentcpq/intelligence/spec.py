SPEC_VERSION = "1.0.0"
PRODUCT = "AgentCPQ"

FEATURE_FLAG_KEY = "INTELLIGENCE_ENABLED"
GLOBAL_OVERRIDE_ENV = "INTELLIGENCE_ENABLED_GLOBAL"

ROLE_KEYS = ["executive", "bizops", "sales_exec"]

CHAT_TRIGGERS = [
    "show me my dashboard",
    "show my dashboard",
    "lead summary",
    "how are leads doing",
    "leads status",
    "leads dashboard",
]

ENABLE_DISABLE_MESSAGES = {
    "disabled": "Intelligence is currently disabled for this tenant. An admin can enable it in Settings → Intelligence.",
    "not_configured": "Intelligence is enabled but planning targets are not configured yet. BizOps can set pipeline required leads in Settings → Intelligence → Planning.",
}

LEADS_TIMEFRAMES = {
    "supported": ["week", "month", "quarter", "year"],
    "default_by_role": {
        "executive": "week",
        "bizops": "week",
        "sales_exec": "day",
    },
}

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

NOTIFICATION_POLICY_BY_ROLE = {
    "executive": {
        "enabled": True,
        "channels": ["email", "slack"],
        "max_per_day": 1,
        "notify_on_severity": ["high"],
        "dedupe_window_hours": 24,
        "digest": {"enabled": True, "frequency": "weekly"},
    },
    "bizops": {
        "enabled": True,
        "channels": ["in_app", "slack"],
        "max_per_day": 3,
        "notify_on_severity": ["medium", "high"],
        "dedupe_window_hours": 8,
        "digest": {"enabled": True, "frequency": "daily"},
    },
    "sales_exec": {
        "enabled": True,
        "channels": ["in_app"],
        "max_per_day": 5,
        "notify_on_severity": ["medium", "high"],
        "dedupe_window_hours": 4,
        "digest": {"enabled": False},
    },
}

RESPONSE_TEMPLATES_BY_ROLE = {
    "executive": {
        "healthy": "Leads are stable and supporting the current forecast.",
        "risk": "Leads show risk signals this period. {{top_risk_sentence}}",
        "dashboard_preface": "Here’s a quick lead summary. I’ve highlighted anything that changed.",
    },
    "bizops": {
        "healthy": "Lead flow is healthy. No SLA breaches detected in the current period.",
        "risk": "Lead flow needs attention: {{top_risk_sentence}}",
        "dashboard_preface": "Here’s the operational lead view with the main bottlenecks highlighted.",
    },
    "sales_exec": {
        "healthy": "",
        "risk": "",
        "dashboard_preface": "",
    },
}

DASHBOARD_LAYOUTS = {
    "executive": {
        "layout_key": "exec_leads_summary_v1",
        "type": "kpi_grid",
        "max_cards": 4,
        "cards": [
            {
                "id": "total_leads",
                "type": "kpi",
                "title": "Total Leads",
                "value": "{{total_leads_current}}",
                "trend": "{{lead_trend_percent}}",
                "format": {"value": "int", "trend": "percent_1dp"},
                "emphasis_rules": [
                    {"when": "{{lead_trend_percent}} <= -15", "emphasis": "alert"},
                    {"when": "{{lead_trend_percent}} >= 10", "emphasis": "positive"},
                ],
            },
            {
                "id": "qualified_rate",
                "type": "kpi",
                "title": "Qualified Lead %",
                "value": "{{qualification_rate}}",
                "format": {"value": "percent_0dp"},
                "emphasis_rules": [
                    {"when": "{{qualification_rate}} < 0.35", "emphasis": "alert"}
                ],
            },
            {
                "id": "coverage",
                "type": "progress",
                "title": "Lead Coverage vs Need",
                "value": "{{coverage_health_ratio}}",
                "target": 1.0,
                "format": {"value": "ratio_2dp"},
                "labels": {"on_track": "On Track", "risk": "At Risk"},
                "emphasis_rules": [
                    {"when": "{{coverage_health_ratio}} < 1.0", "emphasis": "alert"}
                ],
            },
            {
                "id": "lead_health",
                "type": "status_badge",
                "title": "Lead Health",
                "value": "{{computed_risk_status}}",
                "states": ["Healthy", "At Risk"],
                "emphasis_rules": [
                    {"when": "{{computed_risk_status}} == 'At Risk'", "emphasis": "alert"}
                ],
            },
        ],
        "no_drilldowns": True,
        "no_filters": True,
    },
    "bizops": {
        "layout_key": "bizops_leads_ops_v1",
        "type": "stacked_sections",
        "sections": [
            {
                "id": "kpis",
                "type": "kpi_row",
                "cards": [
                    {
                        "id": "total_leads",
                        "type": "kpi",
                        "title": "Total Leads",
                        "value": "{{total_leads_current}}",
                        "trend": "{{lead_trend_percent}}",
                        "format": {"value": "int", "trend": "percent_1dp"},
                    },
                    {
                        "id": "qualification_rate",
                        "type": "kpi",
                        "title": "Qualified Lead %",
                        "value": "{{qualification_rate}}",
                        "format": {"value": "percent_0dp"},
                    },
                    {
                        "id": "avg_age_new",
                        "type": "kpi",
                        "title": "Avg Age in New (days)",
                        "value": "{{avg_age_new_status_days}}",
                        "format": {"value": "ratio_1dp"},
                    },
                ],
            },
            {
                "id": "by_status",
                "type": "bar_list",
                "title": "Leads by Status",
                "source": "{{leads_by_status}}",
                "bar_style": "horizontal_segment",
                "show_counts": True,
                "no_pie": True,
            },
            {
                "id": "sla",
                "type": "callout",
                "title": "SLA Watch",
                "body": "{{stale_new_count}} leads are past SLA ({{sla_days}} day(s)).",
            },
        ],
        "drilldown_allowed": "role_based",
        "filters_allowed": False,
    },
    "sales_exec": {
        "layout_key": "sales_exec_leads_actions_v1",
        "type": "action_panel",
        "sections": [
            {
                "id": "today_actions",
                "type": "callout",
                "title": "Today’s Focus",
                "body": "Action needed: {{stale_new_count}} new leads are past SLA ({{sla_days}} day(s)). Follow up today to prevent staleness. Move them to Qualified where appropriate.",
            },
            {
                "id": "sla_alert",
                "type": "kpi",
                "title": "Overdue New Leads",
                "value": "{{stale_new_count}}",
                "format": {"value": "int"},
                "emphasis_rules": [
                    {"when": "{{stale_new_count}} > 0", "emphasis": "alert"}
                ],
            },
            {
                "id": "by_status",
                "type": "bar_list",
                "title": "Leads by Status",
                "source": "{{leads_by_status}}",
                "bar_style": "horizontal_segment",
                "show_counts": True,
            },
        ],
        "no_tables": True,
        "no_charts_axes": True,
    },
}

COMPUTED_FIELDS = [
    {
        "field_key": "computed_risk_status",
        "compute_method": "python",
        "logic": "if (coverage_health_ratio < 1.0) or (lead_trend_percent <= -15) then 'At Risk' else 'Healthy'",
    },
    {
        "field_key": "sla_days",
        "compute_method": "config",
        "logic": "read LEADS_NEW_SLA_DAYS from business_owned_inputs.sla_config",
    },
    {
        "field_key": "top_risk_sentence",
        "compute_method": "python",
        "logic": "select highest severity triggered ThresholdRule message_template rendered with metrics",
    },
]

BUSINESS_OWNED_INPUTS = {
    "planning_config": {
        "model": "intelligence.PlanningConfig",
        "ownership": "bizops",
        "required_fields_minimum": ["timeframe_key", "period_start", "period_end"],
        "recommended_fields": ["pipeline_required_leads"],
        "derivation_allowed": True,
    },
    "sla_config": {
        "key": "LEADS_NEW_SLA_DAYS",
        "default": 1,
        "owner_role": "bizops",
    },
}
