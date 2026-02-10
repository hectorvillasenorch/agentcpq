from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from .models import (
    Account,
    AccessPolicy,
    Contact,
    CustomObject,
    CustomObjectPermission,
    CustomField,
    CustomFieldValue,
    PartnerProfile,
    RecordAccessGrant,
)


@dataclass(frozen=True)
class CustomObjectPerms:
    can_view: bool
    can_add: bool
    can_change: bool
    can_delete: bool

    def any(self) -> bool:
        return self.can_view or self.can_add or self.can_change or self.can_delete


def _is_enforced(custom_object: CustomObject) -> bool:
    return CustomObjectPermission.objects.filter(custom_object=custom_object).exists()


def get_custom_object_perms(user, custom_object: CustomObject) -> CustomObjectPerms:
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return CustomObjectPerms(True, True, True, True)

    # Backwards-compatible: permissions only take effect once configured for that object.
    if not _is_enforced(custom_object):
        return CustomObjectPerms(True, True, True, True)

    group_ids = list(user.groups.values_list("id", flat=True))
    if not group_ids:
        return CustomObjectPerms(False, False, False, False)

    perms_qs = CustomObjectPermission.objects.filter(
        custom_object=custom_object,
        group_id__in=group_ids,
    )

    can_view = perms_qs.filter(can_view=True).exists()
    can_add = perms_qs.filter(can_add=True).exists()
    can_change = perms_qs.filter(can_change=True).exists()
    can_delete = perms_qs.filter(can_delete=True).exists()
    return CustomObjectPerms(can_view, can_add, can_change, can_delete)


def user_can_access_custom_object(user, custom_object: CustomObject, action: str) -> bool:
    perms = get_custom_object_perms(user, custom_object)
    action = (action or "").lower().strip()
    if action in {"view", "read"}:
        return perms.can_view
    if action in {"add", "create"}:
        return perms.can_add
    if action in {"change", "edit", "update"}:
        return perms.can_change
    if action in {"delete", "remove"}:
        return perms.can_delete
    return perms.any()


def visible_custom_objects_for_user(user):
    base_qs = CustomObject.objects.filter(show_in_sidebar=True)
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return base_qs

    enforced_ids = list(
        CustomObjectPermission.objects.filter(custom_object__in=base_qs)
        .values_list("custom_object_id", flat=True)
        .distinct()
    )
    if not enforced_ids:
        return base_qs

    allowed_ids = list(
        CustomObjectPermission.objects.filter(group__in=user.groups.all())
        .filter(Q(can_view=True) | Q(can_add=True) | Q(can_change=True) | Q(can_delete=True))
        .values_list("custom_object_id", flat=True)
        .distinct()
    )

    return base_qs.filter(Q(id__in=allowed_ids) | ~Q(id__in=enforced_ids))


def perms_to_template_dict(perms: CustomObjectPerms) -> Dict[str, bool]:
    return {
        "can_view": bool(perms.can_view),
        "can_add": bool(perms.can_add),
        "can_change": bool(perms.can_change),
        "can_delete": bool(perms.can_delete),
    }


def _user_in_partner_group(user) -> bool:
    if not user or getattr(user, "is_anonymous", False):
        return False
    try:
        return user.groups.filter(name__icontains="partner").exists()
    except Exception:
        return False


def get_partner_profile(user) -> Optional[PartnerProfile]:
    if not user or getattr(user, "is_anonymous", False):
        return None
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return None
    try:
        profile = user.partner_profile
    except (PartnerProfile.DoesNotExist, AttributeError):
        return None
    return profile if profile.is_partner else None


def is_partner_user(user) -> bool:
    return bool(get_partner_profile(user) or _user_in_partner_group(user))


def partner_label_for_user(user) -> str:
    return "Partner" if is_partner_user(user) else ""


def _resolve_partner_accounts(user, profile: Optional[PartnerProfile]):
    if profile:
        assigned_accounts = profile.accounts.all()
        if assigned_accounts.exists():
            return assigned_accounts
    return Account.objects.filter(owner=user)


