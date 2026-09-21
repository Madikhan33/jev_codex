import unittest

from test_router import FakeAPI

from eval import evaluate_cases
from jev_router.catalog import load_catalog


class EvaluationTests(unittest.TestCase):
    def test_missing_category_counts_as_profile_error(self):
        cases = [
            {
                "id": "test",
                "prompt": "UI and API",
                "categories": ["ui_layout", "backend_api"],
                "expected_intent": "implement",
                "acceptable_profiles": {"ui_layout": ["sol_medium"], "backend_api": ["sol_medium"]},
            }
        ]
        report = evaluate_cases(cases, FakeAPI({"ui_layout": 0.98}), load_catalog())
        self.assertEqual(report["micro_recall"], 0.5)
        self.assertEqual(report["profile_accuracy"], 0.5)
        self.assertEqual(report["intent_accuracy"], 1)
        self.assertEqual(report["details"][0]["profile_errors"], ["backend_api"])

    def test_unannotated_metrics_are_unknown(self):
        report = evaluate_cases(
            [{"id": "test", "prompt": "hello", "categories": []}],
            FakeAPI(intent="non_software"),
            load_catalog(),
        )
        self.assertIsNone(report["profile_accuracy"])
        self.assertIsNone(report["intent_accuracy"])
        self.assertEqual(report["classification_calls"], 1)
