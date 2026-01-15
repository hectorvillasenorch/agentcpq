import os
from cpq.models import Tenant

from .identifiers import tenant_uuid_from_value
from .models import FeatureFlag
from .spec import FEATURE_FLAG_KEY, GLOBAL_OVERRIDE_ENV


def tenant_uuid_from_tenant(tenant: Tenant):
    source = getattr(tenant, "tenant_id", None) or str(getattr(tenant, "pk", ""))
    return tenant_uuid_from_value(source)


def parse_env_override() -> bool | None:
    raw = os.getenv(GLOBAL_OVERRIDE_ENV)
    if raw is None:
        return None
    value = str(raw).strip().lower()
    return value in {"1", "true", "yes", "on"}


def is_intelligence_enabled(tenant: Tenant | None) -> bool:
    override = parse_env_override()
    if override is not None:
        return override
    if tenant is None:
        return False
    tenant_uuid = tenant_uuid_from_tenant(tenant)
    flag = FeatureFlag.objects.filter(tenant_id=tenant_uuid, key=FEATURE_FLAG_KEY).first()
    return bool(flag.enabled) if flag else False
