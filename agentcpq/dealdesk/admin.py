from django.contrib import admin

from .models import (
    AuditEvent,
    DealDeskApprovalInstance,
    DealPacket,
    PolicyConfig,
    PolicyEvaluation,
    SLATimer,
    SystemAuditEvent,
)


@admin.register(DealPacket)
class DealPacketAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "external_ref_type", "external_ref_id", "status", "created_at")
    list_filter = ("status", "external_ref_type")
    search_fields = ("tenant_id", "external_ref_id", "idempotency_key")


@admin.register(PolicyConfig)
class PolicyConfigAdmin(admin.ModelAdmin):
    list_display = ("tenant_id", "version", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("tenant_id", "version")


@admin.register(PolicyEvaluation)
class PolicyEvaluationAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "deal_packet", "policy_version", "created_at")
    search_fields = ("tenant_id", "policy_version")


@admin.register(DealDeskApprovalInstance)
class DealDeskApprovalInstanceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant_id",
        "deal_packet",
        "routing_mode",
        "template_workflow_ref",
        "instance_workflow_ref",
        "created_at",
    )
    list_filter = ("routing_mode",)
    search_fields = ("tenant_id", "instance_key")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "run_id", "event_type", "entity_type", "entity_id", "created_at")
    list_filter = ("event_type", "source")
    search_fields = ("tenant_id", "run_id", "entity_id", "idempotency_key")


@admin.register(SystemAuditEvent)
class SystemAuditEventAdmin(admin.ModelAdmin):
    list_display = ("id", "event_type", "source", "created_at")
    list_filter = ("event_type", "source")


@admin.register(SLATimer)
class SLATimerAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant_id", "deal_packet", "target_role", "due_at", "breached")
    list_filter = ("breached",)
    search_fields = ("tenant_id", "target_role")
