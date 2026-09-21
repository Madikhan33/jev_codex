import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jev_router.settings import get_api_key, read_settings


class SettingsTests(unittest.TestCase):
    def test_bom_settings_and_persistent_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "settings.json").write_text('{"enabled": true}', encoding="utf-8-sig")
            (root / "secrets.json").write_text('{"api_key": "test-only"}', encoding="utf-8-sig")
            with patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
                self.assertEqual(get_api_key(read_settings(root / "settings.json")), "test-only")

    def test_environment_key_wins_without_reading_file(self):
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "env-test"}):
            self.assertEqual(get_api_key({"credential_file": "does-not-exist"}), "env-test")

    def test_string_false_is_not_treated_as_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "settings.json"
            for invalid in ("false", 0, None):
                target.write_text(json.dumps({"enabled": invalid}), encoding="utf-8")
                with self.subTest(value=invalid), self.assertRaises(ValueError):
                    read_settings(target)
