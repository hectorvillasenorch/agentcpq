from django.db.models.signals import post_save
from django.dispatch import receiver
from cpq.models import Quote,Tenant,QuoteDocumentSettings, Account, Opportunity, CustomObject, CustomField
from hubspot.views import sync_quote_to_hubspot
from .notifications.quote_notifications import notify_account_created, notify_opportunity_created
from .custom_objects.custom_objects import create_defaults_fields_for_custom_objects

@receiver(post_save, sender=Quote)
def handle_primary_quote_sync(sender, instance, **kwargs):
    if instance.hs_primary and instance.hs_deal_id:
        sync_quote_to_hubspot(instance)


# Email notifications post-save for Account
@receiver(post_save, sender=Account)
def send_account_created_email(sender, instance, created, **kwargs):
    if created:
        notify_account_created(instance)

#@receiver(post_save, sender=Opportunity)
#def send_opportunity_created_email(sender, instance, created, **kwargs):
#    if created:
#        notify_opportunity_created(instance)