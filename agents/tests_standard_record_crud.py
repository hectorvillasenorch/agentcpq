"""DB-backed tests for standard-record FK resolution and symmetric CRUD."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from cpq.models import Account, Activity, Contact, Opportunity, Product

from agents import standard_record_agent as sra
from agents.standard_record_agent import (
    _find_contract,
    _find_product,
    _find_quote,
    _find_quote_line,
    _persist_update,
    _resolve_related_instance,
)


class RelatedInstanceResolutionTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(sku="SKU-001", name="Widget", price=10.0)

    def test_resolve_product_by_sku(self):
        self.assertEqual(_resolve_related_instance(Product, "SKU-001").id, self.product.id)

    def test_resolve_product_by_numeric_id(self):
        self.assertEqual(_resolve_related_instance(Product, str(self.product.id)).id, self.product.id)

    def test_resolve_returns_none_for_missing(self):
        self.assertIsNone(_resolve_related_instance(Product, "NOPE-999"))


class FinderFunctionsExistTests(TestCase):
    def test_missing_related_finders_are_defined(self):
        # These were previously undefined (NameError on Subscription/Option create).
        for finder in (_find_quote, _find_quote_line, _find_product, _find_contract):
            self.assertIsNone(finder("does-not-exist"))


class UpdateForeignKeyResolutionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="crudadmin", email="admin@example.com", password="pw"
        )
        self.account = Account.objects.create(name="Acme")
        self.contact = Contact.objects.create(
            first_name="John", last_name="Doe", email="john@acme.com", account=self.account
        )
        self.opportunity = Opportunity.objects.create(name="Big Deal", account=self.account)
        self.activity = Activity.objects.create(subject="Intro call", activity_type="call")

    def test_update_activity_resolves_fks_by_identifier(self):
        ok, message, _payload = _persist_update(
            self.user,
            "Activity",
            str(self.activity.id),
            {"contact": "john@acme.com", "opportunity": "Big Deal", "status": "completed"},
        )
        self.assertTrue(ok, message)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.contact_id, self.contact.id)
        self.assertEqual(self.activity.opportunity_id, self.opportunity.id)
        self.assertEqual(self.activity.status, "completed")

    def test_update_fk_not_found_returns_error(self):
        ok, message, _payload = _persist_update(
            self.user,
            "Activity",
            str(self.activity.id),
            {"contact": "missing@example.com"},
        )
        self.assertFalse(ok)
        self.assertIn("not found", message)


class DeleteConfirmationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username="deleter", email="delete@example.com", password="pw"
        )
        self.account = Account.objects.create(name="Doomed")

    @mock.patch.object(sra, "_extract_delete_requests")
    def test_delete_asks_for_confirmation_instead_of_deleting(self, mock_extract):
        mock_extract.return_value = (
            {
                "delete_standard_record": [
                    {"data": {"object": "Account", "identifier": "Doomed"}, "completed": True}
                ],
                "agent_message": "",
                "summary": "",
            },
            0,
            0,
        )
        result = sra._delete_standard_records(self.user, "delete account Doomed", {})
        self.assertIn("yes", result["message"].lower())
        self.assertIn("Doomed", result["message"])
        # Nothing deleted yet.
        self.assertTrue(Account.objects.filter(name="Doomed").exists())

    def test_delete_confirmation_phase_performs_delete(self):
        session_data = {
            "pending_delete": {"requests": [{"object": "Account", "identifier": "Doomed"}]}
        }
        result = sra._delete_standard_records(self.user, "yes", session_data)
        self.assertIn("Deleted", result["message"])
        self.assertFalse(Account.objects.filter(name="Doomed").exists())
