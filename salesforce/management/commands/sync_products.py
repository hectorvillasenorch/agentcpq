from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from cpq.models import Product, SystemFieldMapping
from salesforce.utils import (
    fetch_salesforce_object_field_metadata,
    get_valid_salesforce_token,
    soql_query_all,
    validate_salesforce_connection,
)


BASE_PRODUCT2_FIELDS = [
    "Id",
    "Name",
    "ProductCode",
    "Family",
    "IsActive",
    "Description",
]


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
        parser.add_argument(
            "--actor-user-id",
            type=int,
            default=None,
            help="Optional AgentCPQ user id to stamp created_by/updated_by on synced products.",
        )

    def handle(self, *args, **options):
        timeout = options["timeout"]
        actor_user = None
        actor_user_id = options.get("actor_user_id")
        if actor_user_id:
            actor_user = get_user_model().objects.filter(pk=actor_user_id).first()

        token = get_valid_salesforce_token(timeout=timeout)
        if not token:
            raise CommandError("No Salesforce token found. Authenticate first.")

        status = validate_salesforce_connection(token, timeout=timeout)
        if not status.get("authenticated"):
            raise CommandError(f"Salesforce auth invalid: {status.get('errors')}")

        mapping_rows = SystemFieldMapping.objects.filter(
            crm="Salesforce",
            field_type="Product",
        )
        mapping = {
            row.local_field: row.crm_field
            for row in mapping_rows
            if row.crm_field
        }

        fields = list(BASE_PRODUCT2_FIELDS)
        for crm_field in mapping.values():
            if not crm_field or "." in crm_field or " " in crm_field:
                continue
            if crm_field not in fields:
                fields.append(crm_field)

        field_metadata, field_response = fetch_salesforce_object_field_metadata(
            token,
            "Product2",
            timeout=timeout,
        )
        if field_metadata is not None:
            available_fields = {
                field.get("name")
                for field in field_metadata
                if field.get("name")
            }
            fields = [field for field in fields if field in available_fields]
        elif field_response is not None:
            self.stderr.write(
                self.style.WARNING(
                    f"Product2 describe failed (HTTP {field_response.status_code}); using default field list."
                )
            )

        soql = f"SELECT {', '.join(fields)} FROM Product2"
        if not options["include_inactive"]:
            soql = f"{soql} WHERE IsActive = true"

        product_records, response = soql_query_all(token, soql, timeout=timeout)
        if product_records is None:
            detail = "request_failed"
            status_code = getattr(response, "status_code", "unknown")
            if response is not None:
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text
            raise CommandError(
                f"Failed to fetch Product2 records (HTTP {status_code}). {detail}"
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

            mapped_values = self._build_mapped_values(mapping, record)

            if product:
                if not options["update_existing"]:
                    if not dry_run:
                        skip_updates = {"last_synced_at": now}
                        if actor_user and not product.created_by_id:
                            skip_updates["created_by_id"] = actor_user.id
                        if actor_user:
                            skip_updates["updated_by_id"] = actor_user.id
                        Product.objects.filter(pk=product.pk).update(**skip_updates)
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
                if mapped_values:
                    for local_field, mapped_value in mapped_values.items():
                        if mapped_value is None:
                            continue
                        if getattr(product, local_field, None) != mapped_value:
                            updates[local_field] = mapped_value
                if actor_user and not product.created_by_id:
                    updates["created_by_id"] = actor_user.id
                if actor_user:
                    updates["updated_by_id"] = actor_user.id
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
                create_kwargs = {
                    "name": name or sku,
                    "sku": self._ensure_unique_sku(sku, sf_id),
                    "price": price,
                    "family": family or "Uncategorized",
                    "external_id": sf_id,
                    "is_active": is_active,
                    "description": description,
                    "last_synced_at": now,
                }
                if actor_user:
                    create_kwargs["created_by"] = actor_user
                    create_kwargs["updated_by"] = actor_user
                if mapped_values:
                    for local_field, mapped_value in mapped_values.items():
                        if mapped_value is None:
                            continue
                        create_kwargs[local_field] = mapped_value
                Product.objects.create(**create_kwargs)
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

    def _build_mapped_values(self, mapping, record):
        if not mapping:
            return {}

        skip_local_fields = {
            "id",
            "pk",
            "external_id",
            "public_id",
            "prdid",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "last_synced_at",
        }

        values = {}
        for local_field, crm_field in mapping.items():
            if not crm_field or local_field in skip_local_fields:
                continue
            if crm_field not in record:
                continue
            raw_value = record.get(crm_field)
            if raw_value is None:
                continue
            try:
                model_field = Product._meta.get_field(local_field)
            except Exception:
                continue
            value = self._coerce_field_value(model_field, raw_value)
            values[local_field] = value

        return values

    def _coerce_field_value(self, field, value):
        if value is None:
            return None
        if isinstance(field, models.BooleanField):
            return bool(value)
        if isinstance(field, models.IntegerField):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        if isinstance(field, models.DecimalField):
            try:
                return Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                return None
        if isinstance(field, models.DateTimeField):
            if isinstance(value, str):
                return parse_datetime(value)
            return value
        if isinstance(field, models.DateField):
            if isinstance(value, str):
                return parse_date(value)
            return value
        if isinstance(value, str):
            return value.strip()
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
