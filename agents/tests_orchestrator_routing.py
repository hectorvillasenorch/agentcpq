"""Deterministic routing / command-understanding unit tests.

These cover the "understanding" layer that decides what a chat message means
before (or instead of) hitting the LLM. They are pure functions, so they run
under SimpleTestCase without a database.
"""
from django.test import SimpleTestCase

from cpq.models import DEFAULT_OPPORTUNITY_STAGES

from agents.orchestrator import (
    _infer_standard_record_write_decision,
    _should_shortcut_to_metrics,
    _should_shortcut_to_single_record,
    clean_llm_label,
    should_reset_session,
)
from agents.standard_record_agent import _normalize_opportunity_stage_value


class ShouldResetSessionTests(SimpleTestCase):
    def test_standalone_reset_words_trigger(self):
        for message in ("reset", "Reset", "reset!", "restart", "start over", "new chat"):
            self.assertTrue(should_reset_session(message), message)

    def test_explicit_session_phrases_trigger(self):
        for message in (
            "reset session",
            "reset my session",
            "clear the chat",
            "clear the conversation",
            "start a new conversation",
            "forget everything",
        ):
            self.assertTrue(should_reset_session(message), message)

    def test_non_reset_messages_do_not_trigger(self):
        for message in (
            "",
            "show me my leads",
            "create a lead John Doe",
            "reset password",
            "what is a reset token",
            "list accounts",
        ):
            self.assertFalse(should_reset_session(message), message)


class CleanLlmlabelTests(SimpleTestCase):
    def test_strips_non_letters(self):
        self.assertEqual(clean_llm_label("ShowSingleRecord"), "ShowSingleRecord")
        self.assertEqual(clean_llm_label("  Show Metrics  "), "ShowMetrics")
        self.assertEqual(clean_llm_label("Create_Standard_Record"), "CreateStandardRecord")
        self.assertEqual(clean_llm_label("DeleteQuote!"), "DeleteQuote")

    def test_empty(self):
        self.assertEqual(clean_llm_label(""), "")
        self.assertEqual(clean_llm_label(None), "")


class ShortcutToMetricsTests(SimpleTestCase):
    def test_plural_objects_route_to_metrics(self):
        for message in (
            "show me my quotes",
            "list all products",
            "show my last 5 quotes",
            "display all accounts",
            "list all opportunities",
        ):
            self.assertTrue(_should_shortcut_to_metrics(message), message)

    def test_revenue_metrics_route(self):
        self.assertTrue(_should_shortcut_to_metrics("revenue this year"))
        self.assertTrue(_should_shortcut_to_metrics("what is my pipeline forecast"))

    def test_singular_with_list_keyword_routes(self):
        self.assertTrue(_should_shortcut_to_metrics("show all account records"))

    def test_singular_no_list_keyword_does_not_route(self):
        self.assertFalse(_should_shortcut_to_metrics("show account Acme"))
        self.assertFalse(_should_shortcut_to_metrics("show the opportunity"))

    def test_non_view_request_does_not_route(self):
        self.assertFalse(_should_shortcut_to_metrics("create a lead John Doe"))


class ShortcutToSingleRecordTests(SimpleTestCase):
    def test_singular_lookup_routes(self):
        for message in (
            "show account Acme",
            "open product SKU-1001",
            "show lead with phone 9498724333",
            "display the opportunity Renewal Q1",
        ):
            self.assertTrue(_should_shortcut_to_single_record(message), message)

    def test_plural_does_not_route(self):
        self.assertFalse(_should_shortcut_to_single_record("show me my quotes"))
        self.assertFalse(_should_shortcut_to_single_record("list all accounts"))

    def test_list_keyword_does_not_route(self):
        self.assertFalse(_should_shortcut_to_single_record("show all accounts"))


class InferStandardRecordWriteDecisionTests(SimpleTestCase):
    def test_create_verbs(self):
        self.assertEqual(
            _infer_standard_record_write_decision("create a lead John Doe with email john@acme.com"),
            "CreateStandardRecord",
        )
        self.assertEqual(
            _infer_standard_record_write_decision("add an account named Acme in New York"),
            "CreateStandardRecord",
        )

    def test_update_verbs(self):
        self.assertEqual(
            _infer_standard_record_write_decision("update account Acme phone to 555-0101"),
            "UpdateStandardRecord",
        )
        self.assertEqual(
            _infer_standard_record_write_decision("change opportunity Renewal Q1 stage to negotiation"),
            "UpdateStandardRecord",
        )

    def test_delete_verbs(self):
        self.assertEqual(
            _infer_standard_record_write_decision("delete lead john@acme.com"),
            "DeleteStandardRecord",
        )
        self.assertEqual(
            _infer_standard_record_write_decision("remove account Acme"),
            "DeleteStandardRecord",
        )

    def test_quote_and_bundle_are_excluded(self):
        self.assertIsNone(_infer_standard_record_write_decision("create a quote for Acme"))
        self.assertIsNone(_infer_standard_record_write_decision("add a product option to bundle"))

    def test_view_or_question_does_not_infer_write(self):
        self.assertIsNone(_infer_standard_record_write_decision("show account Acme"))
        self.assertIsNone(_infer_standard_record_write_decision("what is a lead"))


class NormalizeOpportunityStageValueTests(SimpleTestCase):
    def test_label_normalizes_to_key(self):
        self.assertEqual(
            _normalize_opportunity_stage_value("Closed Won", DEFAULT_OPPORTUNITY_STAGES, "qualifiedtobuy"),
            "closedwon",
        )

    def test_exact_key_passes_through(self):
        self.assertEqual(
            _normalize_opportunity_stage_value("closedwon", DEFAULT_OPPORTUNITY_STAGES, "qualifiedtobuy"),
            "closedwon",
        )

    def test_empty_falls_back_to_default(self):
        self.assertEqual(
            _normalize_opportunity_stage_value("", DEFAULT_OPPORTUNITY_STAGES, "qualifiedtobuy"),
            "qualifiedtobuy",
        )
        self.assertEqual(
            _normalize_opportunity_stage_value(None, DEFAULT_OPPORTUNITY_STAGES, "qualifiedtobuy"),
            "qualifiedtobuy",
        )

    def test_unknown_stage_untouched(self):
        self.assertEqual(
            _normalize_opportunity_stage_value("custom_stage", DEFAULT_OPPORTUNITY_STAGES, "qualifiedtobuy"),
            "custom_stage",
        )
