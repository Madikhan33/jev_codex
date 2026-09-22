"""Structural checks for the authored economy routing suite."""

import json
import unittest
from pathlib import Path

from eval import validate_cases
from jev_router.catalog import load_catalog


class EconomyPromptTests(unittest.TestCase):
    def test_authored_economy_cases_match_catalog(self):
        fixture = json.loads(
            Path(__file__).with_name("economy_cases.json").read_text(encoding="utf-8")
        )
        self.assertEqual(fixture["kind"], "authored_ground_truth_not_model_results")
        validate_cases(fixture["cases"], load_catalog())

    def test_boundary_profiles_are_represented(self):
        fixture = json.loads(
            Path(__file__).with_name("economy_cases.json").read_text(encoding="utf-8")
        )
        expected = {
            profile
            for case in fixture["cases"]
            for profiles in case.get("acceptable_profiles", {}).values()
            for profile in profiles
        }
        self.assertTrue(
            {
                "luna_xhigh",
                "luna_max",
                "sol_medium",
                "sol_high",
                "sol_xhigh",
                "astra_low",
                "astra_medium",
                None,
            }
            <= expected
        )


if __name__ == "__main__":
    unittest.main()
