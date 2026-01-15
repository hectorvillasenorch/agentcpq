import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import MetricSnapshot, SlaConfig
from .spec import BUSINESS_OWNED_INPUTS


logger = logging.getLogger(__name__)
SLA_KEY = BUSINESS_OWNED_INPUTS.get("sla_config", {}).get("key", "LEADS_NEW_SLA_DAYS")


def _clear_lead_snapshots(tenant_id: str) -> None:
    if not tenant_id:
        return
    deleted, _ = MetricSnapshot.objects.filter(tenant_id=tenant_id, domain="leads").delete()
    logger.info("SLA config changed; cleared lead snapshots tenant_id=%s deleted=%s", tenant_id, deleted)


@receiver(post_save, sender=SlaConfig)
def handle_sla_config_save(sender, instance, **kwargs):
    if instance.key != SLA_KEY:
        return
    _clear_lead_snapshots(instance.tenant_id)


@receiver(post_delete, sender=SlaConfig)
def handle_sla_config_delete(sender, instance, **kwargs):
    if instance.key != SLA_KEY:
        return
    _clear_lead_snapshots(instance.tenant_id)
