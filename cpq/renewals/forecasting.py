import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from cpq.models import CPQSettings, Opportunity, Quote, QuoteLine, Renewal, Subscription
from salesforce.forecasting import sync_forecast_opportunity

logger = logging.getLogger(__name__)


def _safe_decimal(value):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _compute_forecast_amount(quote, strategy):
    if strategy == "BASELINE_ACV_ONLY":
        total = Decimal("0")
        for line in quote.quote_lines.all():
            if not line.is_subscription:
                continue
            total += line.baseline_acv()
        if total > 0:
            return total
    if quote.net_amount is not None:
        return _safe_decimal(quote.net_amount)
    if quote.subtotal is not None:
        return _safe_decimal(quote.subtotal)
    total = Decimal("0")
    for line in quote.quote_lines.all():
        total += _safe_decimal(line.total_price)
    return total


def _build_forecast_opportunity_name(account, subscription, end_date):
    if subscription.product:
        product_label = subscription.product.name
    else:
        product_label = "Subscription"
    return f"Renewal Forecast - {account.name} - {product_label} ({end_date:%Y-%m-%d})"


def _create_forecast_opportunity(account, subscription, base_opportunity, settings_obj):
    end_date = subscription.end_date
    name = _build_forecast_opportunity_name(account, subscription, end_date)
    expected_close_date = end_date
    owner = None
    created_by = None
    if base_opportunity:
        owner = base_opportunity.owner
        created_by = base_opportunity.created_by
    owner = owner or account.owner
    created_by = created_by or account.created_by

    return Opportunity.objects.create(
        name=name,
        account=account,
        amount=Decimal("0.00"),
        stage=settings_obj.forecast_opportunity_stage or "Forecast",
        owner=owner,
        expected_close_date=expected_close_date,
        created_by=created_by,
    )


def _create_forecast_quote(subscription, opportunity, settings_obj):
    end_date = subscription.end_date

    # Quote name is auto-assigned as Q-##### by the Quote model.
    quote = Quote.objects.create(
        account=opportunity.account,
        opportunity=opportunity,
        status="Forecast",
        expiration_date=end_date,
        notes="Forecast renewal quote",
        owner=opportunity.owner,
        created_by=opportunity.created_by,
    )

    line = subscription.quote_line
    QuoteLine.objects.create(
        quote=quote,
        product=line.product,
        product_name=line.product_name,
        quantity=line.quantity,
        unit_price=line.unit_price,
        special_price=line.special_price,
        discount_type=line.discount_type,
        discount_percentage=line.discount_percentage,
        discount_amount=line.discount_amount,
        subtotal=line.subtotal,
        total_price=line.total_price,
        is_subscription=True,
        billing_frequency=line.billing_frequency,
        term=line.term or subscription.term,
        billing_start_date=subscription.end_date + timedelta(days=1),
        billing_end_date=None,
        sku=line.sku,
        description=line.description,
        tax_rate=line.tax_rate,
        created_by=opportunity.created_by,
    )

    return quote


def generate_renewal_forecasts(as_of_date=None, dry_run=False):
    settings_obj = CPQSettings.safe_first() or CPQSettings()
    window_days = settings_obj.renewal_forecast_window_days or 90
    as_of_date = as_of_date or timezone.now().date()
    window_end = as_of_date + timedelta(days=window_days)

    candidates = Subscription.objects.select_related(
        "contract__opportunity",
        "quote",
        "quote_line",
        "product",
        "quote__account",
    ).filter(
        status="Active",
        end_date__isnull=False,
        end_date__gte=as_of_date,
        end_date__lte=window_end,
    )

    created = 0
    skipped = 0
    for subscription in candidates:
        stale_qs = Renewal.objects.filter(subscription=subscription).exclude(
            renewal_date=subscription.end_date
        ).exclude(status="stale")
        if stale_qs.exists() and not dry_run:
            for renewal in stale_qs:
                renewal.status = "stale"
                renewal.save(update_fields=["status", "updated_at"])
                try:
                    from cpq.events import emit_domain_event
                    emit_domain_event(
                        "RENEWAL.STALE",
                        payload={
                            "renewal_id": renewal.id,
                            "subscription_id": subscription.id,
                            "renewal_date": str(renewal.renewal_date),
                        },
                        object_type="Renewal",
                        object_id=renewal.id,
                        source="renewal_forecast",
                    )
                except Exception:
                    pass

        if Renewal.objects.filter(subscription=subscription, renewal_date=subscription.end_date).exclude(status="stale").exists():
            skipped += 1
            continue

        base_opportunity = None
        if subscription.contract and subscription.contract.opportunity_id:
            base_opportunity = subscription.contract.opportunity
        elif subscription.quote and subscription.quote.opportunity_id:
            base_opportunity = subscription.quote.opportunity

        account = None
        if base_opportunity:
            account = base_opportunity.account
        elif subscription.quote:
            account = subscription.quote.account

        if not account:
            skipped += 1
            continue

        if dry_run:
            created += 1
            continue

        forecast_opp = _create_forecast_opportunity(
            account,
            subscription,
            base_opportunity,
            settings_obj,
        )
        forecast_quote = _create_forecast_quote(subscription, forecast_opp, settings_obj)

        forecast_amount = _compute_forecast_amount(
            forecast_quote,
            settings_obj.forecast_amount_strategy or "TOTAL_CONTRACT_VALUE",
        )

        forecast_opp.amount = forecast_amount
        forecast_opp.save(update_fields=["amount"])

        renewal = Renewal.objects.create(
            subscription=subscription,
            quote=forecast_quote,
            renewal_date=subscription.end_date,
            status="forecast",
            forecast_amount=forecast_amount,
        )

        try:
            from cpq.events import emit_domain_event
            emit_domain_event(
                "FORECAST_OPPORTUNITY.CREATED",
                payload={
                    "opportunity_id": forecast_opp.id,
                    "subscription_id": subscription.id,
                    "renewal_date": str(subscription.end_date),
                    "forecast_amount": str(forecast_amount),
                },
                object_type="Opportunity",
                object_id=forecast_opp.id,
                source="renewal_forecast",
            )
            emit_domain_event(
                "RENEWAL.CREATED",
                payload={
                    "renewal_id": renewal.id,
                    "subscription_id": subscription.id,
                    "renewal_date": str(subscription.end_date),
                    "forecast_amount": str(forecast_amount),
                },
                object_type="Renewal",
                object_id=renewal.id,
                source="renewal_forecast",
            )
        except Exception:
            pass

        if settings_obj.forecast_opportunity_enabled:
            sync_forecast_opportunity(
                forecast_opp,
                forecast_quote,
                account,
                forecast_amount,
                settings_obj,
            )

        created += 1

    return {"created": created, "skipped": skipped, "window_end": window_end}
