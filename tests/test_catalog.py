import copy
import tempfile
import unittest
from pathlib import Path

from jev_router.catalog import install_catalog, load_catalog, validate_catalog
from jev_router.questions import detection_questions, profile_questions


class CatalogTests(unittest.TestCase):
    def test_fresh_install_contains_all_runtime_prompts(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "catalog"
            install_catalog(directory)
            self.assertEqual(load_catalog(directory), load_catalog())

    def test_legacy_catalog_keeps_local_edits_and_gets_control_prompts(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "catalog"
            install_catalog(directory)
            (directory / "routing.toml").unlink()
            categories = directory / "domains.toml"
            original = categories.read_bytes()
            categories.write_bytes(original + b"\n# local customization\n")
            before = load_catalog(directory)
            install_catalog(directory)
            self.assertEqual(load_catalog(directory), before)
            self.assertEqual(categories.read_bytes(), original + b"\n# local customization\n")

    def test_control_prompt_edits_reach_all_question_types(self):
        catalog = copy.deepcopy(load_catalog())
        catalog["routing"]["scope"] = "custom-test-scope"
        catalog["routing"]["intent"]["question"] = "custom-intent-question"
        questions = detection_questions(catalog)
        questions.update(profile_questions(catalog, ["ui_layout", "backend_api"]))
        for question in questions.values():
            self.assertEqual(question["instructions"]["scope"], "custom-test-scope")
        self.assertEqual(questions["intent"]["instructions"]["question"], "custom-intent-question")

    def test_invalid_policy_is_rejected_before_network(self):
        for field in ("profile_margin", "yes_threshold", "request_timeout_seconds"):
            for invalid in (True, float("nan"), float("inf"), "0.8"):
                catalog = copy.deepcopy(load_catalog())
                catalog["policy"][field] = invalid
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    validate_catalog(catalog)

    def test_invalid_examples_and_control_labels_rejected(self):
        catalog = copy.deepcopy(load_catalog())
        catalog["categories"]["ui_style"]["positive_examples"] = "not a list"
        with self.assertRaises(ValueError):
            validate_catalog(catalog)
        catalog = copy.deepcopy(load_catalog())
        catalog["routing"]["intent"]["criteria"]["invented"] = "Unsupported intent"
        with self.assertRaises(ValueError):
            validate_catalog(catalog)
