from datetime import date, timedelta

from dateutil.relativedelta import relativedelta


def _month_range(reference: date):
    start = reference.replace(day=1)
    next_month = start + relativedelta(months=1)
    end = next_month - timedelta(days=1)
    return start, end


def _quarter_range(reference: date):
    quarter = (reference.month - 1) // 3 + 1
    start_month = (quarter - 1) * 3 + 1
    start = date(reference.year, start_month, 1)
    end = date(reference.year, start_month, 1) + relativedelta(months=3) - timedelta(days=1)
    return start, end


def _normalize_fiscal_start_month(start_month: int | None) -> int:
    try:
        start_month = int(start_month or 1)
    except (TypeError, ValueError):
        start_month = 1
    if start_month < 1 or start_month > 12:
        return 1
    return start_month


def _normalize_fiscal_label_mode(label_mode: str | None) -> str:
    return label_mode if label_mode in {"start", "end"} else "start"


def fiscal_label_year(reference: date, start_month: int, label_mode: str) -> int:
    start_month = _normalize_fiscal_start_month(start_month)
    label_mode = _normalize_fiscal_label_mode(label_mode)
    fiscal_start_year = reference.year if reference.month >= start_month else reference.year - 1
    if label_mode == "end":
        return fiscal_start_year + (1 if start_month != 1 else 0)
    return fiscal_start_year


def fiscal_year_range_for_label(label_year: int, start_month: int, label_mode: str) -> tuple[date, date]:
    start_month = _normalize_fiscal_start_month(start_month)
    label_mode = _normalize_fiscal_label_mode(label_mode)
    start_year = label_year if label_mode == "start" else label_year - (1 if start_month != 1 else 0)
    start_date = date(start_year, start_month, 1)
    end_date = start_date + relativedelta(years=1) - timedelta(days=1)
    return start_date, end_date


def fiscal_year_span_range(end_label_year: int, span: int, start_month: int, label_mode: str) -> tuple[date, date]:
    span = max(int(span), 1)
    start_label_year = end_label_year - (span - 1)
    start_date, _ = fiscal_year_range_for_label(start_label_year, start_month, label_mode)
    _, end_date = fiscal_year_range_for_label(end_label_year, start_month, label_mode)
    return start_date, end_date


def current_period_range(
    timeframe_key: str,
    reference: date,
    *,
    year_span: int = 1,
    year_offset: int = 0,
    use_fiscal: bool = False,
    fiscal_start_month: int = 1,
    fiscal_label_mode: str = "start",
    fiscal_end_label_year: int | None = None,
) -> tuple[date, date]:
    if timeframe_key == "day":
        return reference, reference
    if timeframe_key == "week":
        start = reference - timedelta(days=reference.weekday())
        end = start + timedelta(days=6)
        return start, end
    if timeframe_key == "month":
        return _month_range(reference)
    if timeframe_key == "quarter":
        return _quarter_range(reference)
    if timeframe_key == "year":
        span = max(int(year_span), 1)
        if use_fiscal:
            end_label_year = fiscal_end_label_year
            if end_label_year is None:
                end_label_year = fiscal_label_year(reference, fiscal_start_month, fiscal_label_mode)
                end_label_year -= max(int(year_offset), 0)
            return fiscal_year_span_range(end_label_year, span, fiscal_start_month, fiscal_label_mode)
        offset = max(int(year_offset), 0)
        end_year = reference.year - offset
        start_year = end_year - (span - 1)
        return date(start_year, 1, 1), date(end_year, 12, 31)
    raise ValueError(f"Unsupported timeframe_key: {timeframe_key}")


def previous_period_range(
    timeframe_key: str,
    period_start: date,
    period_end: date,
    *,
    year_span: int = 1,
    use_fiscal: bool = False,
    fiscal_start_month: int = 1,
    fiscal_label_mode: str = "start",
    fiscal_end_label_year: int | None = None,
) -> tuple[date, date]:
    if timeframe_key == "custom":
        span_days = (period_end - period_start).days + 1
        span_days = max(span_days, 1)
        prev_end = period_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span_days - 1)
        return prev_start, prev_end
    if timeframe_key == "day":
        prev = period_start - timedelta(days=1)
        return prev, prev
    if timeframe_key == "week":
        start = period_start - timedelta(days=7)
        end = period_end - timedelta(days=7)
        return start, end
    if timeframe_key == "month":
        prev_start = period_start - relativedelta(months=1)
        return _month_range(prev_start)
    if timeframe_key == "quarter":
        prev_start = period_start - relativedelta(months=3)
        return _quarter_range(prev_start)
    if timeframe_key == "year":
        span = max(int(year_span), 1)
        if use_fiscal:
            end_label_year = fiscal_end_label_year
            if end_label_year is None:
                end_label_year = fiscal_label_year(period_end, fiscal_start_month, fiscal_label_mode)
            prev_end_label_year = end_label_year - span
            return fiscal_year_span_range(prev_end_label_year, span, fiscal_start_month, fiscal_label_mode)
        end_year = period_end.year - span
        start_year = end_year - (span - 1)
        return date(start_year, 1, 1), date(end_year, 12, 31)
    raise ValueError(f"Unsupported timeframe_key: {timeframe_key}")
