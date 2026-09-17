"""Business dashboard metrics for the CPQ admin.

All numbers are computed server-side from the CPQ models and returned as a
plain dict so the admin template can render KPI cards, tables and charts.

Conventions:
- Revenue = Closed-Won opportunities (``Opportunity.stage == "closedwon"``).
- Periods use ``expected_close_date`` (the closest thing the model has to an
  actual close date).
- Open pipeline = every stage except Closed Won / Closed Lost / Disqualified.
- Weighted forecast = open amount x stage probability (``OpportunityStage.probability``).
- Active customer = an Account that purchased in the trailing 12 months
  (won opportunity or subscription start).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

NOT_OPEN_STAGES = ("closedwon", "closedlost", "disqualified")
WON_STAGE = "closedwon"
LOST_STAGE = "closedlost"

DEFAULT_STAGE_PROBABILITIES = {
    "appointmentscheduled": 10,
    "qualifiedtobuy": 20,
    "presentationscheduled": 40,
    "decisionmakerboughtin": 60,
    "contractsent": 80,
    "disqualified": 0,
    "closedwon": 100,
    "closedlost": 0,
}

MONEY_FIELD = DecimalField(max_digits=18, decimal_places=2)


def _money_sum(field: str):
    """Coalesced decimal SUM with an explicit output field (MySQL/SQLite safe)."""
    return Coalesce(Sum(field), Decimal("0"), output_field=MONEY_FIELD)


OPEN_QUOTE_STATUSES = ("Draft", "Forecast", "Pending Approval", "Approved")
ACTIVITY_LABELS = {
    "call": "Call",
    "email": "Email",
    "meeting": "Meeting",
    "task": "Task",
}
LEAD_STATUS_ORDER = ["new", "qualified", "converted", "disqualified"]
LEAD_STATUS_LABELS = {
    "new": "New",
    "qualified": "Qualified",
    "converted": "Converted",
    "disqualified": "Disqualified",
}


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, 28)
    return date(year, month, day)


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _quarter_start(value: date) -> date:
    first_month = ((value.month - 1) // 3) * 3 + 1
    return date(value.year, first_month, 1)


def _money(value) -> str:
    number = Decimal(str(value or 0))
    return f"{number:,.0f}"


def _money2(value) -> str:
    number = Decimal(str(value or 0))
    return f"{number:,.2f}"


def _pct(part, whole) -> str:
    if not whole:
        return "0%"
    return f"{(Decimal(str(part)) / Decimal(str(whole)) * 100):.0f}%"


# ---------------------------------------------------------------------------
# Small query helpers (never raise — the dashboard must always render)
# ---------------------------------------------------------------------------
def _sum(queryset, field="amount"):
    try:
        return queryset.aggregate(total=_money_sum(field))["total"] or 0
    except Exception:
        return 0


def _count(queryset):
    try:
        return queryset.count()
    except Exception:
        return 0


def _stage_rows():
    """Active stages in display order with their probabilities."""
    from .models import OpportunityStage

    rows = []
    try:
        for stage in OpportunityStage.objects.filter(active=True).order_by("sort_order", "key"):
            rows.append(
                {
                    "key": stage.key,
                    "label": stage.label or stage.key,
                    "probability": stage.probability if stage.probability is not None else 50,
                    "is_closed": stage.key in (WON_STAGE, LOST_STAGE, "disqualified"),
                }
            )
    except Exception:
        rows = []

    if rows:
        return rows

    return [
        {
            "key": key,
            "label": key.replace("_", " ").title(),
            "probability": DEFAULT_STAGE_PROBABILITIES.get(key, 50),
            "is_closed": key in (WON_STAGE, LOST_STAGE, "disqualified"),
        }
        for key in DEFAULT_STAGE_PROBABILITIES
    ]


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------
def build_business_dashboard_context() -> dict:
    from .models import (
        Account,
        Activity,
        Lead,
        Opportunity,
        Quote,
        Subscription,
    )

    today = timezone.localdate()
    month_start = _month_start(today)
    quarter_start = _quarter_start(today)
    year_start = date(today.year, 1, 1)
    ttm_start = _add_months(today, -12)

    opportunities = Opportunity.objects.all()
    won = opportunities.filter(stage=WON_STAGE)
    lost = opportunities.filter(stage=LOST_STAGE)
    disqualified = opportunities.filter(stage="disqualified")
    open_opps = opportunities.exclude(stage__in=NOT_OPEN_STAGES)

    won_ttm = won.filter(expected_close_date__gte=ttm_start)
    won_month = won.filter(expected_close_date__gte=month_start, expected_close_date__lte=today)
    won_quarter = won.filter(expected_close_date__gte=quarter_start, expected_close_date__lte=today)
    won_year = won.filter(expected_close_date__gte=year_start, expected_close_date__lte=today)

    revenue_all = _sum(won)
    revenue_ttm = _sum(won_ttm)
    open_count = _count(open_opps)
    open_value = _sum(open_opps)

    # --- Weighted forecast -------------------------------------------------
    stages = _stage_rows()
    probability_by_key = {row["key"]: row["probability"] for row in stages}
    by_stage = {}
    try:
        for row in opportunities.values("stage").annotate(count=Count("id"), value=_money_sum("amount")):
            by_stage[row["stage"]] = row
    except Exception:
        by_stage = {}

    weighted_forecast = Decimal("0")
    pipeline_by_stage = []
    for stage in stages:
        row = by_stage.get(stage["key"], {})
        value = Decimal(str(row.get("value") or 0))
        weighted = value * Decimal(stage["probability"]) / Decimal(100)
        if not stage["is_closed"]:
            weighted_forecast += weighted
        pipeline_by_stage.append(
            {
                **stage,
                "count": row.get("count") or 0,
                "value": value,
                "value_display": _money(value),
                "weighted_display": _money(weighted) if not stage["is_closed"] else "—",
            }
        )

    weighted_forecast_90 = Decimal("0")
    try:
        forecast_qs = open_opps.filter(
            expected_close_date__gte=today,
            expected_close_date__lte=today + timedelta(days=90),
        ).values("stage").annotate(value=_money_sum("amount"))
        for row in forecast_qs:
            weighted_forecast_90 += (
                Decimal(str(row.get("value") or 0))
                * Decimal(probability_by_key.get(row["stage"], 50))
                / Decimal(100)
            )
    except Exception:
        pass

    # --- Win rate / deal size ---------------------------------------------
    won_ttm_count = _count(won_ttm)
    lost_ttm_count = _count(lost.filter(expected_close_date__gte=ttm_start))
    disq_ttm_count = _count(disqualified.filter(expected_close_date__gte=ttm_start))
    closed_total = won_ttm_count + lost_ttm_count + disq_ttm_count
    avg_deal_size = (Decimal(str(revenue_ttm)) / won_ttm_count) if won_ttm_count else Decimal("0")

    # --- Revenue by month (trailing 12) -----------------------------------
    revenue_labels = []
    revenue_values = []
    won_lost_labels = []
    won_values = []
    lost_values = []
    monthly_map = {}
    try:
        for row in (
            won.filter(expected_close_date__gte=_add_months(month_start, -11), expected_close_date__lte=today)
            .annotate(bucket=TruncMonth("expected_close_date"))
            .values("bucket")
            .annotate(total=_money_sum("amount"))
        ):
            if row["bucket"]:
                monthly_map[row["bucket"].strftime("%Y-%m")] = row["total"]

        won_month_map = {}
        for row in (
            won_ttm.annotate(bucket=TruncMonth("expected_close_date"))
            .values("bucket")
            .annotate(total=_money_sum("amount"), count=Count("id"))
        ):
            if row["bucket"]:
                won_month_map[row["bucket"].strftime("%Y-%m")] = row

        lost_month_map = {}
        for row in (
            lost.filter(expected_close_date__gte=ttm_start)
            .annotate(bucket=TruncMonth("expected_close_date"))
            .values("bucket")
            .annotate(count=Count("id"))
        ):
            if row["bucket"]:
                lost_month_map[row["bucket"].strftime("%Y-%m")] = row
    except Exception:
        monthly_map, won_month_map, lost_month_map = {}, {}, {}

    for offset in range(11, -1, -1):
        bucket = _add_months(month_start, -offset)
        key = bucket.strftime("%Y-%m")
        label = bucket.strftime("%b %y")
        revenue_labels.append(label)
        revenue_values.append(float(monthly_map.get(key, 0)))
        won_lost_labels.append(label)
        won_values.append(won_month_map.get(key, {}).get("count", 0))
        lost_values.append(lost_month_map.get(key, {}).get("count", 0))

    # --- Lead funnel -------------------------------------------------------
    lead_counts = {status: 0 for status in LEAD_STATUS_ORDER}
    try:
        for row in Lead.objects.values("status").annotate(count=Count("id")):
            lead_counts[row["status"]] = row["count"]
    except Exception:
        pass
    lead_total = sum(lead_counts.values())
    lead_funnel = [
        {
            "key": status,
            "label": LEAD_STATUS_LABELS.get(status, status.title()),
            "count": lead_counts.get(status, 0),
            "share": (lead_counts.get(status, 0) / lead_total * 100) if lead_total else 0,
        }
        for status in LEAD_STATUS_ORDER
    ]
    leads_month = _count(Lead.objects.filter(created_at__date__gte=month_start))

    leads_by_source = []
    try:
        for row in (
            Lead.objects.exclude(source="")
            .exclude(source__isnull=True)
            .values("source")
            .annotate(count=Count("id"))
            .order_by("-count")[:6]
        ):
            leads_by_source.append({"label": row["source"], "count": row["count"]})
    except Exception:
        pass

    # --- Quotes ------------------------------------------------------------
    quotes = Quote.objects.all()
    open_quotes = quotes.filter(status__in=OPEN_QUOTE_STATUSES)
    quote_status_rows = []
    try:
        for row in quotes.values("status").annotate(count=Count("id"), value=_money_sum("net_amount")):
            quote_status_rows.append(
                {
                    "label": row["status"] or "—",
                    "count": row["count"],
                    "value": row["value"],
                }
            )
    except Exception:
        pass

    pending_quotes = quotes.filter(status="Pending Approval")
    expiring_soon = _count(
        open_quotes.filter(
            expiration_date__isnull=False,
            expiration_date__date__gte=today,
            expiration_date__date__lte=today + timedelta(days=30),
        )
    )
    avg_quote = 0
    try:
        open_quote_count = _count(open_quotes)
        if open_quote_count:
            avg_quote = _sum(open_quotes, "net_amount") / open_quote_count
    except Exception:
        avg_quote = 0

    avg_discount = 0
    try:
        discounted = quotes.filter(discount_percentage__gt=0)
        agg = discounted.aggregate(avg=Sum("discount_percentage"), count=Count("id"))
        if agg["count"]:
            avg_discount = agg["avg"] / agg["count"]
    except Exception:
        avg_discount = 0

    # --- Customers ---------------------------------------------------------
    ttm_account_ids = set()
    month_account_ids = set()
    try:
        ttm_account_ids.update(
            won_ttm.exclude(account_id__isnull=True).values_list("account_id", flat=True)
        )
        month_account_ids.update(
            won_month.exclude(account_id__isnull=True).values_list("account_id", flat=True)
        )
        sub_accounts = Subscription.objects.filter(start_date__gte=ttm_start).values_list(
            "quote__account_id", flat=True
        )
        ttm_account_ids.update(account_id for account_id in sub_accounts if account_id)
        sub_accounts_month = Subscription.objects.filter(start_date__gte=month_start).values_list(
            "quote__account_id", flat=True
        )
        month_account_ids.update(account_id for account_id in sub_accounts_month if account_id)
    except Exception:
        pass

    top_customers = []
    try:
        for row in (
            won_ttm.values("account__name")
            .annotate(total=_money_sum("amount"), deals=Count("id"))
            .order_by("-total")[:8]
        ):
            top_customers.append(
                {
                    "name": row["account__name"] or "—",
                    "total": row["total"],
                    "total_display": _money(row["total"]),
                    "deals": row["deals"],
                }
            )
    except Exception:
        pass

    # --- Subscriptions -----------------------------------------------------
    active_subscriptions = 0
    mrr = Decimal("0")
    renewals_due = 0
    try:
        subscriptions = Subscription.objects.filter(status="Active")
        active_subscriptions = _count(subscriptions)
        for sub in subscriptions.only("billing_cycle", "price_per_cycle", "end_date"):
            price = Decimal(str(sub.price_per_cycle or 0))
            cycle = (sub.billing_cycle or "monthly").lower()
            if cycle == "monthly":
                mrr += price
            elif cycle == "quarterly":
                mrr += price / Decimal(3)
            elif cycle == "annual":
                mrr += price / Decimal(12)
        renewals_due = _count(
            subscriptions.filter(
                end_date__gte=today,
                end_date__lte=today + timedelta(days=90),
            )
        )
    except Exception:
        pass

    # --- Activities --------------------------------------------------------
    activity_mix = []
    try:
        since = timezone.now() - timedelta(days=30)
        for row in (
            Activity.objects.filter(created_at__gte=since)
            .values("activity_type")
            .annotate(count=Count("id"))
            .order_by("-count")
        ):
            activity_mix.append(
                {
                    "label": ACTIVITY_LABELS.get(row["activity_type"], row["activity_type"]),
                    "count": row["count"],
                }
            )
    except Exception:
        pass
    activities_30d = sum(row["count"] for row in activity_mix)
    overdue_activities = _count(
        Activity.objects.filter(due_date__lt=today).exclude(status="completed")
    )

    # --- Rep leaderboard ---------------------------------------------------
    leaderboard = []
    try:
        for row in (
            won_ttm.exclude(owner__isnull=True)
            .values("owner__username")
            .annotate(revenue=_money_sum("amount"), deals=Count("id"))
            .order_by("-revenue")[:8]
        ):
            leaderboard.append(
                {
                    "name": row["owner__username"],
                    "revenue": row["revenue"],
                    "revenue_display": _money(row["revenue"]),
                    "deals": row["deals"],
                }
            )
    except Exception:
        pass

    # --- Data quality ------------------------------------------------------
    data_quality = [
        {
            "label": "Open opportunities missing amount",
            "count": _count(open_opps.filter(amount__isnull=True)),
        },
        {
            "label": "Open opportunities missing close date",
            "count": _count(open_opps.filter(expected_close_date__isnull=True)),
        },
        {
            "label": "Quotes stuck in Pending Approval",
            "count": _count(pending_quotes),
        },
        {
            "label": "Accounts without an owner",
            "count": _count(Account.objects.filter(owner__isnull=True)),
        },
        {
            "label": "Overdue activities",
            "count": overdue_activities,
        },
    ]

    kpis = [
        {
            "label": "Revenue (YTD)",
            "value": f"${_money(won_year and _sum(won_year) or 0)}",
            "sub": f"Closed Won · this year",
            "tone": "green",
        },
        {
            "label": "Revenue (12 mo)",
            "value": f"${_money(revenue_ttm)}",
            "sub": f"{won_ttm_count} won deals",
            "tone": "green",
        },
        {
            "label": "Open pipeline",
            "value": f"${_money(open_value)}",
            "sub": f"{open_count} open opportunities",
            "tone": "blue",
        },
        {
            "label": "Weighted forecast",
            "value": f"${_money(weighted_forecast)}",
            "sub": f"${_money(weighted_forecast_90)} closing in 90 days",
            "tone": "purple",
        },
        {
            "label": "Open quotes",
            "value": f"${_money(_sum(open_quotes, 'net_amount'))}",
            "sub": f"{_count(open_quotes)} quotes · {_count(pending_quotes)} pending approval",
            "tone": "amber",
        },
        {
            "label": "Active customers",
            "value": str(len(ttm_account_ids)),
            "sub": f"purchased last 12 months · {len(month_account_ids)} this month",
            "tone": "blue",
        },
        {
            "label": "Win rate (12 mo)",
            "value": _pct(won_ttm_count, closed_total),
            "sub": f"{won_ttm_count} won / {closed_total} closed",
            "tone": "green",
        },
        {
            "label": "Avg deal size (12 mo)",
            "value": f"${_money(avg_deal_size)}",
            "sub": "Closed Won average",
            "tone": "blue",
        },
        {
            "label": "New leads (month)",
            "value": str(leads_month),
            "sub": f"{lead_counts.get('converted', 0)} converted all-time",
            "tone": "purple",
        },
        {
            "label": "Activities (30 days)",
            "value": str(activities_30d),
            "sub": f"{overdue_activities} overdue",
            "tone": "amber",
        },
    ]

    return {
        "kpis": kpis,
        "revenue_labels": revenue_labels,
        "revenue_values": revenue_values,
        "won_lost_labels": won_lost_labels,
        "won_values": won_values,
        "lost_values": lost_values,
        "lead_funnel": lead_funnel,
        "lead_total": lead_total,
        "leads_by_source": leads_by_source,
        "pipeline_by_stage": pipeline_by_stage,
        "quote_status_rows": quote_status_rows,
        "quotes": {
            "open_count": _count(open_quotes),
            "open_value": _money(_sum(open_quotes, "net_amount")),
            "pending_count": _count(pending_quotes),
            "pending_value": _money(_sum(pending_quotes, "net_amount")),
            "expiring_soon": expiring_soon,
            "avg_value": _money(avg_quote),
            "avg_discount": f"{Decimal(str(avg_discount)):.1f}%",
        },
        "top_customers": top_customers,
        "subscriptions": {
            "active": active_subscriptions,
            "mrr": _money(mrr),
            "arr": _money(mrr * 12),
            "renewals_due": renewals_due,
        },
        "activity_mix": activity_mix,
        "leaderboard": leaderboard,
        "data_quality": data_quality,
        "generated_at": timezone.localtime(),
        "revenue_all": _money(revenue_all),
    }
