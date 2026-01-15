from django.db.models.signals import pre_save, post_save, pre_delete, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from cpq.models import Lead,Quote,Tenant,Quote,QuoteDocumentSettings, Account, Opportunity, CustomObject, CustomField, CustomRecord, CustomFieldValue
from hubspot.views import sync_quote_to_hubspot
from .custom_objects.custom_objects import set_custom_indentifier
from agents.utils.quote_agent.general_helpers import (
    restrict_quote_document_settings_to_line_item_object_types,
    set_custom_fields_into_quote_document_settings,
)
import logging, threading

from cpq.action_trigger.virtual_events import get_collector, schedule_flush_on_commit
from cpq.action_trigger.signal_controls import should_skip_signals

User = get_user_model()

# Async helper used by some notification signals
from .utils import run_async

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

# Actions and contracts
from cpq.action_trigger.trigger_engine import engine as action_trigger_engine

# Action Trigger Helpers
#from .action_trigger.expression_evaluator import dispatch_trigger

@receiver(post_save, sender=Quote)
def handle_primary_quote_sync(sender, instance, **kwargs):
    if should_skip_signals():
        return
    if instance.hs_primary and instance.hs_deal_id:
        sync_quote_to_hubspot(instance)

@receiver(post_save, sender=CustomField)
def set_custom_fields_to_quote_template(sender, instance, **kwargs):
    if should_skip_signals():
        return
    restrict_quote_document_settings_to_line_item_object_types(["QuoteLine"])
    set_custom_fields_into_quote_document_settings(["QuoteLine"])

@receiver(post_delete, sender=CustomField)
def update_quote_template_after_delete(sender, instance, **kwargs):
    if should_skip_signals():
        return
    restrict_quote_document_settings_to_line_item_object_types(["QuoteLine"])
    set_custom_fields_into_quote_document_settings(["QuoteLine"])

# ---------------- VIRTUAL EVENTS ------------------------------

@receiver(post_save, sender=CustomRecord)
def collect_custom_record_event(sender, instance, created, **kwargs):
    if should_skip_signals():
        return
    collector = get_collector()

    action = "create" if created else "update"

    collector.add(
        object_name=instance.object_type.name,
        instance=instance,
        action=action,
        source="custom_record",
    )
    
    schedule_flush_on_commit()


@receiver(post_delete, sender=CustomRecord)
def collect_custom_record_delete(sender, instance, **kwargs):
    if should_skip_signals():
        return
    collector = get_collector()

    collector.add(
        object_name=instance.object_type.name,
        instance=instance,
        action="delete",
        source="custom_record",
    )

    schedule_flush_on_commit()

@receiver(post_save, sender=CustomFieldValue)
def collect_custom_field_value_event(sender, instance, created, **kwargs):
    if should_skip_signals():
        return
    record = instance.record
    if not record:
        return

    collector = get_collector()

    collector.add(
        object_name=record.object_type.name,
        instance=record,
        action="update",
        source="custom_field_value",
    )

    schedule_flush_on_commit()


# ---------------- DEACTIVE LATER ------------------------------

# 📧🔔 EMAIL NOTIFICATIONS SIGNALS
#from .utils import run_async
# LEAD HAS BEEN CREATED
# ACCOUNT HAS BEEN CREATE
#@receiver(post_save, sender=Account)
#def send_account_created_email(sender, instance, created, **kwargs):
#    if created:
#        run_async(notify_account_created, instance)

# USER HAS BEEN CREATED
#@receiver(post_save, sender=User)
#def send_user_created_email(sender, instance, created, **kwargs):
#    if created:
#        run_async(notify_user_created, instance)

# OPPORTUNITY HAS BEEN CREATED
#@receiver(post_save, sender=Opportunity)
#def send_opportunity_created_email(sender, instance, created, **kwargs):
#    if created:
#        run_async(notify_opportunity_created, instance)

# OPPORTUNITY HAS CHANGE STAGE TO CLOSED WON OR CLOSED LOST
@receiver(pre_save, sender=Opportunity)
def check_opportunity_stage_change(sender, instance, **kwargs):
    if should_skip_signals():
        return
    if not instance.pk:
        return
    try:
        old_instance = Opportunity.objects.get(pk=instance.pk)
    except Opportunity.DoesNotExist:
        return

    if old_instance.stage != instance.stage:
        if instance.stage == "closedwon":
            print(f"\n{instance.name} moved to Closed Won ✅.\n")
            run_async(notify_opportunity_closed_won, instance)

            # Action Trigger
            action_trigger_engine.handle_event(
                object_type="opportunity",
                action="closedwon",
                instance=instance,
                signal_timing="post_save",
            )

        elif instance.stage == "closedlost":
            print(f"Opportunity {instance.name} moved to Closed Lost ❌")
            run_async(notify_opportunity_closed_lost, instance)


# QUOTE IS SENT FOR APPROVAL
#@receiver(pre_save, sender=Quote)
#def check_quote_status_change(sender, instance, **kwargs):
#    if not instance.pk:
        # Es nuevo, no hay cambio
#        return

#    try:
#        old_instance = Quote.objects.get(pk=instance.pk)
#    except Quote.DoesNotExist:
#        return

    # Compara el status anterior con el nuevo
#    if old_instance.status != instance.status:
#        if instance.status == "Pending Approval":
#            logging.info(f"Quote {instance.id} status changed to Pending Approval 🟢")
            # Aquí llamas a la función que quieras, por ejemplo:
#            run_async(notify_quote_sent_for_approval, instance)

# QUOTE HAS BEEN APPROVED
#@receiver(pre_save, sender=Quote)
#def quote_approved_signal(sender, instance, **kwargs):
#    if not instance.pk:
        # This is a new quote, no previous status to compare
#        return

#    try:
#        old_instance = Quote.objects.get(pk=instance.pk)
#    except Quote.DoesNotExist:
#        return

    # Compare previous status with the new status
#    if old_instance.status != instance.status:
#        if instance.status == "Approved":
#            logging.info(f"Quote {instance.id} changed to Approved ✅")
            # Call your notification or post-approval logic here
#            run_async(notify_quote_approved, instance)


# QUOTE HAS BEEN REJECTED
#@receiver(pre_save, sender=Quote)
#def quote_rejected_signal(sender, instance, **kwargs):
#    if not instance.pk:
        # This is a new quote, no previous status to compare
#        return

#    try:
#        old_instance = Quote.objects.get(pk=instance.pk)
#    except Quote.DoesNotExist:
#        return

    # Compare previous status with the new status
    # (Disabled: this block was part of a commented-out signal and should not run at module import time.)
    # if old_instance.status != instance.status:
    #     if instance.status == "Rejected":
    #         logging.info(f"Quote {instance.id} changed to Rejected ❌")
    #         run_async(notify_quote_rejected, instance)
