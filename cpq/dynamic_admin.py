"""Dynamic Django-admin models for custom objects.

Each ``CustomObject`` gets its own admin entry (e.g. "G-Drive Documentation",
"POV") built from a proxy model of ``CustomRecord``, so you can browse / add /
change / delete that object's records exactly like Opportunity or Account.

Admins are (re)built automatically on every admin page load, so objects created
from chat show up without a restart.
"""
from __future__ import annotations

import re
from typing import Dict, Optional

from django import forms
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.utils.html import format_html

from .models import CustomField, CustomFieldValue, CustomObject, CustomRecord

# object id -> (registered proxy model, label snapshot)
_REGISTERED: Dict[int, tuple] = {}

_LIST_COLUMNS = 3  # extra value columns shown in the changelist


class _UTCAdminBase(admin.ModelAdmin):
    """UTC-aware created/updated columns (mirrors UTCDisplayAdmin)."""

    def _utc_field(self, obj, field_name):
        value = getattr(obj, field_name, None)
        if not value:
            return "—"
        return format_html(
            '<span class="utc-date" data-utc="{}">{}</span>',
            value.isoformat(),
            value.strftime("%b %d, %Y, %I:%M %p"),
        )

    @admin.display(description="Created At")
    def created_at_js(self, obj):
        return self._utc_field(obj, "created_at")

    @admin.display(description="Updated At")
    def updated_at_js(self, obj):
        return self._utc_field(obj, "updated_at")


def _key_for(field: CustomField) -> str:
    """Form field key for a custom field (kept close to its API name)."""
    return field.name or f"field_{field.id}"


def _label_for(field: CustomField) -> str:
    return field.label or (field.name or "").replace("__c", "").replace("_", " ").title()


def _form_field(field: CustomField) -> forms.Field:
    data_type = (field.data_type or "text").lower()
    label = _label_for(field)
    required = bool(field.required)
    options = field.options or []

    if data_type in {"dropdown", "choice", "picklist", "select"} and options:
        choices = [("", "—")]
        for opt in options:
            if isinstance(opt, dict):
                choices.append((str(opt.get("value", "")), str(opt.get("label", opt.get("value", "")))))
            else:
                choices.append((str(opt), str(opt)))
        return forms.ChoiceField(choices=choices, required=required, label=label)

    if data_type in {"boolean", "checkbox"}:
        return forms.BooleanField(required=False, label=label)

    if data_type == "number":
        return forms.DecimalField(required=required, label=label, max_digits=20, decimal_places=6)

    if data_type == "date":
        return forms.DateField(required=required, label=label, widget=forms.DateInput(attrs={"type": "date"}))

    if data_type == "datetime":
        return forms.DateTimeField(required=required, label=label)

    if data_type in {"textarea", "text_multiline"}:
        return forms.CharField(required=required, label=label, widget=forms.Textarea(attrs={"rows": 3}))

    return forms.CharField(required=required, label=label, max_length=500)


def _initial_values(record: Optional[CustomRecord], custom_fields) -> Dict[str, object]:
    if record is None:
        return {}
    stored = {
        value.field_id: value.value
        for value in CustomFieldValue.objects.filter(record=record).select_related("field")
    }
    initial: Dict[str, object] = {}
    for field in custom_fields:
        raw = stored.get(field.id)
        if raw in (None, ""):
            continue
        data_type = (field.data_type or "text").lower()
        if data_type in {"boolean", "checkbox"}:
            initial[_key_for(field)] = str(raw).lower() in {"true", "1", "yes"}
        else:
            initial[_key_for(field)] = raw
    return initial


