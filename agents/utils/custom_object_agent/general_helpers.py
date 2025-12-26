import datetime
import re
from decimal import Decimal, InvalidOperation

def validate_and_cast_value(field, value):
    data_type = field.data_type.lower()

    if value is None:
        return False, None

    try:
        def _parse_decimal_like(raw):
            if raw is None:
                return None
            if isinstance(raw, Decimal):
                return raw
            if isinstance(raw, (int, float)):
                try:
                    return Decimal(str(raw))
                except (InvalidOperation, ValueError):
                    return None

            text = str(raw).strip()
            if not text:
                return None

            text = re.sub(r"[^0-9,.\-]+", "", text)
            if not text:
                return None

            has_dot = "." in text
            has_comma = "," in text

            if has_dot and has_comma:
                if text.rfind(",") > text.rfind("."):
                    text = text.replace(".", "")
                    text = text.replace(",", ".")
                else:
                    text = text.replace(",", "")
            elif has_comma and not has_dot:
                parts = text.split(",")
                if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
                    text = ".".join(parts)
                else:
                    text = text.replace(",", "")

            try:
                return Decimal(text)
            except (InvalidOperation, ValueError):
                return None

        if data_type in ["text", "textarea", "text area"]:
            return True, str(value)

        elif data_type in {"number", "currency", "percent", "percentage"}:
            parsed = _parse_decimal_like(value)
            if parsed is None:
                return False, None
            if data_type in {"currency", "percent", "percentage"}:
                parsed = parsed.quantize(Decimal("0.01"))
            return True, parsed

        elif data_type == "boolean":
            if isinstance(value, bool):
                return True, value
            if isinstance(value, str) and value.lower() in ["true", "false"]:
                return True, value.lower() == "true"
            return False, None

        elif data_type == "date":
            if isinstance(value, datetime.date):
                return True, value
            if isinstance(value, str):
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
                    try:
                        return True, datetime.datetime.strptime(value.strip(), fmt).date()
                    except ValueError:
                        continue
                return False, None
            return False, None

        elif data_type == "dropdown":
            input_value = str(value).strip().lower()
            for opt in field.options or []:
                if input_value == str(opt).strip().lower():
                    return True, str(opt).strip()
            return False, None

        elif data_type == "lookup":
            return True, str(value)

        else:
            return False, None

    except Exception:
        return False, None
