from django import forms
from django.contrib import admin

from .llm import clear_llm_config_cache
from .models import LLMConfig, SingleRecordLayout

# Only this user may manage the LLM provider settings.
ALLOWED_LLM_CONFIG_EDITORS = {"hvillasenor"}


class LLMConfigForm(forms.ModelForm):
    """ModelForm for LLMConfig with a masked, encrypted API-key field."""

    api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True, attrs={"autocomplete": "new-password", "size": 60}),
        help_text="API key for the provider. Leave blank to keep the current key or fall back to the environment.",
    )

    class Meta:
        model = LLMConfig
        fields = (
            "is_active",
            "base_url",
            "model",
            "model_classifier",
            "model_structured",
            "model_reasoning",
            "json_mode",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["api_key"].initial = self.instance.api_key

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.api_key = self.cleaned_data.get("api_key") or ""
        if commit:
            obj.save()
            self.save_m2m()
        return obj


@admin.register(LLMConfig)
class LLMConfigAdmin(admin.ModelAdmin):
    form = LLMConfigForm
    list_display = ("is_active", "model", "base_url", "json_mode", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("base_url", "model")
    fieldsets = (
        (None, {"fields": ("is_active",)}),
        ("Provider", {"fields": ("api_key", "base_url")}),
        ("Models", {"fields": ("model", "model_classifier", "model_structured", "model_reasoning")}),
        ("Options", {"fields": ("json_mode",)}),
    )

    def _is_allowed(self, request) -> bool:
        user = getattr(request, "user", None)
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "username", "").lower() in ALLOWED_LLM_CONFIG_EDITORS
        )

    def has_module_permission(self, request):
        return self._is_allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._is_allowed(request)

    def has_add_permission(self, request):
        return self._is_allowed(request)

    def has_change_permission(self, request, obj=None):
        return self._is_allowed(request)

    def has_delete_permission(self, request, obj=None):
        return self._is_allowed(request)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_llm_config_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        clear_llm_config_cache()


@admin.register(SingleRecordLayout)
class SingleRecordLayoutAdmin(admin.ModelAdmin):
    list_display = ("user", "object_name", "updated_at")
    list_filter = ("object_name", "user")
    search_fields = ("user__username", "object_name")
    ordering = ("-updated_at",)
