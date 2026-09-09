from django.core.management.base import BaseCommand
from cpq.tasks.email_scheduler import scan_stale_reminders, deliver_due_scheduled_emails


class Command(BaseCommand):
    help = "Scan for stale leads (no update in N days) and enqueue/deliver reminder emails."

    def handle(self, *args, **options):
        created = scan_stale_reminders() or 0
        self.stdout.write(self.style.SUCCESS(f"Stale scan enqueued {created} reminder email(s)."))
        deliver_due_scheduled_emails()
        self.stdout.write(self.style.SUCCESS("Delivered any due scheduled emails."))
