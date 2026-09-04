from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from cpq.models import Account, Opportunity, Quote

from .quote_agent import create_quote


class QuoteTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(username="quoteuser", email="q@q.com", password="pw")
        self.account = Account.objects.create(name="Test Account")
        self.opportunity = Opportunity.objects.create(name="Test Opportunity", account=self.account)

    @mock.patch("agents.quote_agent.generate_final_create_quote_message")
    @mock.patch("agents.quote_agent.get_or_create_account_and_opportunity")
    @mock.patch("agents.quote_agent.extract_quote_details_with_llm")
    def test_create_quote(self, mock_extract, mock_account_opp, mock_generate):
        mock_extract.return_value = (
            {
                "create_quote": {
                    "completed": True,
                    "data": {
                        "account": "Test Account",
                        "opportunity": "Test Opportunity",
                        "products": [],
                    },
                },
                "summary": "",
                "agent_message": "",
            },
            0,
            0.0,
        )
        mock_account_opp.return_value = (self.account, self.opportunity, "")
        mock_generate.return_value = ("✅ Quote Q-00001 created", "summary", 0, 0.0)

        response = create_quote(self.user, "create a quote for Test Account", {})

        self.assertIsNotNone(response)
        self.assertIn("created", response.get("message", "").lower())
        self.assertTrue(Quote.objects.filter(account=self.account).exists())
