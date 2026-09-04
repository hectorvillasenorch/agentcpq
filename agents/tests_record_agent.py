import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from cpq.models import Account, BusinessRule, Opportunity

from agents.record_agent import update_single_record_from_ui
from agents.utils.record_agent.handle_helpers import get_single_record_payload


class RecordAgentHelperTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(username="helperadmin", email="h@h.com", password="pw")
        self.account = Account.objects.create(
            name="Acme Corp",
            industry="Technology",
            phone="555-1234",
            website="https://acme.example.com",
        )

    def test_get_single_record_payload_success(self):
        message, payload = get_single_record_payload(
            user=self.user,
            request_payload={"object": "Account", "identifier": "Acme Corp"},
        )

        self.assertEqual(message, "")
        self.assertIsNotNone(payload)
        self.assertEqual(payload["object"], "Account")
        self.assertEqual(payload["record_value"], "Acme Corp")

        field_map = {field["name"]: field for field in payload["fields"]}
        self.assertIn("name", field_map)
        self.assertIn("industry", field_map)
        self.assertIn("website", field_map)

        self.assertEqual(field_map["name"]["raw_value"], "Acme Corp")
        self.assertEqual(field_map["industry"]["raw_value"], "Technology")
        self.assertEqual(field_map["website"]["raw_value"], "https://acme.example.com")
        self.assertEqual(field_map["name"]["data_type"], "text")
        self.assertTrue(field_map["industry"]["is_editable"])

    def test_get_single_record_payload_not_found(self):
        message, payload = get_single_record_payload(
            user=None,
            request_payload={"object": "Account", "identifier": "Missing"},
        )

        self.assertIn("wasn’t able to find", message)
        self.assertIsNone(payload)


class RecordAgentUpdateTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(username="tester", email="t@t.com", password="secret")
        self.account = Account.objects.create(
            name="Acme Corp",
            industry="Technology",
            phone="555-1234",
            website="https://acme.example.com",
        )

    def test_update_single_record_from_ui(self):
        payload = {
            "object": "Account",
            "record_id": self.account.id,
            "updates": [
                {
                    "field": "industry",
                    "value": "Financial Services",
                    "data_type": "text",
                    "is_custom": False,
                },
                {
                    "field": "website",
                    "value": "https://acme.example.org",
                    "data_type": "text",
                    "is_custom": False,
                },
            ],
            "hiddenMessage": True,
        }

        response = update_single_record_from_ui(
            self.user,
            f"Update Record: {json.dumps(payload)}",
            session_data={},
        )

        self.account.refresh_from_db()

        self.assertIn("updated successfully", response.get("message", ""))
        self.assertTrue(response.get("hiddenMessage"))
        self.assertEqual(self.account.industry, "Financial Services")
        self.assertEqual(self.account.website, "https://acme.example.org")

        updated_fields = {field["name"]: field for field in response["single_record"]["fields"]}
        self.assertEqual(updated_fields["industry"]["raw_value"], "Financial Services")
        self.assertEqual(updated_fields["website"]["raw_value"], "https://acme.example.org")

    def test_update_single_record_from_ui_blocks_validation_rule(self):
        account = Account.objects.create(
            name="Validation Account",
            industry="Tech",
            phone="555-0000",
            website="https://validation.example.com",
        )
        opportunity = Opportunity.objects.create(
            name="Validation Opp",
            account=account,
            stage="Prospecting",
        )

        BusinessRule.objects.create(
            name="VR-TEST-OPP-STAGE",
            description="Block Closed Won",
            rule_type="validation",
            target_type="opportunity",
            priority=100,
            error_message="Cannot set stage to Closed Won.",
            active=True,
            conditions={
                "items": [{"fieldName": "stage", "operator": "==", "value": "Closed Won"}],
                "logic": "AND",
            },
        )

        payload = {
            "object": "Opportunity",
            "record_id": opportunity.id,
            "updates": [
                {"field": "stage", "value": "Closed Won", "data_type": "text", "is_custom": False}
            ],
            "hiddenMessage": True,
        }

        response = update_single_record_from_ui(
            self.user,
            f"Update Record: {json.dumps(payload)}",
            session_data={},
        )

        opportunity.refresh_from_db()

        self.assertIn("Validation failed", response.get("message", ""))
        self.assertEqual(opportunity.stage, "Prospecting")

        updated_fields = {field["name"]: field for field in response["single_record"]["fields"]}
        self.assertEqual(updated_fields["stage"]["raw_value"], "Prospecting")
