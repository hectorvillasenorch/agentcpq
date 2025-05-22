from django.db.models.signals import post_save
from django.dispatch import receiver
from cpq.models import Quote  
from hubspot.views import sync_quote_to_hubspot

@receiver(post_save, sender=Quote)
def handle_primary_quote_sync(sender, instance, **kwargs):
    if instance.hs_primary and instance.hs_deal_id:
        sync_quote_to_hubspot(instance)