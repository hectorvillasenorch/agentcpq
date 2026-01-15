from django.contrib import admin

from .models import (
    FeatureFlag,
    MetricDefinition,
    MetricSnapshot,
    ThresholdRule,
    NotificationPreference,
    NotificationEvent,
    PlanningConfig,
    SlaConfig,
)


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ("key", "tenant_id", "enabled", "created_at", "updated_at")
    list_filter = ("key", "enabled")
    search_fields = ("key", "tenant_id")


@admin.register(MetricDefinition)
class MetricDefinitionAdmin(admin.ModelAdmin):
    list_display = ("domain", "metric_key", "display_name", "tenant_id", "is_active")
    list_filter = ("domain", "is_active")
    search_fields = ("metric_key", "display_name", "tenant_id")


@admin.register(MetricSnapshot)
class MetricSnapshotAdmin(admin.ModelAdmin):
    list_display = ("domain", "metric_key", "timeframe_key", "period_start", "period_end", "tenant_id")
    list_filter = ("domain", "timeframe_key")
    search_fields = ("metric_key", "tenant_id")


@admin.register(ThresholdRule)
class ThresholdRuleAdmin(admin.ModelAdmin):
    list_display = ("domain", "rule_key", "severity", "tenant_id", "is_active")
    list_filter = ("domain", "severity", "is_active")
    search_fields = ("rule_key", "tenant_id")


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("role_key", "user_id", "tenant_id", "max_per_day", "digest_enabled")
    list_filter = ("role_key", "digest_enabled")
    search_fields = ("user_id", "tenant_id")


@admin.register(NotificationEvent)
class NotificationEventAdmin(admin.ModelAdmin):
    list_display = ("rule_key", "severity", "role_key", "user_id", "tenant_id", "created_at")
    list_filter = ("severity", "role_key", "domain")
    search_fields = ("rule_key", "user_id", "tenant_id")


@admin.register(PlanningConfig)
class PlanningConfigAdmin(admin.ModelAdmin):
    list_display = ("domain", "timeframe_key", "period_start", "period_end", "tenant_id", "owner_role", "locked")
    list_filter = ("domain", "timeframe_key", "locked")
    search_fields = ("tenant_id", "owner_role")


@admin.register(SlaConfig)
class SlaConfigAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "tenant_id", "created_at", "updated_at")
    list_filter = ("key",)
    search_fields = ("tenant_id", "key")