def _save_values(record: CustomRecord, custom_fields, cleaned: Dict[str, object], user) -> None:
    content_type = ContentType.objects.get_for_model(CustomRecord)
    existing = {value.field_id: value for value in CustomFieldValue.objects.filter(record=record)}

    for field in custom_fields:
        key = _key_for(field)
        if key not in cleaned:
            continue
        value = cleaned.get(key)
        if value is None:
            text = ""
        elif isinstance(value, bool):
            text = "true" if value else "false"
        else:
            text = str(value).strip()

        current = existing.get(field.id)
        if current is None:
            # Don't create noise rows for unchecked booleans / untouched fields.
            if text == "" or (isinstance(value, bool) and value is False):
                continue
            CustomFieldValue.objects.create(
                field=field,
                record=record,
                content_type=content_type,
                object_id=record.id,
                value=text,
                updated_by_user=user,
            )
        else:
            if current.value == text:
                continue
            current.value = text
            if user is not None and getattr(user, "pk", None):
                current.updated_by_user = user
            current.save(update_fields=["value", "updated_by_user"])


def _build_admin_class(custom_object: CustomObject):
    custom_fields = list(CustomField.objects.filter(custom_object=custom_object).order_by("id"))
    name_fields = [f for f in custom_fields if re.search(r"name|title|subject|label", (f.name or "").lower())]
    value_columns = [f for f in custom_fields if f not in name_fields][:_LIST_COLUMNS]
    prop_model = _REGISTERED[custom_object.id][0]

    field_keys = [_key_for(f) for f in custom_fields]
    declared_fields = {_key_for(f): _form_field(f) for f in custom_fields}

    def _form_init(self, *args, **kwargs):
        instance = kwargs.get("instance")
        forms.ModelForm.__init__(self, *args, **kwargs)
        if instance is not None:
            for key, value in _initial_values(instance, custom_fields).items():
                if key in self.fields:
                    self.initial[key] = value
        self.fields["custom_identifier"].disabled = True
        self.fields["custom_identifier"].help_text = "Generated automatically."
        self.fields["custom_identifier"].required = False

    def _form_save(self, commit=True):
        record = forms.ModelForm.save(self, commit=False)
        record.object_type = custom_object
        if commit:
            record.save()
        return record

    # Meta and the declared fields must live on the SAME class (Django validates
    # Meta.fields against the declared fields while creating the class).
    _Form = type(
        "_Form",
        (forms.ModelForm,),
        {
            "Meta": type("Meta", (), {"model": prop_model, "fields": ["custom_identifier"] + field_keys}),
            "__init__": _form_init,
            "save": _form_save,
            "__module__": __name__,
            **declared_fields,
        },
    )

    def _display(field: CustomField):
        def accessor(self, obj):
            value = CustomFieldValue.objects.filter(record=obj, field=field).values_list("value", flat=True).first()
            return value or "—"

        accessor.short_description = _label_for(field)
        return accessor

    attrs = {
        "form": _Form,
        "list_display": tuple(
            ["custom_identifier"]
            + [f"col_{f.id}" for f in (name_fields[:1] + value_columns)]
            + ["created_by", "created_at_js", "updated_at_js"]
        ),
        "readonly_fields": ("created_at_js", "updated_at_js"),
        "search_fields": ("custom_identifier",),
        "ordering": ("-created_at",),
        "list_per_page": 50,
        "object_type_id": custom_object.id,
    }
    for field in name_fields[:1] + value_columns:
        attrs[f"col_{field.id}"] = _display(field)

    def get_queryset(self, request):
        return CustomRecord.objects.filter(object_type=custom_object).select_related("object_type", "created_by")

    def save_model(self, request, obj, form, change):
        obj.object_type = custom_object
        if obj.pk is None and request.user and request.user.is_authenticated:
            obj.created_by = request.user
        obj.updated_by = request.user if request.user and request.user.is_authenticated else None
        _UTCAdminBase.save_model(self, request, obj, form, change)
        _save_values(obj, custom_fields, form.cleaned_data, request.user)

    def delete_model(self, request, obj):
        CustomFieldValue.objects.filter(record=obj).delete()
        _UTCAdminBase.delete_model(self, request, obj)

    def get_changeform_initial_data(self, request):
        return {}

    attrs["get_queryset"] = get_queryset
    attrs["save_model"] = save_model
    attrs["delete_model"] = delete_model

    return type(f"{prop_model.__name__}Admin", (_UTCAdminBase,), attrs)


