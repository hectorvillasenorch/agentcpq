from django.core.management.base import BaseCommand, CommandError

from salesforce.utils import ensure_salesforce_fields, get_valid_salesforce_token, validate_salesforce_connection


REQUIRED_FIELDS = [
    {
        "object": "Opportunity",
        "api_name": "AgentCPQ_Quote_Id__c",
        "type": "Text",
        "length": 36,
        "external_id": True,
        "label": "AgentCPQ Quote Id",
    },
    {
        "object": "Opportunity",
        "api_name": "AgentCPQ_Quote_Number__c",
        "type": "Text",
        "length": 100,
        "label": "AgentCPQ Quote Number",
    },
    {
        "object": "Opportunity",
        "api_name": "AgentCPQ_ACV__c",
        "type": "Currency",
        "precision": 18,
        "scale": 2,
        "label": "AgentCPQ ACV",
    },
    {
        "object": "Opportunity",
        "api_name": "AgentCPQ_NACV__c",
        "type": "Currency",
        "precision": 18,
        "scale": 2,
        "label": "AgentCPQ NACV",
    },
    {
        "object": "Opportunity",
        "api_name": "AgentCPQ_MRR__c",
        "type": "Currency",
        "precision": 18,
        "scale": 2,
        "label": "AgentCPQ MRR",
    },
    {
        "object": "Opportunity",
        "api_name": "AgentCPQ_Forecast_Strategy__c",
        "type": "Picklist",
        "values": ["TOTAL_CONTRACT_VALUE", "BASELINE_ACV_ONLY"],
        "label": "AgentCPQ Forecast Strategy",
    },
    {
        "object": "Product2",
        "api_name": "AgentCPQ_Subscription__c",
        "type": "Checkbox",
        "label": "AgentCPQ Subscription",
        "default_value": False,
    },
    {
        "object": "Product2",
        "api_name": "AgentCPQ_Default_Term__c",
        "type": "Number",
        "precision": 18,
        "scale": 0,
        "label": "AgentCPQ Default Term",
    },
]


class Command(BaseCommand):
    help = "Ensure required Salesforce custom fields exist using the Tooling API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Check for missing fields without creating anything.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=8,
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

        if not status.get("tooling_api_enabled"):
            self.stderr.write(
                self.style.WARNING(
                    "Tooling API check failed; field creation may not be allowed."
                )
            )

        results = ensure_salesforce_fields(
            token,
            REQUIRED_FIELDS,
            timeout=timeout,
            dry_run=options["dry_run"],
        )

        had_error = False
        for result in results:
            line = (
                f"{result['object']}.{result['api_name']}: "
                f"{result['status']}"
            )
            if result.get("details"):
                line = f"{line} ({result['details']})"
            if result["status"] == "error":
                had_error = True
                self.stderr.write(self.style.ERROR(line))
            else:
                self.stdout.write(line)

        if had_error:
            raise CommandError("One or more fields failed to validate or create.")
