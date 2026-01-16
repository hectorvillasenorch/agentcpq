from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from django.db.models import Q

from .models import (
    Account,
    Contact,
    CustomObject,
    CustomObjectPermission,
    CustomField,
    CustomFieldValue,
    PartnerProfile,
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


def apply_partner_access_filter(user, object_name: str, queryset, *, custom_object=None):
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


def partner_can_access_record(user, object_name: str, record, *, custom_object=None) -> bool:
    profile = get_partner_profile(user)
    if not profile:
        return True
    if record is None:
        return False
    queryset = record.__class__.objects.all()
    if custom_object is not None and hasattr(record, "object_type"):
        queryset = queryset.filter(object_type=custom_object)
    filtered = apply_partner_access_filter(user, object_name, queryset, custom_object=custom_object)
    return filtered.filter(pk=record.pk).exists()
