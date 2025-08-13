from django.db.models.signals import post_save
from django.dispatch import receiver
from cpq.models import Quote,Tenant,QuoteDocumentSettings, Account, Opportunity, CustomObject, CustomField, CustomRecord
from hubspot.views import sync_quote_to_hubspot
from .notifications.quote_notifications import notify_account_created, notify_opportunity_created
from .custom_objects.custom_objects import set_custom_indentifier

@receiver(post_save, sender=Quote)
def handle_primary_quote_sync(sender, instance, **kwargs):
    if instance.hs_primary and instance.hs_deal_id:
        sync_quote_to_hubspot(instance)


@receiver(post_save, sender=CustomRecord)
def set_or_create_custom_identifier_for_record(sender, instance, created, **kwargs):
    if created:
        set_custom_indentifier(instance)

# Email notifications post-save for Account
@receiver(post_save, sender=Account)
def send_account_created_email(sender, instance, created, **kwargs):
    if created:
        notify_account_created(instance)

#@receiver(post_save, sender=Opportunity)
#def send_opportunity_created_email(sender, instance, created, **kwargs):
#    if created:
#        notify_opportunity_created(instance)