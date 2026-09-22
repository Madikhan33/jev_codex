import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jev_router.catalog import load_catalog
from jev_router.cli import main
from jev_router.installer import register


class CliTests(unittest.TestCase):
    def test_prompt_preview_needs_no_key_and_prints_actual_question(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["prompts", "--category", "backend_api", "--config", str(self.config)])
        self.assertEqual(status, 0)
        questions = json.loads(output.getvalue())
        self.assertEqual(set(questions), {"work.backend_api"})
        self.assertEqual(questions["work.backend_api"]["type"], "noul")

    def test_profile_preview_contains_only_requested_categories(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(
                [
                    "prompts",
                    "--stage",
                    "profiles",
                    "--category",
                    "ui_layout",
                    "--config",
                    str(self.config),
                ]
            )
        self.assertEqual(status, 0)
        self.assertEqual(set(json.loads(output.getvalue())), {"profile.ui_layout"})

    def test_doctor_reports_malformed_hook_without_losing_other_checks(self):
        register(
            self.home,
            Path(self.temp.name) / "skills",
            self.root,
            Path(sys.executable),
            load_catalog(),
        )
        (self.home / "hooks.json").write_text("bad json")
        status, output = self.run_cli("doctor")
        checks = json.loads(output)
        self.assertEqual(status, 1)
        self.assertFalse(checks["hook_registered"])
        self.assertTrue(checks["catalog_valid"])
        self.assertTrue(checks["configuration_warnings"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "codex"
        self.root = self.home / "jev-router"
        self.config = self.root / "settings.json"

    def run_cli(self, command):
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["jev-codex", command, "--config", str(self.config)]),
            contextlib.redirect_stdout(output),
        ):
            status = main()
        return status, output.getvalue()

    def test_configure_saves_hidden_key_and_rotation(self):
        register(
            self.home,
            Path(self.temp.name) / "skills",
            self.root,
            Path(sys.executable),
            load_catalog(),
        )
        for key in ("first-test-key", "replacement-test-key"):
            with (
                patch("sys.stdin.isatty", return_value=True),
                patch("getpass.getpass", return_value=key),
            ):
                status, output = self.run_cli("configure")
            self.assertEqual(status, 0)
            self.assertNotIn(key, output)
            self.assertEqual(json.loads((self.root / "secrets.json").read_text())["api_key"], key)

    def test_doctor_requires_registered_intact_hook(self):
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": "test", "JEV_ROUTER_DISABLE": "0"}),
            patch("importlib.util.find_spec", return_value=object()),
        ):
            status, output = self.run_cli("doctor")
            self.assertEqual(status, 1)
            self.assertFalse(json.loads(output)["registered"])
            register(
                self.home,
                Path(self.temp.name) / "skills",
                self.root,
                Path(sys.executable),
                load_catalog(),
            )
            status, output = self.run_cli("doctor")
            self.assertEqual(status, 0, output)
            self.assertTrue(json.loads(output)["global_instructions_registered"])
            (self.home / "AGENTS.md").write_text("user replacement", encoding="utf-8")
            status, output = self.run_cli("doctor")
            self.assertEqual(status, 1)
            self.assertFalse(json.loads(output)["global_instructions_registered"])
            (self.home / "hooks.json").write_text('{"hooks": {}}')
            status, output = self.run_cli("doctor")
            self.assertEqual(status, 1)
            self.assertFalse(json.loads(output)["hook_registered"])
