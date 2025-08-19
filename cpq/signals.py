from django.db.models.signals import pre_save, post_save, pre_delete, post_delete
from django.dispatch import receiver
from cpq.models import Lead,Quote,Tenant,QuoteDocumentSettings, Account, Opportunity, CustomObject, CustomField, CustomRecord
from hubspot.views import sync_quote_to_hubspot
from .custom_objects.custom_objects import set_custom_indentifier
from agents.utils.quote_agent.general_helpers import set_custom_fields_into_quote_document_settings

# EMAIL ALERT FUNCTIONS
from .notifications.notifications import notify_lead_created, notify_account_created, notify_opportunity_created


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
    Executes after deleting a CustomField.
    Updates the QuoteDocumentSettings configuration to remove it from rendered/omitted.
    """
    # Here you pass the object_types you want to keep visible
    set_custom_fields_into_quote_document_settings(["Product", "Quote"])


@receiver(post_save, sender=CustomRecord)
def set_or_create_custom_identifier_for_record(sender, instance, created, **kwargs):
    if created:
        set_custom_indentifier(instance)



# 📧🔔 EMAIL NOTIFICATIONS SIGNALS

# LEAD HAS BEEN CREATED
@receiver(post_save, sender=Lead)
def send_lead_created_email(sender, instance, created, **kwargs):
    if created:
        notify_lead_created(instance)

# ACCOUNT HAS BEEN CREATE
@receiver(post_save, sender=Account)
def send_account_created_email(sender, instance, created, **kwargs):
    if created:
        notify_account_created(instance)

# OPPORTUNITY HAS BEEN CREATED
@receiver(post_save, sender=Opportunity)
def send_opportunity_created_email(sender, instance, created, **kwargs):
    if created:
        notify_opportunity_created(instance)


# OPPORTUNITY HAS CHANGE STAGE TO CLOSED WON OR CLOSED LOST
@receiver(pre_save, sender=Opportunity)
def check_opportunity_stage_change(sender, instance, **kwargs):
    if not instance.pk:
        # Si es nuevo, no tiene cambios
        return
    
    try:
        old_instance = Opportunity.objects.get(pk=instance.pk)
    except Opportunity.DoesNotExist:
        return

    # Comparar stage anterior con el nuevo
    if old_instance.stage != instance.stage:
        if instance.stage == "Closed Won":
            print(f"Opportunity {instance.id} moved to Closed Won ✅")
            # Aquí llamas a tu función
            # notify_opportunity_closed_won(instance)

        elif instance.stage == "Closed Lost":
            print(f"Opportunity {instance.id} moved to Closed Lost ❌")
            # notify_opportunity_closed_lost(instance)