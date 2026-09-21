import unittest

from scripts.compare_worker_runs import compare_runs


def trial(**changes):
    return (
        dict(
            task_id="mechanical_edit",
            profile="luna_low",
            status="completed",
            checks_passed=True,
            elapsed_ms=100,
            tool_evidence="trial-1/checks.txt: all three acceptance checks passed",
            repetition=1,
        )
        | changes
    )


class WorkerComparisonTests(unittest.TestCase):
    def test_unknown_cost_and_tokens_stay_null(self):
        report = compare_runs([trial(), trial(repetition=2, tokens=20, cost=0.1)])
        group = report["groups"][0]
        self.assertIsNone(group["median_cost"])
        self.assertIsNone(group["median_tokens"])
        self.assertFalse(report["actual_model_verified"])
        self.assertNotIn("best_profile", report)

    def test_failed_checks_and_failed_status_count_as_failures(self):
        group = compare_runs(
            [
                trial(),
                trial(repetition=2, checks_passed=False),
                trial(repetition=3, status="failed"),
            ]
        )["groups"][0]
        self.assertEqual(group["success_rate"], 1 / 3)
        self.assertEqual(group["attempts"], 3)

    def test_measured_medians(self):
        rows = [
            trial(tokens=10, cost=0.1),
            trial(repetition=2, tokens=30, cost=0.3, elapsed_ms=300),
        ]
        group = compare_runs(rows)["groups"][0]
        self.assertEqual(group["median_tokens"], 20)
        self.assertAlmostEqual(group["median_cost"], 0.2)
        self.assertEqual(group["median_elapsed_ms"], 200)

    def test_duplicate_trial_rejected(self):
        with self.assertRaises(ValueError):
            compare_runs([trial(), trial()])

    def test_invalid_measurements_and_identifiers(self):
        for changes in [
            {"elapsed_ms": 0},
            {"elapsed_ms": float("nan")},
            {"elapsed_ms": True},
            {"tokens": -1},
            {"tokens": 1.5},
            {"cost": float("inf")},
            {"cost": -1},
            {"task_id": "unknown"},
            {"profile": "unknown"},
            {"repetition": 0},
            {"checks_passed": "yes"},
            {"tool_evidence": " "},
            {"simulated": True},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                compare_runs([trial(**changes)])
        with self.assertRaises(ValueError):
            compare_runs([])
