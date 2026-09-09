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


# ---------------------------------------------------------------------------
# Stale-record reminders ("email me when a lead has NOT been updated in N days")
# ---------------------------------------------------------------------------
# The engine is event-driven, so it can't fire on an *absence* of updates.
# Instead, triggers whose event_type is {"object_name": "lead", "action": "stale"}
# act as *configuration* for this periodic scan. Format (conditions):
#   - lead.id == <static leadId/external id>       → which lead(s) to watch
#   - lead.updated_at older_than_days <static N>   → inactivity threshold (days)
# The trigger's EMAIL action is used as the reminder. Dedupe: we only remind
# once per stale cycle — i.e., no new email until the lead is updated again.
# ---------------------------------------------------------------------------

STALE_SCAN_INTERVAL_SECONDS = int(__import__("os").getenv("STALE_SCAN_INTERVAL", "1800"))


def _parse_stale_trigger_config(trigger):
    """Return (lead_ids, days) parsed from a stale trigger's conditions."""
    items = (trigger.conditions or {}).get("items") or []
    lead_ids = []
    days = 7  # fallback
    for item in items:
        source = item.get("source") or {}
        target = item.get("target") or {}
        if source.get("object") != "lead":
            continue
        field = source.get("field_name")
        operator = item.get("operator", "==")
        if field == "id" and operator == "==" and target.get("type") == "static":
            val = target.get("value")
            if val:
                lead_ids.append(str(val).strip())
        elif field == "updated_at" and operator == "older_than_days" and target.get("type") == "static":
            try:
                days = int(str(target.get("value")))
            except (TypeError, ValueError):
                pass
    return lead_ids, max(1, days)


def scan_stale_reminders():
    """Email configured recipients when a watched lead hasn't been updated in N days."""
    close_old_connections()
    try:
        from cpq.models import ActionTrigger, Lead, ScheduledEmail as SE

        triggers = list(
            ActionTrigger.objects.filter(active=True).exclude(event_type=None)
        )
    except Exception:
        return  # tables not ready yet (during migrate)

    now = timezone.now()
    created_rows = 0

    for trigger in triggers:
        event = trigger.event_type
        if not isinstance(event, dict):
            continue
        if event.get("object_name") != "lead" or event.get("action") != "stale":
            continue

        lead_ids, days = _parse_stale_trigger_config(trigger)
        if not lead_ids:
            logger.debug("⚠️ stale trigger %s has no watched lead ids", trigger.name)
            continue

        email_action = None
        for action in (trigger.actions or []):
            if isinstance(action, dict) and isinstance(action.get("email"), dict):
                email_action = action
                break
        if email_action is None:
            logger.debug("⚠️ stale trigger %s has no EMAIL action", trigger.name)
            continue

        for lead in Lead.objects.filter(leadId__in=lead_ids):
            if lead.status in ("converted", "disqualified"):
                continue
            if lead.updated_at is None:
                continue
            if now - lead.updated_at < timedelta(days=days):
                continue  # not stale yet

            # Dedupe per stale cycle:
            #  - already reminded since the last update → wait for another update
            already_sent = SE.objects.filter(
                trigger=trigger,
                instance_model="cpq.Lead",
                instance_id=lead.pk,
                status="sent",
                send_at__gte=lead.updated_at,
            ).exists()
            already_pending = SE.objects.filter(
                trigger=trigger,
                instance_model="cpq.Lead",
                instance_id=lead.pk,
                status="pending",
                created_at__gte=now - timedelta(hours=23),
            ).exists()
            if already_sent or already_pending:
                continue

            try:
                SE.objects.create(
                    trigger=trigger,
                    instance_model="cpq.Lead",
                    instance_id=lead.pk,
                    action=email_action,
                    send_at=now,
                    status="pending",
                )
                created_rows += 1
            except Exception as exc:
                logger.warning("⚠️ stale reminder enqueue failed for lead %s: %s", lead.pk, exc)

    if created_rows:
        logger.info("📬 Stale reminder scan enqueued %s email(s)", created_rows)
    close_old_connections()
    return created_rows


def start_email_scheduler(stop_event=None):
    """Run once immediately, then poll for due emails and stale reminders."""
    logger.info("📧 Email scheduler started")
    deliver_due_scheduled_emails()
    _last_stale_scan = time.monotonic()

    while True:
        if stop_event:
            if stop_event.wait(timeout=POLL_INTERVAL_SECONDS):
                logger.info("🛑 Email scheduler stop signal received; shutting down")
                break
        else:
            time.sleep(POLL_INTERVAL_SECONDS)

        deliver_due_scheduled_emails()

        # Periodic stale-lead scan (throttled, default every 30 min).
        if time.monotonic() - _last_stale_scan >= STALE_SCAN_INTERVAL_SECONDS:
            try:
                scan_stale_reminders()
            except Exception:
                logger.exception("Stale reminder scan failed")
            _last_stale_scan = time.monotonic()

