from django.db.models.signals import post_save
from django.dispatch import receiver
from cpq.models import Quote,Tenant,QuoteDocumentSettings
from hubspot.views import sync_quote_to_hubspot

@receiver(post_save, sender=Quote)
def handle_primary_quote_sync(sender, instance, **kwargs):
    if instance.hs_primary and instance.hs_deal_id:
        sync_quote_to_hubspot(instance)

@receiver(post_save, sender=Tenant)
def create_default_document_settings(sender, instance, created, **kwargs):

    if created:
        QuoteDocumentSettings.objects.get_or_create(
            tenant=instance
        )