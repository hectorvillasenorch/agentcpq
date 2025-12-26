from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from django.db.models import Q

from .models import CustomObject, CustomObjectPermission


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
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return CustomObject.objects.all()

    enforced_ids = list(
        CustomObjectPermission.objects.values_list("custom_object_id", flat=True).distinct()
    )
    if not enforced_ids:
        return CustomObject.objects.all()

    allowed_ids = list(
        CustomObjectPermission.objects.filter(group__in=user.groups.all())
        .filter(Q(can_view=True) | Q(can_add=True) | Q(can_change=True) | Q(can_delete=True))
        .values_list("custom_object_id", flat=True)
        .distinct()
    )

    return CustomObject.objects.filter(Q(id__in=allowed_ids) | ~Q(id__in=enforced_ids))


def perms_to_template_dict(perms: CustomObjectPerms) -> Dict[str, bool]:
    return {
        "can_view": bool(perms.can_view),
        "can_add": bool(perms.can_add),
        "can_change": bool(perms.can_change),
        "can_delete": bool(perms.can_delete),
    }

