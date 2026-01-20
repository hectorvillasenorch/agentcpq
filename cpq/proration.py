from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP

from cpq.models import CPQSettings


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


def calculate_proration_multiplier(start_date, end_date, effective_date):
    if not start_date or not end_date or not effective_date:
        return Decimal("1")

    if effective_date <= start_date:
        return Decimal("1")
    if effective_date > end_date:
        return Decimal("0")

    total_days = (end_date - start_date).days + 1
    remaining_days = (end_date - effective_date).days + 1
    if total_days <= 0:
        return Decimal("1")

    multiplier = Decimal(remaining_days) / Decimal(total_days)
    settings_obj = CPQSettings.safe_first() or CPQSettings()
    precision = settings_obj.decimal_precision or 2
    rounding_mode = settings_obj.rounding_mode or "HALF_EVEN"
    return _quantize(multiplier, precision, rounding_mode)


def calculate_prorated_amount(amount, multiplier):
    try:
        base_amount = Decimal(str(amount or 0))
        mult = Decimal(str(multiplier or 0))
    except Exception:
        return Decimal("0")

    settings_obj = CPQSettings.safe_first() or CPQSettings()
    precision = settings_obj.decimal_precision or 2
    rounding_mode = settings_obj.rounding_mode or "HALF_EVEN"
    return _quantize(base_amount * mult, precision, rounding_mode)
