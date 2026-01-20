from decimal import Decimal, InvalidOperation

from django.utils import timezone

from cpq.models import Amendment, AmendmentDelta, CPQSettings, Subscription
from cpq.proration import calculate_proration_multiplier, calculate_prorated_amount


def _to_decimal(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def create_amendment(subscription, changes, amendment_type="Amendment", effective_date=None, quote=None):
    if not isinstance(subscription, Subscription):
        raise ValueError("subscription must be a Subscription instance")

    effective_date = effective_date or timezone.now().date()
    settings_obj = CPQSettings.safe_first() or CPQSettings()
    proration_multiplier = Decimal("1")
    if settings_obj.proration_enabled:
        proration_multiplier = calculate_proration_multiplier(
            subscription.start_date,
            subscription.end_date,
            effective_date,
        )

    amendment = Amendment.objects.create(
        subscription=subscription,
        quote=quote,
        amendment_type=amendment_type,
        effective_date=effective_date,
        status="draft",
        proration_multiplier=proration_multiplier,
    )

    for field_name, payload in (changes or {}).items():
        old_value = None
        new_value = None
        if isinstance(payload, dict):
            old_value = payload.get("old")
            new_value = payload.get("new")
        else:
            new_value = payload

        delta_value = None
        prorated_value = None
        old_decimal = _to_decimal(old_value)
        new_decimal = _to_decimal(new_value)
        if old_decimal is not None and new_decimal is not None:
            delta_value = new_decimal - old_decimal
            if settings_obj.proration_enabled:
                prorated_value = calculate_prorated_amount(delta_value, proration_multiplier)

        AmendmentDelta.objects.create(
            amendment=amendment,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            delta_value=delta_value,
            prorated_value=prorated_value,
        )

    try:
        from cpq.events import emit_domain_event
        emit_domain_event(
            "AMENDMENT.APPLIED",
            payload={
                "amendment_id": amendment.id,
                "subscription_id": subscription.id,
                "proration_multiplier": str(proration_multiplier),
                "delta_count": AmendmentDelta.objects.filter(amendment=amendment).count(),
            },
            object_type="Amendment",
            object_id=amendment.id,
            source="amendments",
        )
    except Exception:
        pass

    return amendment
