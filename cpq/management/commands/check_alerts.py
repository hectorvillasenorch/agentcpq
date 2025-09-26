# notifications/management/commands/check_alerts.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from cpq.models import EmailAlert, Quote, Subscription, EmailAlertLog
from cpq.notifications.notifications import notify_users
import logging
from croniter import croniter

logger = logging.getLogger(__name__)

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

def process_offset_email_alerts():
    today = timezone.now().date()
    alerts = EmailAlert.objects.filter(active=True, offset_days__isnull=False)

    for alert in alerts:
        target_date = today + timedelta(days=alert.offset_days)

        if alert.trigger == "quote_expiring":
            queryset = Quote.objects.filter(expiration_date=target_date)
        elif alert.trigger == "subscription_renewal":
            queryset = Subscription.objects.filter(end_date=target_date)
        else:
            continue

        for instance in queryset:
            if has_already_been_sent(alert, instance):
                continue

            try:
                notify_users(
                    alerts=[alert],
                    instance=instance,
                    template_name=alert.trigger,
                    subject=f"Reminder: {alert.trigger.replace('_', ' ').title()}",
                    context_builder=lambda inst, user: {"object": inst, "user": user},
                )
                log_sent(alert, instance)
                logger.info(f"✅ Alert sent: {alert} for {instance}")
            except Exception as e:
                logger.error(f"❌ Failed to send alert {alert} for {instance}: {e}")

def weekly_digest():
    today = timezone.now().date()
    next_week = today + timedelta(days=7)

    subscriptions = Subscription.objects.filter(end_date__range=[today, next_week])
    quotes = Quote.objects.filter(expiration_date__range=[today, next_week])

    alerts = EmailAlert.objects.filter(
        trigger__in=["subscription_renewal", "quote_expiring"],
        scheduled_cron__isnull=False,
        active=True
    )

    for alert in alerts:
        if alert.scheduled_cron:
            # Validar si hoy toca ejecutar la alerta según cron
            base = timezone.now()
            iter = croniter(alert.scheduled_cron, base - timedelta(minutes=1))
            if iter.get_next(timezone.datetime) > base:
                continue  # No toca hoy

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
                logger.info(f"✅ Weekly digest sent: {alert} for {obj}")
            except Exception as e:
                logger.error(f"❌ Failed weekly digest {alert} for {obj}: {e}")

class Command(BaseCommand):
    help = "Check subscriptions and quotes expiring soon and send email alerts"

    def handle(self, *args, **kwargs):
        self.stdout.write("🔍 Running email alerts check...")

        process_offset_email_alerts()
        self.stdout.write("✅ Offset alerts processed.")

        weekly_digest()
        self.stdout.write("✅ Weekly digest processed.")

        self.stdout.write("🎉 All email alerts check finished.")
