import datetime

def validate_and_cast_value(field, value):
    data_type = field.data_type.lower()

    if value is None:
        return False, None

    try:
        if data_type in ["text", "text area"]:
            return True, str(value)

        elif data_type == "number":
            return True, float(value)

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
                return True, datetime.datetime.strptime(value, "%Y-%m-%d").date()
            return False, None

        elif data_type == "dropdown":
            allowed_options = [str(opt).strip().lower() for opt in field.options or []]
            if str(value).strip().lower() in allowed_options:
                return True, str(value).strip()
            return False, None

        elif data_type == "lookup":
            return True, str(value)

        else:
            return False, None

    except Exception:
        return False, None