def _resolve_partner_contacts(user, profile: Optional[PartnerProfile], accounts):
    if profile:
        assigned_contacts = profile.contacts.all()
        if assigned_contacts.exists():
            return assigned_contacts
    return Contact.objects.filter(account__in=accounts)


def _normalize_record_permission(permission: str) -> str:
    value = (permission or "view").strip().lower()
    if value in {"edit", "update"}:
        return "change"
    if value in {"remove"}:
        return "delete"
    return value


def _record_permission_field(permission: str) -> str:
    normalized = _normalize_record_permission(permission)
    if normalized in {"change", "write"}:
        return "can_change"
    if normalized == "delete":
        return "can_delete"
    if normalized == "share":
        return "can_share"
    return "can_view"


def _fallback_access_policy() -> AccessPolicy:
    return AccessPolicy(
        key="fallback",
        label="Fallback Access Policy",
        strategy=AccessPolicy.STRATEGY_LEGACY_PARTNER,
        is_active=True,
        allow_superuser=True,
        allow_staff=True,
        include_partner_scope=True,
        allow_unassigned_records=False,
        use_record_grants=False,
    )


def get_record_access_policy() -> AccessPolicy:
    policy = AccessPolicy.get_active_policy()
    return policy if policy else _fallback_access_policy()


def _policy_user_bypass(user, policy: AccessPolicy) -> bool:
    if not user or getattr(user, "is_anonymous", False):
        return False
    if getattr(policy, "allow_superuser", True) and getattr(user, "is_superuser", False):
        return True
    if getattr(policy, "allow_staff", True) and getattr(user, "is_staff", False):
        return True
    return False


def _model_has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False


def _granted_record_ids(user, model, permission: str):
    if not user or getattr(user, "is_anonymous", False):
        return []
    try:
        content_type = ContentType.objects.get_for_model(model)
        perm_field = _record_permission_field(permission)
        grants_qs = RecordAccessGrant.objects.filter(content_type=content_type).filter(**{perm_field: True})
        user_groups = list(user.groups.values_list("id", flat=True))
        principal_filter = Q(user=user)
        if user_groups:
            principal_filter |= Q(group_id__in=user_groups)
        return grants_qs.filter(principal_filter).values_list("object_id", flat=True)
    except Exception:
        return []


def _strict_record_access_q(user, queryset, policy: AccessPolicy, permission: str):
    strategy = getattr(policy, "strategy", AccessPolicy.STRATEGY_LEGACY_PARTNER)
    include_creator = strategy in {
        AccessPolicy.STRATEGY_CREATOR_ONLY,
        AccessPolicy.STRATEGY_CREATOR_OR_GROUP,
        AccessPolicy.STRATEGY_CREATOR_OR_OWNER_OR_GROUP,
    }
    include_owner = strategy in {
        AccessPolicy.STRATEGY_OWNER_OR_GROUP,
        AccessPolicy.STRATEGY_CREATOR_OR_OWNER_OR_GROUP,
    }

    model = queryset.model
    has_created_by = _model_has_field(model, "created_by")
    has_owner = _model_has_field(model, "owner")

    # Strategy fallback so strict policies still work for models that define
    # only one principal field (e.g., Product has created_by but no owner).
    if include_owner and not has_owner and has_created_by:
        include_creator = True
    if include_creator and not has_created_by and has_owner:
        include_owner = True

    allow_unassigned = bool(getattr(policy, "allow_unassigned_records", False))

    access_q = Q(pk__in=[])

    if include_creator and has_created_by:
        creator_q = Q(created_by=user)
        if allow_unassigned:
            creator_q |= Q(created_by__isnull=True)
        access_q |= creator_q

    if include_owner and has_owner:
        owner_q = Q(owner=user)
        if allow_unassigned:
            owner_q |= Q(owner__isnull=True)
        access_q |= owner_q

    if getattr(policy, "use_record_grants", True):
        grant_ids = _granted_record_ids(user, model, permission)
        access_q |= Q(pk__in=grant_ids)

    return access_q


