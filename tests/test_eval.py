import json
import unittest
from pathlib import Path

from test_router import FakeAPI

from eval import evaluate_cases, validate_cases
from jev_router.catalog import load_catalog


class EvaluationTests(unittest.TestCase):
    def test_rejected_profile_is_not_accepted_needs_context(self):
        from test_router import choice

        api = FakeAPI({"ui_style": 0.99})

        def request(state, questions):
            response = api(state, questions)
            if "profile.ui_style" in questions:
                response["answers"]["profile.ui_style"] = choice(
                    questions["profile.ui_style"]["criteria"], "sol_medium", 0.4
                )
            return response

        report = evaluate_cases(
            [
                {
                    "id": "rejected",
                    "prompt": "Style it",
                    "categories": ["ui_style"],
                    "acceptable_profiles": {"ui_style": [None]},
                }
            ],
            request,
            load_catalog(),
        )
        self.assertEqual(report["profile_accuracy"], 0)
        self.assertEqual(report["expectations_failed_cases"], 1)

    def test_acceptable_intents_allow_documented_annotation_ambiguity(self):
        report = evaluate_cases(
            [
                {
                    "id": "ambiguous",
                    "prompt": "Fix it",
                    "categories": [],
                    "acceptable_intents": ["implement", "unclear"],
                }
            ],
            FakeAPI(intent="unclear"),
            load_catalog(),
        )
        self.assertEqual(report["intent_accuracy"], 1)

    def test_strategy_mismatch_fails_otherwise_matching_case(self):
        report = evaluate_cases(
            [
                {
                    "id": "strategy",
                    "prompt": "Build panel",
                    "categories": ["ui_layout"],
                    "acceptable_strategies": ["consider_delegation"],
                }
            ],
            FakeAPI({"ui_layout": 0.99}),
            load_catalog(),
        )
        self.assertEqual(report["exact_match"], 1)
        self.assertEqual(report["strategy_accuracy"], 0)
        self.assertEqual(report["expectations_failed_cases"], 1)

    def test_authored_context_suite_is_valid(self):
        path = Path(__file__).with_name("context_cases.json")
        fixture = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertEqual(fixture["kind"], "authored_ground_truth_not_model_results")
        validate_cases(fixture["cases"], load_catalog())

    def test_missing_category_is_not_successful_abstention(self):
        case = {
            "id": "missing",
            "prompt": "Fix it",
            "categories": ["ui_style"],
            "acceptable_profiles": {"ui_style": [None]},
        }
        report = evaluate_cases([case], FakeAPI(), load_catalog())
        self.assertEqual(report["profile_accuracy"], 0)
        self.assertEqual(report["expectations_failed_cases"], 1)

    def test_explicit_null_profile_is_valid_but_not_a_model_selection(self):
        case = {
            "id": "abstain",
            "prompt": "Fix the interface style",
            "categories": ["ui_style"],
            "acceptable_profiles": {"ui_style": [None]},
        }
        report = evaluate_cases(
            [case], FakeAPI({"ui_style": 0.99}, {"ui_style": "needs_context"}), load_catalog()
        )
        self.assertEqual(report["profile_accuracy"], 1)
        self.assertEqual(report["profile_selection_rate"], 0)

    def test_transport_failure_is_counted_and_next_case_runs(self):
        cases = [
            {"id": "fail", "prompt": "failure", "categories": []},
            {"id": "pass", "prompt": "hello", "categories": [], "expected_intent": "non_software"},
        ]
        api = FakeAPI(intent="non_software")

        def request(state, questions):
            if state["request"] == "failure":
                raise RuntimeError("private credential and submitted prompt")
            return api(state, questions)

        report = evaluate_cases(cases, request, load_catalog())
        self.assertEqual(report["error_cases"], 1)
        self.assertEqual(report["exact_match"], 0.5)
        self.assertEqual(report["expectations_passed_cases"], 1)
        self.assertEqual(report["classification_calls"], 2)
        self.assertNotIn("private credential", json.dumps(report))

    def test_second_stage_failure_is_counted(self):
        api = FakeAPI({"ui_style": 0.99})

        def request(state, questions):
            if "profile.ui_style" in questions:
                raise TimeoutError("do not print provider exception")
            return api(state, questions)

        report = evaluate_cases(
            [{"id": "timeout", "prompt": "change background", "categories": ["ui_style"]}],
            request,
            load_catalog(),
        )
        self.assertEqual(report["classification_calls"], 2)
        self.assertEqual(report["micro_recall"], 0)
        self.assertEqual(report["details"][0]["error_type"], "TimeoutError")

    def test_explicit_context_reaches_both_stages(self):
        case = {
            "id": "context",
            "prompt": "Исправь это",
            "context": "Only change background to #fff",
            "categories": ["ui_style"],
            "acceptable_profiles": {"ui_style": ["luna_xhigh"]},
            "acceptable_strategies": ["assign_specialist"],
            "expected_review_required": False,
        }
        api = FakeAPI({"ui_style": 0.99}, {"ui_style": "luna_xhigh"})
        report = evaluate_cases([case], api, load_catalog())
        self.assertEqual([call[0]["context"] for call in api.calls], [case["context"]] * 2)
        self.assertEqual(report["strategy_accuracy"], 1)
        self.assertEqual(report["review_accuracy"], 1)
        self.assertEqual(report["details"][0]["route"]["groups"][0]["model"], "gpt-5.6-luna")
        self.assertFalse(report["codex_spawn_measured"])
        self.assertFalse(report["automatic_context_recovery_measured"])

    def test_rejected_intent_cannot_pass_as_accepted_implementation(self):
        from test_router import choice

        api = FakeAPI({"ui_style": 0.99})

        def request(state, questions):
            response = api(state, questions)
            if "intent" in questions:
                response["answers"]["intent"] = choice(
                    questions["intent"]["criteria"], "implement", 0.4
                )
            return response

        report = evaluate_cases(
            [
                {
                    "id": "intent",
                    "prompt": "Do it",
                    "categories": ["ui_style"],
                    "expected_intent": "implement",
                }
            ],
            request,
            load_catalog(),
        )
        self.assertEqual(report["intent_accuracy"], 0)

    def test_invalid_fixture_is_rejected_before_any_provider_call(self):
        api = FakeAPI()
        cases = [{"id": "bad", "prompt": "test", "categories": ["made_up_category"]}]
        with self.assertRaises(ValueError):
            evaluate_cases(cases, api, load_catalog())
        self.assertEqual(api.calls, [])

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
        self.assertEqual(report["details"][0]["checked_axes"], ["categories"])
        self.assertIn("annotated expectations only", report["pass_basis"])
        self.assertNotIn("passed_cases", report)
