from django.core.management.base import BaseCommand
from cpq.tasks.email_scheduler import deliver_due_scheduled_emails


class Command(BaseCommand):
    help = "Deliver all ScheduledEmail reminders whose send_at has passed."

    def handle(self, *args, **options):
        deliver_due_scheduled_emails()
        self.stdout.write(self.style.SUCCESS("Done delivering scheduled emails."))
