import uuid


USER_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "agentcpq.intelligence.user")


def tenant_uuid_from_value(value: str | int | None) -> str:
    return str(value or "")


def user_uuid_from_value(value: str | int | None) -> uuid.UUID:
    source = str(value or "")
    return uuid.uuid5(USER_NAMESPACE, source)