def _build_proxy_model(custom_object: CustomObject):
    label = (custom_object.label or custom_object.name or "Record").strip()
    model_name = f"CustomObjectRecord{custom_object.id}"

    # Reuse the model if this process already built it (re-registering the same
    # model name triggers Django warnings).
    try:
        from django.apps import apps as django_apps

        existing = django_apps.all_models.get("cpq", {}).get(model_name.lower())
        if existing is not None and issubclass(existing, CustomRecord):
            return existing
    except Exception:
        pass

    meta = type(
        "Meta",
        (),
        {
            "proxy": True,
            "app_label": "cpq",
            "managed": True,
            "verbose_name": label,
            "verbose_name_plural": label,
        },
    )
    return type(model_name, (CustomRecord,), {"Meta": meta, "__module__": __name__})


def _reset_admin_urls(site) -> None:
    """New model admins must also appear in the URLconf (it is cached)."""
    try:
        site.__dict__.pop("urls", None)
    except Exception:
        pass
    try:
        from django.urls import clear_url_caches

        clear_url_caches()
    except Exception:
        pass


def ensure_custom_object_admins(site=None) -> None:
    """Create/refresh one admin entry per custom object."""
    site = site or admin.site
    try:
        objects = list(CustomObject.objects.all())
    except Exception:
        return

    current_ids = set()
    changed = False

    for custom_object in objects:
        current_ids.add(custom_object.id)
        label = (custom_object.label or custom_object.name or "").strip()
        registered = _REGISTERED.get(custom_object.id)

        if registered and registered[1] == label:
            continue

        if registered:
            # label changed → rebuild so the admin entry shows the new name
            try:
                site.unregister(registered[0])
            except admin.sites.NotRegistered:
                pass
            _REGISTERED.pop(custom_object.id, None)

        try:
            proxy = _build_proxy_model(custom_object)
            _REGISTERED[custom_object.id] = (proxy, label)
            site.register(proxy, _build_admin_class(custom_object))
        except Exception:
            _REGISTERED.pop(custom_object.id, None)
            changed = True

        try:
            proxy = _build_proxy_model(custom_object)
            _REGISTERED[custom_object.id] = (proxy, label)
            site.register(proxy, _build_admin_class(custom_object))
            changed = True
        except Exception:
            _REGISTERED.pop(custom_object.id, None)

    # drop entries whose object was deleted
    for object_id in list(_REGISTERED.keys()):
        if object_id not in current_ids:
            proxy = _REGISTERED.pop(object_id)[0]
            try:
                site.unregister(proxy)
            except admin.sites.NotRegistered:
                pass
            changed = True

    if changed:
        _reset_admin_urls(site)


def patch_admin_site(site=None) -> None:
    """Register the dynamic admins lazily on every admin page load."""
    site = site or admin.site
    if getattr(site, "_custom_objects_patched", False):
        return

    # 1) Register the per-object admins *before* the admin builds its URL
    #    patterns, so their changelist/add/change URLs exist from the start.
    original_get_urls = site.get_urls

    def get_urls():
        try:
            ensure_custom_object_admins(site)
        except Exception:
            pass
        return original_get_urls()

    site.get_urls = get_urls

    # 2) And again on every admin page load, so objects created later appear
    #    without a restart (busting the cached URLconf when something changed).
    original_get_app_list = site.get_app_list

    def get_app_list(request, app_label=None):
        try:
            ensure_custom_object_admins(site)
        except Exception:
            pass
        if app_label is None:
            return original_get_app_list(request)
        return original_get_app_list(request, app_label)

    site.get_app_list = get_app_list
    site._custom_objects_patched = True
