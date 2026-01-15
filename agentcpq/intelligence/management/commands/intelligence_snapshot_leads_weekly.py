from django.core.management.base import BaseCommand

from agentcpq.intelligence.jobs import run_leads_metric_snapshot


class Command(BaseCommand):
    help = "Generate weekly lead intelligence snapshots."

    def handle(self, *args, **options):
        run_leads_metric_snapshot("week")
        self.stdout.write(self.style.SUCCESS("Lead intelligence weekly snapshot complete."))
