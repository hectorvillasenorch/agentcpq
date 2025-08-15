from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from cpq.models import Quote,Tenant,QuoteDocumentSettings, Account, Opportunity, CustomObject, CustomField, CustomRecord
from hubspot.views import sync_quote_to_hubspot
from .notifications.quote_notifications import notify_account_created, notify_opportunity_created
from .custom_objects.custom_objects import set_custom_indentifier
from agents.utils.quote_agent.general_helpers import set_custom_fields_into_quote_document_settings

@receiver(post_save, sender=Quote)
def handle_primary_quote_sync(sender, instance, **kwargs):
    if instance.hs_primary and instance.hs_deal_id:
        sync_quote_to_hubspot(instance)

@receiver(post_save, sender=CustomField)
def set_custom_fields_to_quote_template(sender, instance, **kwargs):
    set_custom_fields_into_quote_document_settings(["Product", "Quote"])

@receiver(post_delete, sender=CustomField)
def update_quote_template_after_delete(sender, instance, **kwargs):
    """
    Se ejecuta después de borrar un CustomField.
    Actualiza la configuración de QuoteDocumentSettings para eliminarlo de rendered/omitted.
    """
    # Aquí le pasas los object_types que quieres mantener visibles
    set_custom_fields_into_quote_document_settings(["Product", "Quote"])


@receiver(post_save, sender=CustomRecord)
def set_or_create_custom_identifier_for_record(sender, instance, created, **kwargs):
    if created:
        set_custom_indentifier(instance)

# Email notifications post-save for Account
@receiver(post_save, sender=Account)
def send_account_created_email(sender, instance, created, **kwargs):
    if created:
        notify_account_created(instance)

#The email notification is not sent through this method because it is triggered directly when creating the opportunity in the quote.
#@receiver(post_save, sender=Opportunity)
#def send_opportunity_created_email(sender, instance, created, **kwargs):
#    if created:
#        notify_opportunity_created(instance)