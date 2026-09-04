"""Tests for the standard-record LLM request extraction + normalization.

The LLM client is mocked, and the DB-touching `_refresh_allowed_fields` is stubbed,
so these run under SimpleTestCase without a live database or network.
"""
import json
from unittest import mock

from django.test import SimpleTestCase

from agents import standard_record_agent as sra


def _fake_openai_response(payload):
    class _Message:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Message(content)

    class _Response:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    return _Response(json.dumps(payload))


class ExtractCreateRequestsTests(SimpleTestCase):
    def setUp(self):
        # Stub the allowed-field metadata so normalization is deterministic.
        sra.ALLOWED_FIELDS = {
            "Lead": ["first_name", "last_name", "email", "phone", "company", "status", "source"],
        }
        sra.ALLOWED_FIELD_MAP = {
            "Lead": {
                "first_name": "first_name",
                "last_name": "last_name",
                "email": "email",
                "phone": "phone",
                "company": "company",
                "company name": "company",
                "status": "status",
                "source": "source",
            },
        }

    @mock.patch.object(sra, "_refresh_allowed_fields")
    @mock.patch.object(sra, "estimate_cost", return_value=(0, 0.0))
    @mock.patch.object(sra.client.chat.completions, "create")
    def test_normalizes_field_aliases(self, mock_create, _est, _refresh):
        mock_create.return_value = _fake_openai_response(
            {
                "create_standard_record": [
                    {
                        "data": {
                            "object": "Lead",
                            "fields": {
                                "first_name": "John",
                                "last_name": "Doe",
                                "email": "john@acme.com",
                                "Company Name": "Acme Corp",
                                "status": "new",
                            },
                        }
                    }
                ],
                "agent_message": "",
                "summary": "",
            }
        )

        result, _tokens, _cost = sra._extract_create_requests("create a lead", [], None)

        self.assertIsNotNone(result)
        req = result["create_standard_record"][0]
        self.assertTrue(req["completed"])
        self.assertEqual(req["data"]["object"], "Lead")
        self.assertEqual(req["data"]["fields"]["company"], "Acme Corp")
        self.assertNotIn("Company Name", req["data"]["fields"])
        self.assertEqual(req["data"]["fields"]["first_name"], "John")

    @mock.patch.object(sra, "_refresh_allowed_fields")
    @mock.patch.object(sra, "estimate_cost", return_value=(0, 0.0))
    @mock.patch.object(sra.client.chat.completions, "create")
    def test_incomplete_request_is_not_completed(self, mock_create, _est, _refresh):
        mock_create.return_value = _fake_openai_response(
            {
                "create_standard_record": [
                    {"data": {"object": "Lead", "fields": {"first_name": "John"}}}
                ],
                "agent_message": "What is the last name?",
                "summary": "",
            }
        )

        result, _tokens, _cost = sra._extract_create_requests("create a lead John", [], None)

        req = result["create_standard_record"][0]
        self.assertFalse(req["completed"])


class ExtractUpdateRequestsTests(SimpleTestCase):
    def setUp(self):
        sra.ALLOWED_FIELDS = {
            "Lead": ["first_name", "last_name", "email", "phone", "company", "status", "source"],
            "Opportunity": ["name", "account", "stage", "amount", "expected_close_date"],
        }
        sra.ALLOWED_FIELD_MAP = {
            "Lead": {
                "first_name": "first_name",
                "last_name": "last_name",
                "email": "email",
                "phone": "phone",
                "company": "company",
                "status": "status",
                "source": "source",
            },
            "Opportunity": {
                "name": "name",
                "account": "account",
                "stage": "stage",
                "amount": "amount",
                "expected_close_date": "expected_close_date",
            },
        }

    @mock.patch.object(sra, "_refresh_allowed_fields")
    @mock.patch.object(sra, "estimate_cost", return_value=(0, 0.0))
    @mock.patch.object(sra.client.chat.completions, "create")
    def test_normalizes_update(self, mock_create, _est, _refresh):
        mock_create.return_value = _fake_openai_response(
            {
                "update_standard_record": [
                    {
                        "data": {
                            "object": "Opportunity",
                            "identifier": "Renewal Q1",
                            "fields": {"stage": "negotiation"},
                        }
                    }
                ],
                "agent_message": "",
                "summary": "",
            }
        )

        result, _tokens, _cost = sra._extract_update_requests(
            "change opportunity Renewal Q1 stage to negotiation", [], None
        )

        self.assertIsNotNone(result)
        req = result["update_standard_record"][0]
        self.assertTrue(req["completed"])
        self.assertEqual(req["data"]["object"], "Opportunity")
        self.assertEqual(req["data"]["identifier"], "Renewal Q1")
        self.assertEqual(req["data"]["fields"]["stage"], "negotiation")


class ExtractDeleteRequestsTests(SimpleTestCase):
    @mock.patch.object(sra, "estimate_cost", return_value=(0, 0.0))
    @mock.patch.object(sra.client.chat.completions, "create")
    def test_normalizes_delete(self, mock_create, _est):
        mock_create.return_value = _fake_openai_response(
            {
                "delete_standard_record": [
                    {"data": {"object": "Account", "identifier": "Acme"}}
                ],
                "agent_message": "",
                "summary": "",
            }
        )

        result, _tokens, _cost = sra._extract_delete_requests("delete account Acme", [], None)

        self.assertIsNotNone(result)
        req = result["delete_standard_record"][0]
        self.assertTrue(req["completed"])
        self.assertEqual(req["data"]["object"], "Account")
        self.assertEqual(req["data"]["identifier"], "Acme")
