from django.db.models.signals import pre_save, post_save, pre_delete, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from cpq.models import Lead,Quote,Tenant,Quote,QuoteDocumentSettings, Account, Opportunity, CustomObject, CustomField, CustomRecord
from hubspot.views import sync_quote_to_hubspot
from .custom_objects.custom_objects import set_custom_indentifier
from agents.utils.quote_agent.general_helpers import set_custom_fields_into_quote_document_settings
import logging, threading

User = get_user_model()

# EMAIL ALERT FUNCTIONS
from .notifications.notifications import (
    notify_lead_created,
    notify_account_created,
    notify_opportunity_created,
    notify_opportunity_closed_won,
    notify_opportunity_closed_lost,
    notify_quote_sent_for_approval,
    notify_quote_approved,
    notify_quote_rejected,
    notify_user_created,
)

from .renewals.renewals import create_contract_after_closed_won

# Action Trigger Helpers
from .action_trigger.action_trigger import dispatch_trigger


@receiver(post_save, sender=Quote)
def handle_primary_quote_sync(sender, instance, **kwargs):
    if instance.hs_primary and instance.hs_deal_id:
        sync_quote_to_hubspot(instance)

@receiver(post_save, sender=CustomField)
def set_custom_fields_to_quote_template(sender, instance, **kwargs):
    set_custom_fields_into_quote_document_settings(["Product", "Quote"])

@receiver(post_delete, sender=CustomField)
def update_quote_template_after_delete(sender, instance, **kwargs):
    set_custom_fields_into_quote_document_settings(["Product", "Quote"])

@receiver(post_save, sender=CustomRecord)
def set_or_create_custom_identifier_for_record(sender, instance, created, **kwargs):
    if created:
        set_custom_indentifier(instance)

# 📧🔔 EMAIL NOTIFICATIONS SIGNALS
from .utils import run_async
# LEAD HAS BEEN CREATED
@receiver(post_save, sender=Lead)
def send_lead_created_email(sender, instance, created, **kwargs):
    if created:
        run_async(notify_lead_created, instance)

# ACCOUNT HAS BEEN CREATE
@receiver(post_save, sender=Account)
def send_account_created_email(sender, instance, created, **kwargs):
    if created:
        run_async(notify_account_created, instance)

# USER HAS BEEN CREATED
@receiver(post_save, sender=User)
def send_user_created_email(sender, instance, created, **kwargs):
    if created:
        run_async(notify_user_created, instance)

# OPPORTUNITY HAS BEEN CREATED
@receiver(post_save, sender=Opportunity)
def send_opportunity_created_email(sender, instance, created, **kwargs):
    if created:
        run_async(notify_opportunity_created, instance)

# OPPORTUNITY HAS CHANGE STAGE TO CLOSED WON OR CLOSED LOST
@receiver(pre_save, sender=Opportunity)
def check_opportunity_stage_change(sender, instance, **kwargs):
    if not instance.pk:
        return
    try:
        old_instance = Opportunity.objects.get(pk=instance.pk)
    except Opportunity.DoesNotExist:
        return

    if old_instance.stage != instance.stage:
        if instance.stage == "closedwon":
            print(f"\n{instance.name} moved to Closed Won ✅.\n")
            create_contract_after_closed_won(instance)
            run_async(notify_opportunity_closed_won, instance)

            # Action Trigger
            dispatch_trigger("opportunity_closed_won", {"opportunity": instance})

        elif instance.stage == "closedlost":
            print(f"Opportunity {instance.name} moved to Closed Lost ❌")
            run_async(notify_opportunity_closed_lost, instance)


# QUOTE IS SENT FOR APPROVAL
@receiver(pre_save, sender=Quote)
def check_quote_status_change(sender, instance, **kwargs):
    if not instance.pk:
        # Es nuevo, no hay cambio
        return

    try:
        old_instance = Quote.objects.get(pk=instance.pk)
    except Quote.DoesNotExist:
        return

    # Compara el status anterior con el nuevo
    if old_instance.status != instance.status:
        if instance.status == "Pending Approval":
            logging.info(f"Quote {instance.id} status changed to Pending Approval 🟢")
            # Aquí llamas a la función que quieras, por ejemplo:
            run_async(notify_quote_sent_for_approval, instance)

# QUOTE HAS BEEN APPROVED
@receiver(pre_save, sender=Quote)
def quote_approved_signal(sender, instance, **kwargs):
    if not instance.pk:
        # This is a new quote, no previous status to compare
        return

    try:
        old_instance = Quote.objects.get(pk=instance.pk)
    except Quote.DoesNotExist:
        return

    # Compare previous status with the new status
    if old_instance.status != instance.status:
        if instance.status == "Approved":
            logging.info(f"Quote {instance.id} changed to Approved ✅")
            # Call your notification or post-approval logic here
            run_async(notify_quote_approved, instance)


# QUOTE HAS BEEN REJECTED
@receiver(pre_save, sender=Quote)
def quote_rejected_signal(sender, instance, **kwargs):
    if not instance.pk:
        # This is a new quote, no previous status to compare
        return

    try:
        old_instance = Quote.objects.get(pk=instance.pk)
    except Quote.DoesNotExist:
        return

    # Compare previous status with the new status
    if old_instance.status != instance.status:
        if instance.status == "Rejected":
            logging.info(f"Quote {instance.id} changed to Rejected ❌")
            # Call your notification or post-rejection logic here
            run_async(notify_quote_rejected, instance)
