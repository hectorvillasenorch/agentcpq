from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from .identifiers import user_uuid_from_value
from .models import NotificationEvent, NotificationPreference
from .spec import NOTIFICATION_POLICY_BY_ROLE
from .thresholds import render_template

User = get_user_model()

ROLE_GROUP_ALIASES = {
    "executive": {"executive", "executives"},
    "bizops": {"bizops", "biz ops", "business ops", "business operations"},
    "sales_exec": {"sales_exec", "sales exec", "sales executive", "sales executives"},
}


def get_users_for_role(role_key: str):
    names = ROLE_GROUP_ALIASES.get(role_key, {role_key})
    return User.objects.filter(groups__name__in=list(names)).distinct()


def get_user_role_key(user) -> str | None:
    group_names = {g.name.lower() for g in user.groups.all()}
    for role, aliases in ROLE_GROUP_ALIASES.items():
        if group_names.intersection({a.lower() for a in aliases}):
            return role
    return None


def _get_effective_policy(role_key: str):
    return NOTIFICATION_POLICY_BY_ROLE.get(role_key, {})


def _get_preference(tenant_uuid, user_uuid, role_key: str):
    pref = NotificationPreference.objects.filter(
        tenant_id=tenant_uuid,
        user_id=user_uuid,
        role_key=role_key,
    ).first()
    if pref:
        return {
            "channels": pref.channels,
            "max_per_day": pref.max_per_day,
            "digest_enabled": pref.digest_enabled,
            "digest_frequency": pref.digest_frequency,
        }
    policy = _get_effective_policy(role_key)
    return {
        "channels": policy.get("channels", []),
        "max_per_day": policy.get("max_per_day", 0),
        "digest_enabled": policy.get("digest", {}).get("enabled", False),
        "digest_frequency": policy.get("digest", {}).get("frequency"),
    }


def _within_dedupe_window(tenant_uuid, user_uuid, dedupe_key: str, window_hours: int):
    cutoff = timezone.now() - timedelta(hours=window_hours)
    return NotificationEvent.objects.filter(
        tenant_id=tenant_uuid,
        user_id=user_uuid,
        dedupe_key=dedupe_key,
        created_at__gte=cutoff,
    ).exists()


def _exceeds_daily_limit(tenant_uuid, user_uuid, max_per_day: int):
    if max_per_day <= 0:
        return False
    today = timezone.now().date()
    return NotificationEvent.objects.filter(
        tenant_id=tenant_uuid,
        user_id=user_uuid,
        created_at__date=today,
    ).count() >= max_per_day


def record_notifications(
    *,
    tenant_uuid,
    domain: str,
    period_key: str,
    triggered_rules: list,
    metrics: dict,
):
    events = []
    for rule in triggered_rules:
        role_targets = rule.get("audience_roles") or []
        for role_key in role_targets:
            policy = _get_effective_policy(role_key)
            if not policy.get("enabled", False):
                continue
            if rule.get("severity") not in (policy.get("notify_on_severity") or []):
                continue
            dedupe_window = int(policy.get("dedupe_window_hours", 0) or 0)
            users = get_users_for_role(role_key)

            for user in users:
                user_uuid = user_uuid_from_value(user.id)
                dedupe_key = f"{tenant_uuid}:{role_key}:{rule.get('rule_key')}:{period_key}"

                if dedupe_window and _within_dedupe_window(tenant_uuid, user_uuid, dedupe_key, dedupe_window):
                    continue
                pref = _get_preference(tenant_uuid, user_uuid, role_key)
                if _exceeds_daily_limit(tenant_uuid, user_uuid, pref.get("max_per_day", 0) or 0):
                    continue

                title = f"{domain.title()} Alert"
                body = render_template(rule.get("message_template", ""), metrics)
                event = NotificationEvent.objects.create(
                    tenant_id=tenant_uuid,
                    user_id=user_uuid,
                    role_key=role_key,
                    domain=domain,
                    rule_key=rule.get("rule_key"),
                    severity=rule.get("severity"),
                    title=title,
                    body=body,
                    payload={"metrics": metrics},
                    channels_sent=pref.get("channels", []),
                    dedupe_key=dedupe_key,
                )
                events.append(event)
    return events
