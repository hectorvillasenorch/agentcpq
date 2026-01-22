from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cpq.models import Product
from salesforce.utils import get_valid_salesforce_token, soql_query_all, validate_salesforce_connection


PRODUCT2_SOQL = (
    "SELECT Id, Name, ProductCode, Family, IsActive, Description "
    "FROM Product2"
)


class Command(BaseCommand):
    help = "Sync Salesforce Product2 records into AgentCPQ Products."

    def add_arguments(self, parser):
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help="Include inactive Product2 records.",
        )
        parser.add_argument(
            "--match-sku",
            action="store_true",
            help="Match existing products by SKU when external_id is missing.",
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Update existing Product fields when a Product2 match is found.",
        )
        parser.add_argument(
            "--use-standard-pricebook",
            action="store_true",
            help="Set price from the Standard Pricebook if available.",
        )
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
        timeout = options["timeout"]
        token = get_valid_salesforce_token(timeout=timeout)
        if not token:
            raise CommandError("No Salesforce token found. Authenticate first.")

        status = validate_salesforce_connection(token, timeout=timeout)
        if not status.get("authenticated"):
            raise CommandError(f"Salesforce auth invalid: {status.get('errors')}")

        soql = PRODUCT2_SOQL
        if not options["include_inactive"]:
            soql = f"{soql} WHERE IsActive = true"

        product_records, response = soql_query_all(token, soql, timeout=timeout)
        if product_records is None:
            raise CommandError(
                f"Failed to fetch Product2 records (HTTP {response.status_code})."
            )

        price_map = {}
        if options["use_standard_pricebook"]:
            standard_id = self._get_standard_pricebook_id(token, timeout)
            if standard_id:
                price_map = self._get_standard_prices(token, standard_id, timeout)
            else:
                self.stderr.write(self.style.WARNING("Standard Pricebook not found."))

        created = 0
        updated = 0
        skipped = 0
        dry_run = options["dry_run"]

        now = timezone.now()
        for record in product_records:
            sf_id = record.get("Id")
            if not sf_id:
                skipped += 1
                continue

            name = record.get("Name") or ""
            family = record.get("Family") or "Uncategorized"
            family = family[:50]
            description = record.get("Description") or ""
            is_active = record.get("IsActive", True)

            sku = self._build_sku(record)
            if not sku:
                sku = f"SF-{sf_id}"
            sku = sku[:100]

            product = Product.objects.filter(external_id=sf_id).first()
            if not product and options["match_sku"]:
                product = Product.objects.filter(sku=sku).first()
                if product and not product.external_id:
                    if not dry_run:
                        product.external_id = sf_id
                        product.save(update_fields=["external_id"])
                    updated += 1

            if product:
                if not options["update_existing"]:
                    if not dry_run:
                        Product.objects.filter(pk=product.pk).update(last_synced_at=now)
                    skipped += 1
                    continue
                updates = {}
                price = price_map.get(sf_id)
                if name and product.name != name:
                    updates["name"] = name
                if family and product.family != family:
                    updates["family"] = family
                if description and product.description != description:
                    updates["description"] = description
                if product.is_active != is_active:
                    updates["is_active"] = is_active
                if product.sku != sku:
                    updates["sku"] = self._ensure_unique_sku(sku, sf_id, product.id)
                if price is not None and product.price != price:
                    updates["price"] = price
                if not product.external_id:
                    updates["external_id"] = sf_id
                updates["last_synced_at"] = now
                if updates and not dry_run:
                    Product.objects.filter(pk=product.pk).update(**updates)
                if updates:
                    updated += 1
                else:
                    skipped += 1
                continue

            price = price_map.get(sf_id, Decimal("0.00"))
            if not dry_run:
                Product.objects.create(
                    name=name or sku,
                    sku=self._ensure_unique_sku(sku, sf_id),
                    price=price,
                    family=family or "Uncategorized",
                    external_id=sf_id,
                    is_active=is_active,
                    description=description,
                    last_synced_at=now,
                )
            created += 1

        summary = (
            f"Products: +{created} created, {updated} updated, {skipped} skipped."
        )
        if dry_run:
            summary = f"[dry-run] {summary}"
        self.stdout.write(summary)

    def _build_sku(self, record):
        value = record.get("ProductCode") or ""
        value = str(value).strip()
        return value

    def _ensure_unique_sku(self, sku, sf_id, product_id=None):
        candidate = sku
        if product_id:
            exists = Product.objects.exclude(pk=product_id).filter(sku=candidate).exists()
        else:
            exists = Product.objects.filter(sku=candidate).exists()
        if not exists:
            return candidate
        suffix = sf_id[-6:]
        trimmed = candidate[: max(0, 100 - len(suffix) - 1)]
        return f"{trimmed}-{suffix}"

    def _get_standard_pricebook_id(self, token, timeout):
        soql = "SELECT Id FROM Pricebook2 WHERE IsStandard = true LIMIT 1"
        records, response = soql_query_all(token, soql, timeout=timeout)
        if records is None:
            self.stderr.write(
                self.style.WARNING(
                    f"Failed to fetch standard pricebook (HTTP {response.status_code})."
                )
            )
            return None
        if not records:
            return None
        return records[0].get("Id")

    def _get_standard_prices(self, token, pricebook_id, timeout):
        soql = (
            "SELECT Product2Id, UnitPrice "
            f"FROM PricebookEntry WHERE IsActive = true AND Pricebook2Id = '{pricebook_id}'"
        )
        records, response = soql_query_all(token, soql, timeout=timeout)
        if records is None:
            self.stderr.write(
                self.style.WARNING(
                    f"Failed to fetch standard prices (HTTP {response.status_code})."
                )
            )
            return {}

        price_map = {}
        for row in records:
            product_id = row.get("Product2Id")
            if not product_id:
                continue
            unit_price = row.get("UnitPrice")
            try:
                price_map[product_id] = Decimal(str(unit_price))
            except (InvalidOperation, TypeError, ValueError):
                price_map[product_id] = Decimal("0.00")
        return price_map
