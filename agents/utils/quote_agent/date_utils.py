from datetime import datetime


SUPPORTED_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
]


def parse_user_date(value: str):
    """Attempt to parse common UI date formats into a naive date object."""
    if not value:
        return value

    for fmt in SUPPORTED_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    raise ValueError(
        f"Date '{value}' has an invalid format. Accepted formats: YYYY-MM-DD, YYYY/MM/DD, MM/DD/YYYY, DD/MM/YYYY"
    )