def _apply_legacy_partner_scope(user, object_name: str, queryset, *, custom_object=None):
    profile = get_partner_profile(user)
    if not (profile or _user_in_partner_group(user)):
        return queryset

    accounts = _resolve_partner_accounts(user, profile)
    contacts = _resolve_partner_contacts(user, profile, accounts)
    model_name = queryset.model.__name__.lower()
    object_key = (custom_object.name if custom_object else object_name) or model_name
    normalized = str(object_key).lower()

    if normalized in {"account", "accounts"} or model_name == "account":
        return queryset.filter(id__in=accounts)
    if normalized in {"contact", "contacts"} or model_name == "contact":
        return queryset.filter(Q(id__in=contacts) | Q(account__in=accounts))
    if normalized in {"opportunity", "opportunities"} or model_name == "opportunity":
        return queryset.filter(account__in=accounts)
    if normalized in {"quote", "quotes"} or model_name == "quote":
        return queryset.filter(Q(account__in=accounts) | Q(opportunity__account__in=accounts))
    if normalized in {"quoteline", "quote_line", "quote lines"} or model_name == "quoteline":
        return queryset.filter(Q(quote__account__in=accounts) | Q(quote__opportunity__account__in=accounts))
    if normalized in {"activity", "activities"} or model_name == "activity":
        return queryset.filter(
            Q(opportunity__account__in=accounts)
            | Q(contact__account__in=accounts)
            | Q(lead__contact__account__in=accounts)
        )
    if normalized in {"product", "products"} or model_name == "product":
        return queryset

    if custom_object:
        account_ids = list(accounts.values_list("id", flat=True))
        account_accids = list(accounts.values_list("accid", flat=True))
        account_external_ids = list(accounts.values_list("external_id", flat=True))
        account_values = [str(pk) for pk in account_ids]
        account_values.extend([str(val) for val in account_accids if val])
        account_values.extend([str(val) for val in account_external_ids if val])
        if not account_ids:
            return queryset.none()
        lookup_fields = list(CustomField.objects.filter(custom_object=custom_object, data_type="lookup"))
        account_fields = []
        for field in lookup_fields:
            lookup_model = (field.lookup_model or "").lower()
            if lookup_model.endswith(".account") or lookup_model == "account" or lookup_model.endswith("account"):
                account_fields.append(field)
                continue
            field_name = (field.name or "").lower()
            field_label = (field.label or "").lower()
            if "account" in field_name or "account" in field_label:
                account_fields.append(field)
        if not account_fields:
            return queryset.none()
        record_ids = (
            CustomFieldValue.objects.filter(field__in=account_fields, value__in=account_values)
            .values_list("record_id", flat=True)
            .distinct()
        )
        return queryset.filter(id__in=record_ids)

    return queryset


def apply_partner_access_filter(user, object_name: str, queryset, *, custom_object=None, permission: str = "view"):
    if queryset is None:
        return queryset
    if not user or getattr(user, "is_anonymous", False):
        return queryset.none()

    policy = get_record_access_policy()
    if _policy_user_bypass(user, policy):
        return queryset

    scoped_queryset = queryset
    if getattr(policy, "include_partner_scope", True):
        scoped_queryset = _apply_legacy_partner_scope(user, object_name, scoped_queryset, custom_object=custom_object)

    if getattr(policy, "strategy", AccessPolicy.STRATEGY_LEGACY_PARTNER) == AccessPolicy.STRATEGY_LEGACY_PARTNER:
        return scoped_queryset.distinct()

    strict_q = _strict_record_access_q(user, scoped_queryset, policy, permission)
    return scoped_queryset.filter(strict_q).distinct()


def partner_can_access_record(
    user,
    object_name: str,
    record,
    *,
    custom_object=None,
    permission: str = "view",
) -> bool:
    if record is None:
        return False
    queryset = record.__class__.objects.all()
    if custom_object is not None and hasattr(record, "object_type"):
        queryset = queryset.filter(object_type=custom_object)
    filtered = apply_partner_access_filter(
        user,
        object_name,
        queryset,
        custom_object=custom_object,
        permission=permission,
    )
    return filtered.filter(pk=record.pk).exists()
