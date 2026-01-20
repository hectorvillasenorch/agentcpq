from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from cpq.models import Pricebook, PricebookEntry, Product
from salesforce.models import SalesforceToken
from salesforce.utils import soql_query_all, validate_salesforce_connection


PRICEBOOK_SOQL = (
    "SELECT Id, Name, IsActive, IsStandard "
    "FROM Pricebook2 WHERE IsActive = true"
)

PRICEBOOK_ENTRY_SOQL = (
    "SELECT Id, Pricebook2Id, Product2Id, UnitPrice, CurrencyIsoCode, IsActive "
    "FROM PricebookEntry WHERE IsActive = true"
)


class Command(BaseCommand):
    help = "Sync Salesforce Pricebook2 and PricebookEntry into local models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch data without writing to the database.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=10,
            help="Salesforce API timeout in seconds.",
        )

    def handle(self, *args, **options):
        token = SalesforceToken.objects.first()
        if not token:
            raise CommandError("No Salesforce token found. Authenticate first.")

        timeout = options["timeout"]
        status = validate_salesforce_connection(token, timeout=timeout)
        if not status.get("authenticated"):
            raise CommandError(f"Salesforce auth invalid: {status.get('errors')}")

        pricebooks, response = soql_query_all(token, PRICEBOOK_SOQL, timeout=timeout)
        if pricebooks is None:
            raise CommandError(
                f"Failed to fetch pricebooks (HTTP {response.status_code})."
            )

        entries, response = soql_query_all(token, PRICEBOOK_ENTRY_SOQL, timeout=timeout)
        if entries is None:
            raise CommandError(
                f"Failed to fetch pricebook entries (HTTP {response.status_code})."
            )

        dry_run = options["dry_run"]
        created_books = 0
        updated_books = 0
        created_entries = 0
        updated_entries = 0
        skipped_entries = 0

        pricebook_map = {}
        for record in pricebooks:
            sf_id = record.get("Id")
            name = record.get("Name") or "Salesforce Pricebook"
            if not sf_id:
                continue
            pricebook_map[sf_id] = name
            if dry_run:
                continue
            obj, created = Pricebook.objects.update_or_create(
                salesforce_id=sf_id,
                defaults={"name": name},
            )
            if created:
                created_books += 1
            else:
                updated_books += 1

        for record in entries:
            entry_id = record.get("Id")
            pricebook_id = record.get("Pricebook2Id")
            product_id = record.get("Product2Id")
            unit_price = record.get("UnitPrice")
            currency = record.get("CurrencyIsoCode")

            if not entry_id or not pricebook_id or not product_id:
                skipped_entries += 1
                continue

            product = Product.objects.filter(external_id=product_id).first()
            if not product:
                skipped_entries += 1
                continue

            if dry_run:
                continue

            pricebook = Pricebook.objects.filter(salesforce_id=pricebook_id).first()
            if not pricebook:
                pricebook = Pricebook.objects.create(
                    salesforce_id=pricebook_id,
                    name=pricebook_map.get(pricebook_id, "Salesforce Pricebook"),
                )
                created_books += 1

            try:
                unit_price_value = Decimal(str(unit_price)) if unit_price is not None else Decimal("0")
            except InvalidOperation:
                unit_price_value = Decimal("0")

            obj, created = PricebookEntry.objects.update_or_create(
                salesforce_id=entry_id,
                defaults={
                    "pricebook": pricebook,
                    "product": product,
                    "unit_price": unit_price_value,
                    "currency_iso_code": currency,
                },
            )
            if created:
                created_entries += 1
            else:
                updated_entries += 1

        summary = (
            f"Pricebooks: +{created_books} created, {updated_books} updated; "
            f"Entries: +{created_entries} created, {updated_entries} updated; "
            f"{skipped_entries} skipped."
        )
        if dry_run:
            summary = f"[dry-run] {summary}"
        self.stdout.write(summary)

        if not dry_run:
            try:
                from cpq.events import emit_domain_event
                emit_domain_event(
                    "PRICEBOOK.SYNCED",
                    payload={
                        "pricebooks_created": created_books,
                        "pricebooks_updated": updated_books,
                        "entries_created": created_entries,
                        "entries_updated": updated_entries,
                        "entries_skipped": skipped_entries,
                    },
                    object_type="Pricebook",
                    source="salesforce_sync",
                )
            except Exception:
                pass
