from __future__ import annotations

import re
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from dateutil.relativedelta import relativedelta

from cpq.models import Tenant

from .feature_flags import is_intelligence_enabled, tenant_uuid_from_tenant
from .metrics import compute_leads_metrics, compute_leads_metrics_for_timeframe, get_sla_days
from .models import MetricDefinition, MetricSnapshot, ThresholdRule
from .notifications import get_user_role_key
from .spec import (
    CHAT_TRIGGERS,
    DASHBOARD_LAYOUTS,
    ENABLE_DISABLE_MESSAGES,
    LEADS_TIMEFRAMES,
    RESPONSE_TEMPLATES_BY_ROLE,
)
from .thresholds import evaluate_condition, render_template, select_top_risk_sentence
from .timeframes import current_period_range, previous_period_range, fiscal_label_year
from .seed import ensure_intelligence_defaults


TIMEFRAME_PATTERN = re.compile(
    r"\b(day|daily|week|weekly|month|monthly|quarter|quarterly|year|years|yearly|annual|annually)\b",
    re.IGNORECASE,
)
YEAR_SPAN_PATTERN = re.compile(r"\b(\d+)\s+years?\b", re.IGNORECASE)
FISCAL_KEYWORD_PATTERN = re.compile(r"\b(fy|fiscal year|fiscal-year|fiscal)\b", re.IGNORECASE)
FY_LABEL_PATTERN = re.compile(r"\bfy\s*([0-9]{2,4})\b", re.IGNORECASE)
FISCAL_SPAN_PATTERN = re.compile(r"\b(\d+)\s+(?:fiscal\s+)?years?\b", re.IGNORECASE)
DATE_TOKEN_PATTERN = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})"
DATE_RANGE_PATTERN = re.compile(
    rf"\b(?:from|between)\s+({DATE_TOKEN_PATTERN})\s+(?:to|and|through|until)\s+({DATE_TOKEN_PATTERN})\b",
    re.IGNORECASE,
)
DATE_TO_DATE_PATTERN = re.compile(
    rf"\b({DATE_TOKEN_PATTERN})\s*(?:to|through|until|-)\s*({DATE_TOKEN_PATTERN})\b",
    re.IGNORECASE,
)
DATE_SINCE_PATTERN = re.compile(rf"\b(?:since|after|from)\s+({DATE_TOKEN_PATTERN})\b", re.IGNORECASE)
RELATIVE_RANGE_PATTERN = re.compile(
    r"\b(?:last|past)\s+(\d+)\s+(days?|weeks?|months?|quarters?|years?)\b",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


def _parse_timeframe_override(message: str) -> str | None:
    if not message:
        return None
    match = TIMEFRAME_PATTERN.search(message)
    if not match:
        return None
    token = match.group(1).lower()
    if token in {"day", "daily"}:
        return "day"
    if token in {"week", "weekly"}:
        return "week"
    if token in {"month", "monthly"}:
        return "month"
    if token in {"quarter", "quarterly"}:
        return "quarter"
    if token in {"year", "years", "yearly", "annual", "annually"}:
        return "year"
    return None


def _parse_date_token(token: str) -> date | None:
    token = token.strip()
    if not token:
        return None
    if "-" in token:
        try:
            return date.fromisoformat(token)
        except ValueError:
            return None
    if "/" in token:
        parts = token.split("/")
        if len(parts) != 3:
            return None
        try:
            month = int(parts[0])
            day = int(parts[1])
            year = int(parts[2])
        except ValueError:
            return None
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _parse_explicit_date_range(message: str) -> tuple[date, date] | None:
    if not message:
        return None
    lowered = message.lower()
    if "all time" in lowered or "all-time" in lowered or "lifetime" in lowered:
        return date(1970, 1, 1), timezone.now().date()

    match = DATE_RANGE_PATTERN.search(message)
    if not match:
        match = DATE_TO_DATE_PATTERN.search(message)
    if match:
        start = _parse_date_token(match.group(1))
        end = _parse_date_token(match.group(2))
        if start and end:
            if start > end:
                start, end = end, start
            return start, end

    match = DATE_SINCE_PATTERN.search(message)
    if match:
        start = _parse_date_token(match.group(1))
        if start:
            return start, timezone.now().date()
    return None


def _parse_relative_date_range(message: str) -> tuple[date, date] | None:
    if not message:
        return None
    lowered = message.lower()
    today = timezone.now().date()
    match = RELATIVE_RANGE_PATTERN.search(lowered)
    if match:
        try:
            span = max(int(match.group(1)), 1)
        except ValueError:
            span = 1
        unit = match.group(2).lower()
        if unit.startswith("year"):
            return None
        if unit.startswith("day"):
            return today - timedelta(days=span - 1), today
        if unit.startswith("week"):
            return today - timedelta(days=(span * 7) - 1), today
        if unit.startswith("month"):
            return today - relativedelta(months=span), today
        if unit.startswith("quarter"):
            return today - relativedelta(months=span * 3), today

    for token, key in (
        ("last week", "week"),
        ("previous week", "week"),
        ("past week", "week"),
        ("last month", "month"),
        ("previous month", "month"),
        ("past month", "month"),
        ("last quarter", "quarter"),
        ("previous quarter", "quarter"),
        ("past quarter", "quarter"),
    ):
        if token in lowered:
            current_start, current_end = current_period_range(key, today)
            return previous_period_range(key, current_start, current_end)
    return None


def _parse_custom_date_range(message: str) -> tuple[date, date] | None:
    explicit = _parse_explicit_date_range(message)
    if explicit:
        return explicit
    return _parse_relative_date_range(message)


def _parse_year_span(message: str) -> tuple[int, int] | None:
    if not message:
        return None
    lowered = message.lower()
    span = None
    match = YEAR_SPAN_PATTERN.search(lowered)
    if match:
        try:
            span = max(int(match.group(1)), 1)
        except ValueError:
            span = None
    if "last year" in lowered or "previous year" in lowered:
        return 1, 1
    if span:
        if "last" in lowered or "previous" in lowered:
            return span, 1
        return span, 0
    if "this year" in lowered:
        return 1, 0
    if "year" in lowered or "annual" in lowered:
        return 1, 0
    return None


def _parse_fiscal_context(message: str, tenant: Tenant) -> dict | None:
    if not message:
        return None
    lowered = message.lower()
    if not (FISCAL_KEYWORD_PATTERN.search(lowered) or FY_LABEL_PATTERN.search(lowered)):
        return None

    start_month = int(getattr(tenant, "fiscal_year_start_month", 1) or 1)
    label_mode = getattr(tenant, "fiscal_year_label_mode", "start")
    label_mode = label_mode if label_mode in {"start", "end"} else "start"
    current_label = fiscal_label_year(timezone.now().date(), start_month, label_mode)

    span = None
    year_offset = 0
    end_label_year = None

    label_match = FY_LABEL_PATTERN.search(lowered)
    if label_match:
        token = label_match.group(1)
        try:
            label_year = int(token)
        except ValueError:
            label_year = current_label
        if len(token) == 2:
            label_year += 2000
        end_label_year = label_year
        year_offset = max(current_label - label_year, 0)
    else:
        span_match = FISCAL_SPAN_PATTERN.search(lowered)
        if span_match:
            try:
                span = max(int(span_match.group(1)), 1)
            except ValueError:
                span = None

        if "last fy" in lowered or "previous fy" in lowered or "last fiscal year" in lowered or "previous fiscal year" in lowered:
            year_offset = 1
        elif "this fy" in lowered or "current fy" in lowered or "this fiscal year" in lowered or "current fiscal year" in lowered:
            year_offset = 0
        elif span and ("last" in lowered or "previous" in lowered):
            year_offset = 1
        else:
            year_offset = 0

        end_label_year = current_label - year_offset

    if span is None:
        span = 1

    return {
        "year_span": span,
        "year_offset": year_offset,
        "fiscal_start_month": start_month,
        "fiscal_label_mode": label_mode,
        "fiscal_end_label_year": end_label_year,
    }


def _resolve_role_key(user) -> str:
    return get_user_role_key(user) or "sales_exec"


def _resolve_timeframe(role_key: str, override: str | None) -> str:
    if override:
        return override
    defaults = LEADS_TIMEFRAMES.get("default_by_role", {})
    return defaults.get(role_key, "week")


def _normalize_metric_value(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _load_metric_snapshots(tenant_uuid, timeframe_key: str, period_start, period_end):
    return MetricSnapshot.objects.filter(
        tenant_id=tenant_uuid,
        domain="leads",
        timeframe_key=timeframe_key,
        period_start=period_start,
        period_end=period_end,
    )


def _build_metrics_from_snapshots(snapshots):
    metrics = {}
    for snap in snapshots:
        if snap.value_json is not None:
            metrics[snap.metric_key] = snap.value_json
        else:
            metrics[snap.metric_key] = snap.value_number
    return metrics


def _ensure_metrics(
    tenant,
    timeframe_key: str,
    *,
    period_start_override: date | None = None,
    period_end_override: date | None = None,
    year_span: int = 1,
    year_offset: int = 0,
    use_fiscal: bool = False,
    fiscal_start_month: int = 1,
    fiscal_label_mode: str = "start",
    fiscal_end_label_year: int | None = None,
):
    if period_start_override and period_end_override:
        period_start = period_start_override
        period_end = period_end_override
    else:
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
    tenant_uuid = tenant_uuid_from_tenant(tenant)
    snapshots = _load_metric_snapshots(tenant_uuid, timeframe_key, period_start, period_end)
    metric_defs = MetricDefinition.objects.filter(
        tenant_id=tenant_uuid,
        domain="leads",
        is_active=True,
    )
    if not metric_defs.exists():
        logger.warning(
            "No MetricDefinition rows found; seeding defaults for tenant_id=%s",
            tenant_uuid,
        )
        ensure_intelligence_defaults(tenant_uuid)
        metric_defs = MetricDefinition.objects.filter(
            tenant_id=tenant_uuid,
            domain="leads",
            is_active=True,
        )
    logger.info(
        "Ensure metrics tenant_id=%s timeframe=%s period=%s..%s span=%s offset=%s fiscal=%s snapshots=%s defs=%s",
        tenant_uuid,
        timeframe_key,
        period_start,
        period_end,
        year_span,
        year_offset,
        use_fiscal,
        snapshots.count(),
        metric_defs.count(),
    )
    if snapshots.count() < metric_defs.count():
        logger.info(
            "Missing snapshots tenant_id=%s timeframe=%s span=%s offset=%s expected=%s found=%s; recomputing",
            tenant_uuid,
            timeframe_key,
            year_span,
            year_offset,
            metric_defs.count(),
            snapshots.count(),
        )
        if period_start_override and period_end_override:
            metrics, computed_snapshots = compute_leads_metrics(
                tenant,
                timeframe_key,
                period_start,
                period_end,
                year_span=year_span,
                use_fiscal=use_fiscal,
                fiscal_start_month=fiscal_start_month,
                fiscal_label_mode=fiscal_label_mode,
            )
        else:
            metrics, computed_snapshots, period_start, period_end = compute_leads_metrics_for_timeframe(
                tenant,
                timeframe_key,
                year_span=year_span,
                year_offset=year_offset,
                use_fiscal=use_fiscal,
                fiscal_start_month=fiscal_start_month,
                fiscal_label_mode=fiscal_label_mode,
                fiscal_end_label_year=fiscal_end_label_year,
            )
        for snapshot in computed_snapshots:
            MetricSnapshot.objects.update_or_create(
                tenant_id=tenant_uuid,
                domain="leads",
                metric_key=snapshot["metric_key"],
                timeframe_key=timeframe_key,
                period_start=period_start,
                period_end=period_end,
                defaults={
                    "value_number": snapshot["value_number"],
                    "value_json": snapshot["value_json"],
                    "generated_at": timezone.now(),
                    "source_fingerprint": f"{snapshot['metric_key']}:{period_start}:{period_end}",
                },
            )
        snapshots = _load_metric_snapshots(tenant_uuid, timeframe_key, period_start, period_end)
    return snapshots, period_start, period_end


def _compute_changed_fields(
    tenant_uuid,
    timeframe_key: str,
    period_start,
    period_end,
    metrics: dict,
    *,
    year_span: int = 1,
    use_fiscal: bool = False,
    fiscal_start_month: int = 1,
    fiscal_label_mode: str = "start",
    fiscal_end_label_year: int | None = None,
):
    prev_start, prev_end = previous_period_range(
        timeframe_key,
        period_start,
        period_end,
        year_span=year_span,
        use_fiscal=use_fiscal,
        fiscal_start_month=fiscal_start_month,
        fiscal_label_mode=fiscal_label_mode,
        fiscal_end_label_year=fiscal_end_label_year,
    )
    previous = MetricSnapshot.objects.filter(
        tenant_id=tenant_uuid,
        domain="leads",
        timeframe_key=timeframe_key,
        period_start=prev_start,
        period_end=prev_end,
    )
    if not previous.exists():
        return []
    previous_metrics = _build_metrics_from_snapshots(previous)
    changed = []
    for key, value in metrics.items():
        if key not in previous_metrics:
            continue
        if previous_metrics.get(key) != value:
            changed.append(key)
    return changed


def _compute_risk_status(metrics: dict) -> str:
    coverage = metrics.get("coverage_health_ratio") or 0
    trend = metrics.get("lead_trend_percent") or 0
    try:
        coverage_val = float(coverage)
        trend_val = float(trend)
    except (TypeError, ValueError):
        return "Healthy"
    if coverage_val < 1.0 or trend_val <= -15:
        return "At Risk"
    return "Healthy"


def _limit_sentences(message: str, max_sentences: int) -> str:
    if not message:
        return message
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", message) if part.strip()]
    if len(parts) <= max_sentences:
        return message
    return " ".join(parts[:max_sentences]).strip()


def _format_percent(value, decimals: int = 0) -> str | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    normalized = num * 100 if abs(num) <= 1 else num
    return f"{normalized:.{decimals}f}%"


def _format_ratio(value, decimals: int = 2) -> str | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return f"{num:.{decimals}f}"


def _build_exec_explanation(metrics: dict) -> str | None:
    parts = []
    coverage = metrics.get("coverage_health_ratio")
    qual = metrics.get("qualification_rate")
    trend = metrics.get("lead_trend_percent")

    coverage_text = _format_ratio(coverage, 2)
    if coverage_text is not None and float(coverage) < 1.0:
        parts.append(f"coverage below target at {coverage_text}x")

    qual_text = _format_percent(qual, 0)
    if qual_text is not None:
        try:
            qual_val = float(qual)
        except (TypeError, ValueError):
            qual_val = None
        if qual_val is not None and qual_val < 0.35:
            parts.append(f"qualified rate low at {qual_text}")

    trend_text = _format_percent(trend, 1)
    if trend_text is not None:
        try:
            trend_val = float(trend)
        except (TypeError, ValueError):
            trend_val = None
        if trend_val is not None and trend_val <= -15:
            parts.append(f"lead trend down {trend_text}")

    if parts:
        return f"Drivers: {', '.join(parts)}."

    if coverage_text and qual_text:
        return f"Coverage is {coverage_text}x with qualified rate at {qual_text}."
    if coverage_text:
        return f"Coverage is {coverage_text}x."
    if qual_text:
        return f"Qualified rate is {qual_text}."
    return None


def lead_intelligence_agent(user, action, user_message, session_data):
    tenant = Tenant.safe_first()
    if not tenant or not is_intelligence_enabled(tenant):
        return {"message": ENABLE_DISABLE_MESSAGES["disabled"]}

    role_key = _resolve_role_key(user)
    custom_range = _parse_custom_date_range(user_message)
    fiscal_context = _parse_fiscal_context(user_message, tenant)
    override = _parse_timeframe_override(user_message)
    if custom_range:
        timeframe_key = "custom"
        year_span = 1
        year_offset = 0
        use_fiscal = False
        fiscal_start_month = 1
        fiscal_label_mode = "start"
        fiscal_end_label_year = None
        period_start_override, period_end_override = custom_range
    elif fiscal_context:
        timeframe_key = "year"
        year_span = fiscal_context["year_span"]
        year_offset = fiscal_context["year_offset"]
        use_fiscal = True
        fiscal_start_month = fiscal_context["fiscal_start_month"]
        fiscal_label_mode = fiscal_context["fiscal_label_mode"]
        fiscal_end_label_year = fiscal_context["fiscal_end_label_year"]
        period_start_override = None
        period_end_override = None
    else:
        timeframe_key = _resolve_timeframe(role_key, override)
        year_span = 1
        year_offset = 0
        use_fiscal = False
        fiscal_start_month = 1
        fiscal_label_mode = "start"
        fiscal_end_label_year = None
        period_start_override = None
        period_end_override = None
        if timeframe_key == "year":
            parsed_span = _parse_year_span(user_message)
            if parsed_span:
                year_span, year_offset = parsed_span
    logger.info(
        "Lead intelligence start tenant_id=%s role=%s timeframe=%s override=%s span=%s offset=%s fiscal=%s",
        getattr(tenant, "tenant_id", None),
        role_key,
        timeframe_key,
        override,
        year_span,
        year_offset,
        use_fiscal,
    )

    snapshots, period_start, period_end = _ensure_metrics(
        tenant,
        timeframe_key,
        period_start_override=period_start_override,
        period_end_override=period_end_override,
        year_span=year_span,
        year_offset=year_offset,
        use_fiscal=use_fiscal,
        fiscal_start_month=fiscal_start_month,
        fiscal_label_mode=fiscal_label_mode,
        fiscal_end_label_year=fiscal_end_label_year,
    )
    tenant_uuid = tenant_uuid_from_tenant(tenant)
    metrics = _build_metrics_from_snapshots(snapshots)
    metrics["sla_days"] = get_sla_days(tenant)
    metrics["coverage_health_ratio"] = metrics.get("coverage_health_ratio") or 0
    metrics["lead_trend_percent"] = metrics.get("lead_trend_percent") or 0
    logger.info(
        "Lead intelligence metrics tenant_id=%s period=%s..%s pipeline_required_leads=%s fiscal=%s",
        tenant_uuid,
        period_start,
        period_end,
        metrics.get("pipeline_required_leads"),
        use_fiscal,
    )

    triggered_rules = []
    rules = ThresholdRule.objects.filter(
        tenant_id=tenant_uuid,
        domain="leads",
        is_active=True,
    )
    for rule in rules:
        if role_key not in (rule.audience_roles or []):
            continue
        if evaluate_condition(rule.condition, metrics):
            triggered_rules.append(
                {
                    "rule_key": rule.rule_key,
                    "severity": rule.severity,
                    "message_template": rule.message_template,
                    "audience_roles": rule.audience_roles,
                }
            )

    top_risk_sentence = select_top_risk_sentence(triggered_rules, metrics)
    computed_risk_status = _compute_risk_status(metrics)
    metrics["computed_risk_status"] = computed_risk_status
    metrics["top_risk_sentence"] = top_risk_sentence

    if metrics.get("pipeline_required_leads") is None:
        logger.warning(
            "Lead intelligence not configured tenant_id=%s timeframe=%s period=%s..%s fiscal=%s",
            tenant_uuid,
            timeframe_key,
            period_start,
            period_end,
            use_fiscal,
        )
        return {"message": ENABLE_DISABLE_MESSAGES["not_configured"]}

    templates = RESPONSE_TEMPLATES_BY_ROLE.get(role_key, {})
    preface = templates.get("dashboard_preface", "")
    if triggered_rules:
        base = templates.get("risk", "")
    else:
        base = templates.get("healthy", "")
    base = render_template(base, metrics)
    message = " ".join([part for part in [preface, base] if part]).strip()
    if role_key == "executive":
        explanation = _build_exec_explanation(metrics)
        if explanation:
            message = f"{message} {explanation}"
        message = _limit_sentences(message, 3)

    layout = DASHBOARD_LAYOUTS.get(role_key, {})
    changed_fields = _compute_changed_fields(
        tenant_uuid,
        timeframe_key,
        period_start,
        period_end,
        metrics,
        year_span=year_span,
        use_fiscal=use_fiscal,
        fiscal_start_month=fiscal_start_month,
        fiscal_label_mode=fiscal_label_mode,
        fiscal_end_label_year=fiscal_end_label_year,
    )

    payload = {
        "layout_key": layout.get("layout_key"),
        "type": layout.get("type"),
        "data": {
            "layout": layout,
            "metrics": {k: _normalize_metric_value(v) for k, v in metrics.items()},
            "role_key": role_key,
            "timeframe_key": timeframe_key,
            "period_start": str(period_start),
            "period_end": str(period_end),
            "changed_fields": changed_fields,
        },
        "render_hints": {
            "highlight_changed_fields": True,
            "no_static_links_required": True,
            "supports_dark_mode": True,
        },
    }

    return {
        "message": message,
        "intelligence_dashboard": payload,
    }


def matches_lead_intelligence_trigger(message: str) -> bool:
    lowered = (message or "").strip().lower()
    return any(trigger in lowered for trigger in CHAT_TRIGGERS)
