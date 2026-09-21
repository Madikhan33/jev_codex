"""Isolated installation smoke; --online downloads SDK, never calls TypeSafe."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))

from jev_router.catalog import load_catalog
from jev_router.installer import prepare_runtime, register, uninstall


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="Jev smoke space ") as temporary:
        home = Path(temporary) / "codex"
        skills = Path(temporary) / "skills"
        root = home / "jev-router"
        env = dict(os.environ, CODEX_HOME=str(home), JEV_ROUTER_DISABLE="1", TYPESAFE_API_KEY="")
        if args.online:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SOURCE / "install.py"),
                    "--codex-home",
                    str(home),
                    "--skills-dir",
                    str(skills),
                    "--without-key",
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            if proc.returncode:
                raise RuntimeError("Isolated installer failed: " + proc.stderr)
        else:
            python = prepare_runtime(root, install_dependencies=False)
            register(home, skills, root, python, load_catalog())
        manifest = json.loads((root / "manifest.json").read_text())
        handler = manifest["handler"]
        if os.name == "nt":
            argv = handler["commandWindows"].split()
        else:
            argv = shlex.split(handler["command"])
        event = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "Smoke test"})
        disabled = subprocess.run(
            argv, input=event, text=True, capture_output=True, env=env, cwd=temporary, timeout=30
        )
        assert disabled.returncode == 0 and disabled.stdout == "", disabled.stderr
        env["JEV_ROUTER_DISABLE"] = "0"
        fallback = subprocess.run(
            argv, input=event, text=True, capture_output=True, env=env, cwd=temporary, timeout=30
        )
        assert fallback.returncode == 0, fallback.stderr
        assert "systemMessage" in json.loads(fallback.stdout), fallback.stdout
        if args.online:
            reinstall = subprocess.run(
                [
                    sys.executable,
                    str(SOURCE / "install.py"),
                    "--codex-home",
                    str(home),
                    "--skills-dir",
                    str(skills),
                    "--without-key",
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            assert reinstall.returncode == 0, reinstall.stderr
            hooks = json.loads((home / "hooks.json").read_text())["hooks"]["UserPromptSubmit"]
            assert sum(len(group["hooks"]) for group in hooks) == 1
        uninstall(home, root)
        assert not (home / "hooks.json").exists()
        assert not (skills / "jev-router" / "SKILL.md").exists()
        print(
            "PASS: isolated install, actual hook command, disabled mode, missing-key fallback, uninstall"
            + (", online SDK install and reinstall" if args.online else "")
        )


if __name__ == "__main__":
    main()
