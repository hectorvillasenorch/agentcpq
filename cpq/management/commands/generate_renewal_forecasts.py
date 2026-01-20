from django.core.management.base import BaseCommand

from cpq.renewals.forecasting import generate_renewal_forecasts


class Command(BaseCommand):
    help = "Create renewal forecast opportunities/quotes for expiring subscriptions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute results without writing to the database.",
        )

    def handle(self, *args, **options):
        results = generate_renewal_forecasts(dry_run=options["dry_run"])
        label = "dry-run" if options["dry_run"] else "created"
        self.stdout.write(
            f"{label}: {results['created']} forecasts, skipped: {results['skipped']}, "
            f"window_end: {results['window_end']}"
        )
