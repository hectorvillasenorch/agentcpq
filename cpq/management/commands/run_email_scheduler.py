# notifications/management/commands/run_email_scheduler.py
import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from cpq.models import EmailAlert, Quote, Subscription, EmailAlertLog
from cpq.notifications.notifications import notify_users
from croniter import croniter
import logging

logger = logging.getLogger(__name__)

# -------------------------
# Helpers
# -------------------------
def has_already_been_sent(alert, instance):
    return EmailAlertLog.objects.filter(
        email_alert=alert,
        instance_type=instance.__class__.__name__,
        instance_id=instance.id
    ).exists()

def log_sent(alert, instance):
    EmailAlertLog.objects.create(
        email_alert=alert,
        instance_type=instance.__class__.__name__,
        instance_id=instance.id
    )

# -------------------------
# Offset-based alerts
# -------------------------
def process_offset_email_alerts():
    today = timezone.now().date()
    alerts = EmailAlert.objects.filter(active=True, offset_days__isnull=False)

    for alert in alerts:
        target_date = today + timedelta(days=alert.offset_days)
        objects = []

        if alert.trigger == "quote_expiring":
            objects = Quote.objects.filter(expiration_date=target_date)
        elif alert.trigger == "subscription_renewal":
            objects = Subscription.objects.filter(end_date=target_date, status="Active")
        else:
            continue

        for obj in objects:
            if has_already_been_sent(alert, obj):
                continue
            try:
                notify_users(
                    alerts=[alert],
                    instance=obj,
                    template_name=alert.trigger,
                    subject=f"Reminder: {alert.trigger.replace('_',' ').title()}",
                    context_builder=lambda inst, user: {"object": inst, "user": user},
                )
                log_sent(alert, obj)
                logger.info(f"✅ Offset alert sent: {alert} for {obj}")
            except Exception as e:
                logger.error(f"❌ Failed offset alert {alert} for {obj}: {e}")

# -------------------------
# Scheduled cron alerts
# -------------------------
def process_scheduled_alerts():
    now = timezone.now()
    alerts = EmailAlert.objects.filter(active=True, scheduled_cron__isnull=False)

    for alert in alerts:
        iter = croniter(alert.scheduled_cron, now - timedelta(minutes=1))
        next_run = iter.get_next(timezone.datetime)

        if next_run > now:
            continue

        objects = []
        if alert.trigger == "quote_expiring":
            objects = Quote.objects.filter(expiration_date__range=[now.date(), now.date()+timedelta(days=7)])
        elif alert.trigger == "subscription_renewal":
            objects = Subscription.objects.filter(end_date__range=[now.date(), now.date()+timedelta(days=7)], status="Active")
        else:
            continue

        for obj in objects:
            if has_already_been_sent(alert, obj):
                continue
            try:
                notify_users(
                    alerts=[alert],
                    instance=obj,
                    template_name="weekly_digest",
                    subject=f"📅 Scheduled Alert: {alert.trigger.replace('_',' ').title()}",
                    context_builder=lambda inst, user: {"object": inst, "user": user},
                )
                log_sent(alert, obj)
                logger.info(f"✅ Scheduled alert sent: {alert} for {obj}")
            except Exception as e:
                logger.error(f"❌ Failed scheduled alert {alert} for {obj}: {e}")

# -------------------------
# Weekly digest (opcional)
# -------------------------
def weekly_digest():
    today = timezone.now().date()
    next_week = today + timedelta(days=7)

    subscriptions = Subscription.objects.filter(end_date__range=[today, next_week], status="Active")
    quotes = Quote.objects.filter(expiration_date__range=[today, next_week])

    if subscriptions.exists() or quotes.exists():
        alerts = EmailAlert.objects.filter(
            trigger__in=["subscription_renewal","quote_expiring"],
            scheduled_cron__isnull=False,
            active=True
        )
        for alert in alerts:
            for obj in list(subscriptions) + list(quotes):
                if has_already_been_sent(alert, obj):
                    continue
                try:
                    notify_users(
                        alerts=[alert],
                        instance=obj,
                        template_name="weekly_digest",
                        subject="📅 Weekly Digest: Expiring Quotes & Renewals",
                        context_builder=lambda inst, user: {"object": inst, "user": user},
                    )
                    log_sent(alert, obj)
                    logger.info(f"✅ Weekly digest alert sent: {alert} for {obj}")
                except Exception as e:
                    logger.error(f"❌ Failed weekly digest {alert} for {obj}: {e}")

# -------------------------
# Command principal
# -------------------------
class Command(BaseCommand):
    help = "Run email alerts scheduler (offset_days + scheduled_cron + weekly_digest)"

    def handle(self, *args, **kwargs):
        self.stdout.write("🚀 Email scheduler started...")

        while True:
            try:
                process_offset_email_alerts()
                process_scheduled_alerts()
                weekly_digest()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            time.sleep(60)  # revisa cada minuto
