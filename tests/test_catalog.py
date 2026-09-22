import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_unchanged_legacy_profiles_are_migrated_without_replacing_other_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "catalog"
            install_catalog(directory)
            domains = directory / "domains.toml"
            domains.write_bytes(domains.read_bytes() + b"\n# user edit\n")
            profiles = directory / "profiles.toml"
            legacy = b"# formerly shipped profiles\n"
            profiles.write_bytes(legacy)
            with patch(
                "jev_router.catalog.LEGACY_PROFILES_SHA256", hashlib.sha256(legacy).hexdigest()
            ):
                self.assertEqual(load_catalog(directory)["profiles"], load_catalog()["profiles"])
                install_catalog(directory)
            self.assertEqual(
                profiles.read_bytes(),
                (
                    Path(__file__).resolve().parents[1] / "jev_router/prompts/profiles.toml"
                ).read_bytes(),
            )
            self.assertTrue(domains.read_bytes().endswith(b"# user edit\n"))

    def test_only_supported_efforts_per_family_are_accepted(self):
        expected = {
            "luna": {"xhigh", "max"},
            "sol": {"medium", "high", "xhigh"},
        }
        catalog = load_catalog()
        for profile in catalog["profiles"].values():
            self.assertIn(profile["effort"], expected[profile["family"]])
        for name, invalid_effort in (
            ("luna_xhigh", "low"),
            ("sol_medium", "max"),
        ):
            invalid = copy.deepcopy(catalog)
            invalid["profiles"][name]["effort"] = invalid_effort
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_catalog(invalid)

    def test_profiles_require_the_model_for_their_family_and_allow_custom_criteria(self):
        catalog = load_catalog()
        self.assertEqual(
            set(catalog["profiles"]),
            {"luna_xhigh", "luna_max", "sol_medium", "sol_high", "sol_xhigh"},
        )
        expected_models = {"luna": "gpt-6-luna", "sol": "gpt-6-sol"}
        for name, profile in catalog["profiles"].items():
            self.assertEqual(profile["model"], expected_models[profile["family"]])
            profile["criterion"] = f"Custom criterion for {name}"
        validate_catalog(catalog)

        invalid_models = {
            "luna": ("gpt-5.6", "gpt-6-sol", "provider/custom-model"),
            "sol": ("gpt-5.6", "gpt-6-luna", "provider/custom-model"),
        }
        for name, profile in catalog["profiles"].items():
            for model in invalid_models[profile["family"]]:
                invalid = copy.deepcopy(catalog)
                invalid["profiles"][name]["model"] = model
                with (
                    self.subTest(name=name, model=model),
                    self.assertRaisesRegex(ValueError, "Configured model must be"),
                ):
                    validate_catalog(invalid)

    def test_installed_catalog_with_wrong_execution_model_is_rejected_on_load(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "catalog"
            install_catalog(directory)
            profiles = directory / "profiles.toml"
            original = profiles.read_bytes()
            invalid = original.replace(b'model = "gpt-6-luna"', b'model = "gpt-5.6"', 1)
            self.assertNotEqual(invalid, original)
            profiles.write_bytes(invalid)
            with self.assertRaisesRegex(ValueError, "Configured model must be"):
                load_catalog(directory)

    def test_legacy_profile_migration_does_not_modify_hardlink_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "catalog"
            install_catalog(directory)
            profiles = directory / "profiles.toml"
            outside = Path(temporary) / "outside.toml"
            legacy = b"# unchanged legacy profile data\n"
            profiles.unlink()
            outside.write_bytes(legacy)
            try:
                os.link(outside, profiles)
            except OSError as error:
                self.skipTest(f"Hardlinks unavailable: {error}")
            with patch(
                "jev_router.catalog.LEGACY_PROFILES_SHA256", hashlib.sha256(legacy).hexdigest()
            ):
                install_catalog(directory)
            self.assertEqual(outside.read_bytes(), legacy)
            self.assertNotEqual(profiles.read_bytes(), legacy)

    def test_legacy_profile_symlink_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "catalog"
            install_catalog(directory)
            profiles = directory / "profiles.toml"
            outside = Path(temporary) / "outside.toml"
            legacy = b"# unchanged legacy profile data\n"
            profiles.unlink()
            outside.write_bytes(legacy)
            try:
                profiles.symlink_to(outside)
            except OSError as error:
                self.skipTest(f"Symlinks unavailable: {error}")
            with patch(
                "jev_router.catalog.LEGACY_PROFILES_SHA256", hashlib.sha256(legacy).hexdigest()
            ):
                with self.assertRaises(ValueError):
                    install_catalog(directory)
            self.assertEqual(outside.read_bytes(), legacy)

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
