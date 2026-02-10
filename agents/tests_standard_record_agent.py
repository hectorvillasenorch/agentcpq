from django.test import SimpleTestCase

from cpq.models import DEFAULT_OPPORTUNITY_STAGES

from agents.standard_record_agent import _normalize_opportunity_stage_value


class OpportunityStageNormalizationTests(SimpleTestCase):
    def test_maps_qualification_alias_to_valid_stage_key(self):
        normalized = _normalize_opportunity_stage_value(
            "qualification",
            DEFAULT_OPPORTUNITY_STAGES,
            "qualifiedtobuy",
        )
        self.assertEqual(normalized, "qualifiedtobuy")

    def test_maps_stage_label_to_stage_key(self):
        normalized = _normalize_opportunity_stage_value(
            "Qualified to Buy",
            DEFAULT_OPPORTUNITY_STAGES,
            "qualifiedtobuy",
        )
        self.assertEqual(normalized, "qualifiedtobuy")

    def test_leaves_unknown_stage_untouched(self):
        normalized = _normalize_opportunity_stage_value(
            "some_new_stage",
            DEFAULT_OPPORTUNITY_STAGES,
            "qualifiedtobuy",
        )
        self.assertEqual(normalized, "some_new_stage")
