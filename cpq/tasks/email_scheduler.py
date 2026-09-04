import time
import logging
from datetime import timedelta

from django.apps import apps
from django.db import close_old_connections
from django.utils import timezone

from cpq.models import ScheduledEmail

logger = logging.getLogger(__name__)

# How often (seconds) the daemon thread checks for due emails.
POLL_INTERVAL_SECONDS = 60


def deliver_due_scheduled_emails():
    """Send every ScheduledEmail whose send_at has passed.

    Re-fetches the triggering record and re-evaluates the trigger's conditions to
    rebuild the alias context, then runs the EMAIL action exactly as the engine would.
    """
    close_old_connections()
    now = timezone.now()

    try:
        items = list(ScheduledEmail.objects.filter(status="pending", send_at__lte=now).select_related("trigger"))
    except Exception:
        # Table may not exist yet (e.g. during `migrate` on a fresh deploy) — no-op.
        return

    from cpq.action_trigger.trigger_engine import engine
    from cpq.action_trigger.email.email_action import execute_email_action

    for item in items:
        try:
            model = apps.get_model(item.instance_model)
            instance = model.objects.get(pk=item.instance_id)
        except Exception as exc:  # record deleted / model missing
            item.attempts += 1
            item.last_error = f"Instance not found: {exc}"
            item.status = "failed"
            item.updated_at = now
            item.save(update_fields=["attempts", "last_error", "status", "updated_at"])
            continue

        try:
            trigger = item.trigger
            context = {}
            if trigger is not None:
                # Re-evaluate conditions to rebuild alias context used by merge fields.
                try:
                    _matched, alias_map = engine._evaluate_trigger(trigger, instance)
                    context = dict(alias_map or {})
                except Exception:
                    context = {}
                context["_trigger"] = trigger
            if context.get(None) is None:
                context[None] = instance

            execute_email_action(action=item.action, instance=instance, context=context)
            item.status = "sent"
            item.last_error = ""
        except Exception as exc:
            item.status = "failed"
            item.last_error = str(exc)

        item.attempts += 1
        item.updated_at = timezone.now()
        item.save(update_fields=["attempts", "last_error", "status", "updated_at"])

    close_old_connections()


def start_email_scheduler(stop_event=None):
    """Run once immediately, then poll every POLL_INTERVAL_SECONDS for due emails."""
    logger.info("📧 Email scheduler started")
    deliver_due_scheduled_emails()

    while True:
        if stop_event:
            if stop_event.wait(timeout=POLL_INTERVAL_SECONDS):
                logger.info("🛑 Email scheduler stop signal received; shutting down")
                break
        else:
            time.sleep(POLL_INTERVAL_SECONDS)

        deliver_due_scheduled_emails()
