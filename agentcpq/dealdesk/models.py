import uuid

from django.conf import settings
from django.db import models

from cpq.models import ApprovalWorkflow, QuoteApproval


class DealPacket(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_NEEDS_INFO = "needs_info"
    STATUS_IN_APPROVAL = "in_approval"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_NEEDS_INFO, "Needs Info"),
        (STATUS_IN_APPROVAL, "In Approval"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    EXTERNAL_REF_OPPORTUNITY = "opportunity"
    EXTERNAL_REF_QUOTE = "quote"
    EXTERNAL_REF_DEAL_PACKET = "deal_packet"

    EXTERNAL_REF_CHOICES = [
        (EXTERNAL_REF_OPPORTUNITY, "Opportunity"),
        (EXTERNAL_REF_QUOTE, "Quote"),
        (EXTERNAL_REF_DEAL_PACKET, "Deal Packet"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tenant_id = models.CharField(max_length=64, db_index=True)
    idempotency_key = models.CharField(max_length=255)
    request_fingerprint = models.CharField(max_length=64)

    external_ref_type = models.CharField(max_length=24, choices=EXTERNAL_REF_CHOICES)
    external_ref_id = models.CharField(max_length=128)

    crm_source = models.CharField(max_length=64, blank=True, default="")
    payload_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    decision_summary = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dealdesk_packets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "idempotency_key"],
                name="uniq_dealpacket_tenant_idempotency",
            )
        ]
        indexes = [
            models.Index(fields=["tenant_id", "external_ref_type", "external_ref_id"]),
            models.Index(fields=["tenant_id", "status"]),
        ]

    def __str__(self):
        return f"DealPacket({self.id}, {self.tenant_id}, {self.status})"


class PolicyConfig(models.Model):
    tenant_id = models.CharField(max_length=64, db_index=True)
    version = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)
    config_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "version"],
                name="uniq_policyconfig_tenant_version",
            )
        ]
        indexes = [
            models.Index(fields=["tenant_id", "is_active"]),
        ]

    def __str__(self):
        return f"PolicyConfig({self.tenant_id}, {self.version}, active={self.is_active})"


class PolicyEvaluation(models.Model):
    tenant_id = models.CharField(max_length=64, db_index=True)
    deal_packet = models.ForeignKey(
        DealPacket,
        on_delete=models.CASCADE,
        related_name="policy_evaluations",
    )
    policy_version = models.CharField(max_length=32)
    results_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "deal_packet"]),
        ]

    def __str__(self):
        return f"PolicyEvaluation({self.deal_packet_id}, {self.policy_version})"


class DealDeskApprovalInstance(models.Model):
    ROUTING_TEMPLATE_USED = "template_used"
    ROUTING_INSTANCE_FALLBACK = "instance_fallback"

    ROUTING_MODE_CHOICES = [
        (ROUTING_TEMPLATE_USED, "Template Used"),
        (ROUTING_INSTANCE_FALLBACK, "Instance Fallback"),
    ]

    tenant_id = models.CharField(max_length=64, db_index=True)
    deal_packet = models.ForeignKey(
        DealPacket,
        on_delete=models.CASCADE,
        related_name="approval_instances",
    )
    quoteapproval = models.ForeignKey(
        QuoteApproval,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dealdesk_instances",
    )
    routing_mode = models.CharField(max_length=32, choices=ROUTING_MODE_CHOICES)
    template_workflow_ref = models.ForeignKey(
        ApprovalWorkflow,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dealdesk_template_instances",
    )
    instance_workflow_ref = models.ForeignKey(
        ApprovalWorkflow,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dealdesk_runtime_instances",
    )
    instance_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "deal_packet", "instance_key"],
                name="uniq_dealdesk_instance_key",
            )
        ]
        indexes = [
            models.Index(fields=["tenant_id", "deal_packet"]),
        ]

    def __str__(self):
        return f"DealDeskApprovalInstance({self.deal_packet_id}, {self.routing_mode})"


class AuditEvent(models.Model):
    tenant_id = models.CharField(max_length=64, db_index=True)
    run_id = models.CharField(max_length=64, db_index=True)
    source = models.CharField(max_length=32, default="api")
    idempotency_key = models.CharField(max_length=255, blank=True, default="")
    tenant_resolution_source = models.CharField(max_length=32, blank=True, default="")
    duplicate_request_detected = models.BooleanField(default=False)

    entity_type = models.CharField(max_length=32)
    entity_id = models.CharField(max_length=128)
    event_type = models.CharField(max_length=64)
    details_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "run_id"]),
            models.Index(fields=["tenant_id", "entity_type", "entity_id"]),
            models.Index(fields=["tenant_id", "event_type"]),
        ]

    def __str__(self):
        return f"AuditEvent({self.tenant_id}, {self.event_type})"


class SystemAuditEvent(models.Model):
    source = models.CharField(max_length=32, default="api")
    event_type = models.CharField(max_length=64)
    request_meta_json = models.JSONField(default=dict, blank=True)
    idempotency_key_if_present = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
        ]

    def __str__(self):
        return f"SystemAuditEvent({self.event_type})"


class SLATimer(models.Model):
    tenant_id = models.CharField(max_length=64, db_index=True)
    deal_packet = models.ForeignKey(
        DealPacket,
        on_delete=models.CASCADE,
        related_name="sla_timers",
    )
    target_role = models.CharField(max_length=255)
    due_at = models.DateTimeField()
    breached = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "breached"]),
            models.Index(fields=["tenant_id", "due_at"]),
        ]

    def __str__(self):
        return f"SLATimer({self.deal_packet_id}, {self.target_role}, breached={self.breached})"
