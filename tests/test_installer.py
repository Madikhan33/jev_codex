import base64
import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from jev_router.catalog import load_catalog
from jev_router.installer import agent_file, hook_definition, register, uninstall

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_catalog()


class InstallerTests(unittest.TestCase):
    def test_conditional_workflow_is_installed_and_protected(self):
        self.install()
        path = self.skills / "jev-router" / "team-workflow.md"
        self.assertEqual(
            path.read_bytes(), (ROOT / "jev_router/resources/team-workflow.md").read_bytes()
        )
        path.write_text("User customized workflow", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(path.read_text(), "User customized workflow")

    def test_modified_posix_command_does_not_duplicate_windows_handler(self):
        self.install()
        path = self.home / "hooks.json"
        hooks = json.loads(path.read_text())
        hooks["hooks"]["UserPromptSubmit"][-1]["hooks"][0]["command"] = "custom-posix-command"
        path.write_text(json.dumps(hooks))
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(json.loads(path.read_text()), hooks)

    def test_printed_doctor_targets_custom_installation(self):
        import contextlib
        import io

        from jev_router.installer import install

        output = io.StringIO()
        with (
            patch("jev_router.installer.prepare_runtime", return_value=Path(sys.executable)),
            contextlib.redirect_stdout(output),
        ):
            install(self.home, self.skills, without_key=True)
        command = output.getvalue().split("Doctor: ")[1].strip()
        self.assertIn("--config", command)
        self.assertIn(str(self.root / "settings.json"), command)
        if sys.platform == "win32":
            self.assertTrue(command.startswith("& '"))

    def test_modified_hook_refuses_duplicate_registration(self):
        self.install()
        path = self.home / "hooks.json"
        hooks = json.loads(path.read_text())
        hooks["hooks"]["UserPromptSubmit"][-1]["hooks"][0]["timeout"] = 99
        path.write_text(json.dumps(hooks))
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(json.loads(path.read_text()), hooks)

    def test_foreign_empty_group_is_preserved(self):
        path = self.home / "hooks.json"
        self.initial["hooks"]["UserPromptSubmit"].append({"matcher": "foreign", "hooks": []})
        path.write_text(json.dumps(self.initial))
        self.install()
        uninstall(self.home, self.root)
        self.assertEqual(json.loads(path.read_text()), self.initial)

    def test_failed_registration_restores_original_files(self):
        from jev_router.storage import atomic_write

        hooks = self.home / "hooks.json"
        failed = False

        def fail_once(path, content, **kwargs):
            nonlocal failed
            if path == hooks and not failed:
                failed = True
                raise OSError("simulated write failure")
            return atomic_write(path, content, **kwargs)

        with (
            patch("jev_router.installer.atomic_write", side_effect=fail_once),
            self.assertRaises(OSError),
        ):
            self.install()
        self.assertEqual(json.loads(hooks.read_text()), self.initial)
        self.assertFalse((self.skills / "jev-router" / "SKILL.md").exists())
        self.assertFalse((self.root / "manifest.json").exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Jev test space ")
        self.base = Path(self.temp.name)
        self.home = self.base / "codex"
        self.skills = self.base / "skills"
        self.root = self.home / "jev-router"
        self.home.mkdir()
        self.foreign = {"type": "command", "command": "echo existing"}
        self.initial = {
            "description": "existing config",
            "hooks": {
                "UserPromptSubmit": [{"hooks": [self.foreign]}],
                "Stop": [{"hooks": [self.foreign]}],
            },
        }
        (self.home / "hooks.json").write_text(json.dumps(self.initial), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def install(self):
        return register(self.home, self.skills, self.root, Path(sys.executable), CATALOG)

    def test_register_preserves_foreign_hooks(self):
        self.install()
        hooks = json.loads((self.home / "hooks.json").read_text())
        self.assertEqual(hooks["hooks"]["Stop"], self.initial["hooks"]["Stop"])
        self.assertEqual(hooks["hooks"]["UserPromptSubmit"][0]["hooks"], [self.foreign])
        self.assertEqual(len(list((self.home / "agents").glob("*.toml"))), 7)
        self.assertTrue((self.skills / "jev-router" / "SKILL.md").is_file())

    def test_reinstall_does_not_duplicate_hook(self):
        self.install()
        self.install()
        hooks = json.loads((self.home / "hooks.json").read_text())
        all_handlers = [h for g in hooks["hooks"]["UserPromptSubmit"] for h in g["hooks"]]
        self.assertEqual(sum(h.get("statusMessage") == "Jev Router" for h in all_handlers), 1)

    def test_uninstall_removes_only_owned_integration(self):
        self.install()
        uninstall(self.home, self.root)
        self.assertEqual(json.loads((self.home / "hooks.json").read_text()), self.initial)
        self.assertFalse((self.skills / "jev-router" / "SKILL.md").exists())
        self.assertEqual(list((self.home / "agents").glob("*.toml")), [])

    def test_uninstall_preserves_locally_edited_file(self):
        self.install()
        target = self.home / "agents" / "jev_luna_low.toml"
        target.write_text("# a local customization\n", encoding="utf-8")
        messages = uninstall(self.home, self.root)
        self.assertTrue(target.exists())
        self.assertTrue(any("Preserved" in m for m in messages))

    def test_unowned_file_is_not_overwritten(self):
        target = self.skills / "jev-router" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("my independent skill", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(target.read_text(), "my independent skill")
        self.assertEqual(json.loads((self.home / "hooks.json").read_text()), self.initial)

    def test_invalid_hooks_not_overwritten(self):
        path = self.home / "hooks.json"
        path.write_text("invalid json")
        with self.assertRaises(ValueError):
            self.install()
        self.assertEqual(path.read_text(), "invalid json")

    def test_subagent_files_are_valid_toml(self):
        for key, row in CATALOG["profiles"].items():
            data = tomllib.loads(agent_file(key, row).decode())
            self.assertEqual(data["name"], "jev_" + key)
            self.assertEqual(data["model_reasoning_effort"], row["effort"])
            self.assertNotIn("sandbox_mode", data)
            self.assertNotIn("approval_policy", data)

    def test_windows_paths_are_quoted_without_shell_input(self):
        python = Path("C:/Users/Someone's folder/python.exe")
        entry = Path("C:/Users/Name & Name/entry.py")
        h = hook_definition(python, entry, Path("C:/Users/Name/settings.json"), 5)
        encoded = h["commandWindows"].split()[-1]
        decoded = base64.b64decode(encoded).decode("utf-16-le")
        self.assertIn("Someone''s folder", decoded)
        self.assertIn("'" + str(entry) + "'", decoded)
        self.assertNotIn("prompt", decoded)
        self.assertEqual(h["timeout"], 21)

    def test_dry_run_does_not_write_anything(self):
        home = self.base / "untouched"
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "install.py"),
                "--codex-home",
                str(home),
                "--skills-dir",
                str(self.base / "other"),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(home.exists())
        self.assertFalse(json.loads(proc.stdout)["will_bypass_hook_trust"])

    def test_no_parent_config_changes(self):
        file = self.home / "config.toml"
        original = 'model = "my-parent-model"\n[features]\nhooks = false\n'
        file.write_text(original)
        self.install()
        self.assertEqual(file.read_text(), original)


if __name__ == "__main__":
    unittest.main()
