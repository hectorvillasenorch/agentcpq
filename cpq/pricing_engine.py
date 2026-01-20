from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP

from django.db.models import Q
from django.utils import timezone

from cpq.models import CPQSettings, PricingTierRow, PricingTierTable


ROUNDING_MAP = {
    "HALF_EVEN": ROUND_HALF_EVEN,
    "HALF_UP": ROUND_HALF_UP,
    "UP": ROUND_UP,
    "DOWN": ROUND_DOWN,
}


def _quantize(value, precision, rounding_mode):
    quant = Decimal("1").scaleb(-int(precision))
    rounding = ROUNDING_MAP.get(str(rounding_mode or "HALF_EVEN").upper(), ROUND_HALF_EVEN)
    return value.quantize(quant, rounding=rounding)


def _is_table_effective(table, as_of_date):
    if table.effective_start_date and table.effective_start_date > as_of_date:
        return False
    if table.effective_end_date and table.effective_end_date < as_of_date:
        return False
    return True


def get_active_pricing_table(product, currency=None, uom=None, as_of_date=None):
    if not product:
        return None

    as_of_date = as_of_date or timezone.now().date()
    qs = PricingTierTable.objects.filter(product=product, is_active=True)
    if currency is None:
        qs = qs.filter(currency__isnull=True)
    else:
        qs = qs.filter(currency=currency)
    if uom is None:
        qs = qs.filter(uom__isnull=True)
    else:
        qs = qs.filter(uom=uom)

    for table in qs.order_by("-effective_start_date", "-created_at", "-id"):
        if _is_table_effective(table, as_of_date):
            return table
    return None


def resolve_unit_price(product, quantity, currency=None, uom=None, as_of_date=None):
    table = get_active_pricing_table(
        product,
        currency=currency,
        uom=uom,
        as_of_date=as_of_date,
    )
    if not table:
        return None

    try:
        qty = int(quantity or 0)
    except (TypeError, ValueError):
        qty = 0

    row = (
        PricingTierRow.objects.filter(pricing_table=table, min_quantity__lte=qty)
        .filter(Q(max_quantity__isnull=True) | Q(max_quantity__gte=qty))
        .order_by("min_quantity")
        .first()
    )
    if not row:
        return None

    settings = CPQSettings.safe_first() or CPQSettings()
    precision = settings.decimal_precision or 2
    rounding_mode = settings.rounding_mode or "HALF_EVEN"
    unit_price = _quantize(Decimal(str(row.unit_price)), precision, rounding_mode)
    try:
        from cpq.events import emit_domain_event
        event_key = f"{product.id}:{table.id}:{row.id}:{qty}:{currency}:{uom}:{as_of_date}"
        emit_domain_event(
            "PRICING.TIER_RESOLVED",
            payload={
                "product_id": product.id,
                "pricing_table_id": table.id,
                "pricing_row_id": row.id,
                "quantity": qty,
                "currency": currency,
                "uom": uom,
                "as_of_date": str(as_of_date),
                "unit_price": str(unit_price),
            },
            object_type="Product",
            object_id=product.id,
            source="pricing_engine",
            idempotency_key=event_key,
        )
    except Exception:
        pass
    return unit_price
