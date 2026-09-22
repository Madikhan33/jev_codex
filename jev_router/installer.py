"""Idempotent per-user installation. Never edits hook trust or parent model settings."""

from __future__ import annotations

import argparse
import base64
import copy
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import tomllib
import uuid
import venv
from pathlib import Path
from typing import Any

from .catalog import install_catalog, load_catalog
from .contracts import Catalog, Profile
from .settings import codex_home, prompt_api_key
from .storage import atomic_write as atomic_write
from .storage import digest as digest
from .storage import json_bytes as json_bytes

OWNER = "jev-codex-router-v3"
GLOBAL_INSTRUCTIONS = (
    b"<!-- Jev Router managed instructions: start -->\n"
    b"For every software change request, use the installed $jev-router skill, even when "
    b"JEV_ROUTE_V3 hook metadata is absent. Use the original request and local context "
    b"to choose a bounded assignment. Delegate implementation to one available subagent "
    b"with the smallest suitable Jev profile, including small edits; the lead "
    b"owns scope, integration, checks and the final answer. Add parallel specialists "
    b"only for independent work. If delegation is unavailable or a higher-priority "
    b"instruction forbids it, continue safely and state the limitation. Never claim a "
    b"worker model ran without an accepted spawn. An explicit user request to work "
    b"directly takes precedence.\n"
    b"<!-- Jev Router managed instructions: end -->\n\n"
)
GLOBAL_MARKER = b"<!-- Jev Router managed instructions: start -->"
UTF8_BOM = b"\xef\xbb\xbf"
AGENT_INSTRUCTIONS = (
    "Work as a specialist reporting to the parent team lead. Complete only the assigned "
    "task and preserve its acceptance criteria and original constraints. You are not alone "
    "in the codebase: edit only your assigned files, preserve others' changes, and report "
    "ownership conflicts before editing shared files. Ask the parent for missing interfaces "
    "or prerequisites; continue independent assigned work while waiting. "
    "When the lead supplies real peer IDs and a peer messaging tool is available, send "
    "focused questions or findings directly to the responsible peer. Include task ID, "
    "message kind, the concrete question or result and short evidence references. Copy "
    "contract changes and blockers to the parent; only the parent may change ownership. "
    "If direct messaging is unavailable, relay through the parent. Avoid broadcasts, "
    "duplicate messages and acknowledgement loops. Ask the parent to resume idle peers. "
    "Use the supplied context and targeted file reads. Do not perform a full-repository "
    "scan, spawn subagents or call Jev again. Preserve sandbox and approval requirements. "
    "For missing local facts inspect relevant files; for missing user choices ask the "
    "parent. Verify needed current external facts with available research tools when "
    "permitted, using public technical queries and primary sources. Stop when the gap "
    "is resolved; share the concise finding so teammates do not repeat the search. "
    "Return task status (completed, blocked, or needs_review), changed files, actual "
    "validation results, interface changes and remaining blockers to the parent. "
    "Completion requires evidence for the assigned acceptance criteria; do not claim "
    "unrun checks passed. No fabricated paths, test results or model changes."
)
ENTRY = """from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from jev_router.cli import main
if __name__ == "__main__":
    raise SystemExit(main())
"""


def read_manifest(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    if not path.exists():
        return {}
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict) or result.get("owner") != OWNER:
        raise ValueError("Installation manifest is not owned by this package")
    for name in ("files", "handler"):
        if not isinstance(result.get(name), dict):
            raise ValueError(f"Invalid manifest {name}")
    if not all(isinstance(p, str) and isinstance(h, str) for p, h in result["files"].items()):
        raise ValueError("Invalid manifest file hashes")
    for name in ("codex_home", "skills_dir"):
        if not isinstance(result.get(name), str):
            raise ValueError(f"Invalid manifest {name}")
    return result


def remove_handler(document: dict[str, Any], handler: dict[str, Any] | None) -> dict[str, Any]:
    result = copy.deepcopy(document)
    if not handler:
        return result
    events = result.get("hooks", {}).get("UserPromptSubmit", [])
    cleaned = []
    for group in events:
        if handler not in group.get("hooks", []):
            cleaned.append(group)
            continue
        replacement = copy.deepcopy(group)
        replacement["hooks"] = [h for h in group.get("hooks", []) if h != handler]
        if replacement["hooks"]:
            cleaned.append(replacement)
    if "hooks" in result and "UserPromptSubmit" in result["hooks"]:
        if cleaned:
            result["hooks"]["UserPromptSubmit"] = cleaned
        else:
            del result["hooks"]["UserPromptSubmit"]
    return result


def load_hooks(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {"hooks": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("hooks", {}), dict):
        raise ValueError("Existing hooks.json has an invalid shape")
    groups = doc.get("hooks", {}).get("UserPromptSubmit", [])
    if not isinstance(groups, list) or any(
        not isinstance(g, dict) or not isinstance(g.get("hooks", []), list) for g in groups
    ):
        raise ValueError("Existing UserPromptSubmit configuration is invalid")
    if any(not isinstance(handler, dict) for group in groups for handler in group.get("hooks", [])):
        raise ValueError("Existing hook handlers must be objects")
    return doc


def hook_definition(python: Path, entry: Path, settings: Path, timeout: float) -> dict[str, Any]:
    argv = [str(python), "-I", str(entry), "hook", "--config", str(settings)]
    # PowerShell literal quoting keeps installer-generated paths safe across
    # shells. Submitted prompt text is read from stdin and never enters this command.
    ps = "& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in argv)
    encoded = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    return {
        "type": "command",
        "command": shlex.join(argv),
        "commandWindows": "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded,
        "timeout": math.ceil(3 * timeout + 6),
        "statusMessage": "jev-codex",
        "additionalContextLimit": 1800,
    }


def agent_file(profile: str, row: Profile) -> bytes:
    values = {
        "name": f"jev_{profile}",
        "description": f"Jev Router execution profile {profile}; accepts the parent's scoped assignment.",
        "model": row["model"],
        "model_reasoning_effort": row["effort"],
        "developer_instructions": AGENT_INSTRUCTIONS,
    }
    return (
        "# Managed by jev-codex-router. Edit profiles.toml, then rerun install.\n"
        + "\n".join(f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in values.items())
        + "\n"
    ).encode("utf-8")


def managed_outputs(home: Path, skills: Path, catalog: Catalog) -> dict[Path, bytes]:
    result = {
        skills / "jev-router" / name: (Path(__file__).parent / "resources" / name).read_bytes()
        for name in ("SKILL.md", "team-workflow.md")
    }
    for profile, row in catalog["profiles"].items():
        result[home / "agents" / f"jev_{profile}.toml"] = agent_file(profile, row)
    return result


def preflight(outputs: dict[Path, bytes], manifest: dict[str, Any]) -> None:
    known = manifest.get("files", {})
    for path in outputs:
        if path.is_symlink():
            raise ValueError(f"Refusing an existing symlink: {path}")
        if path.exists():
            current = digest(path.read_bytes())
            if current != known.get(str(path)):
                raise ValueError(f"Existing unowned or locally edited file preserved: {path}")


def global_instruction_update(home: Path, manifest: dict[str, Any]) -> tuple[Path, bytes, bool]:
    """Prepend a managed rule without changing the user's existing AGENTS.md bytes."""
    path = home / "AGENTS.md"
    if path.is_symlink():
        raise ValueError(f"Refusing an existing symlink: {path}")
    existed = path.exists()
    current = path.read_bytes() if existed else b""
    current.decode("utf-8-sig")
    bom = UTF8_BOM if current.startswith(UTF8_BOM) else b""
    body = current[len(bom) :]
    previous = manifest.get("global_instructions_block")
    if previous is not None:
        if not isinstance(previous, str) or not body.startswith(previous.encode("utf-8")):
            raise ValueError(f"Locally edited Jev instructions preserved: {path}")
        body = body[len(previous.encode("utf-8")) :]
    elif GLOBAL_MARKER in body:
        raise ValueError(f"Existing unowned Jev instructions preserved: {path}")
    return path, bom + GLOBAL_INSTRUCTIONS + body, existed


def config_warnings(home: Path) -> list[str]:
    warnings = []
    for filename in ("config.toml", "requirements.toml"):
        file = home / filename
        if not file.is_file():
            continue
        value = tomllib.loads(file.read_text(encoding="utf-8-sig"))
        if (
            value.get("features", {}).get("hooks") is False
            or value.get("features", {}).get("codex_hooks") is False
        ):
            warnings.append(
                f"{filename} disables hooks; this installer does not override that setting."
            )
        if value.get("allow_managed_hooks_only") is True:
            warnings.append(f"{filename} permits only managed hooks; this local hook will not run.")
        if value.get("agents", {}).get("enabled") is False:
            warnings.append(
                f"{filename} disables subagents; this installer leaves that choice unchanged."
            )
        if filename == "config.toml" and any(
            isinstance(groups, list) and groups for groups in value.get("hooks", {}).values()
        ):
            warnings.append(
                "Inline hooks also exist in config.toml. Review /hooks for duplicate routing hooks."
            )
    override = home / "AGENTS.override.md"
    if override.is_file() and override.stat().st_size:
        warnings.append("AGENTS.override.md takes precedence over Jev's global AGENTS.md rule.")
    return warnings


def register(
    home: Path, skills: Path, root: Path, python: Path, catalog: Catalog
) -> dict[str, Any]:
    """Register an already staged runtime; no dependency installation or API calls."""
    manifest = read_manifest(root)
    validate_locations(manifest, home, skills)
    outputs = managed_outputs(home, skills, catalog)
    preflight(outputs, manifest)
    instructions_path, instructions, instructions_existed = global_instruction_update(
        home, manifest
    )
    hooks_path = home / "hooks.json"
    existing_hooks = load_hooks(hooks_path)
    check_modified_handler(existing_hooks, manifest.get("handler"))
    hooks = remove_handler(existing_hooks, manifest.get("handler"))
    handler = hook_definition(
        python,
        root / "app" / "entry.py",
        root / "settings.json",
        catalog["policy"]["request_timeout_seconds"],
    )
    hooks.setdefault("hooks", {}).setdefault("UserPromptSubmit", []).append({"hooks": [handler]})
    original_hooks = hooks_path.read_bytes() if hooks_path.exists() else None
    if original_hooks is not None:
        backup = home / f"hooks.json.jev-{uuid.uuid4().hex[:12]}.bak"
        atomic_write(backup, original_hooks)
    snapshots = {p: p.read_bytes() if p.exists() else None for p in outputs}
    snapshots[hooks_path] = original_hooks
    snapshots[instructions_path] = instructions_path.read_bytes() if instructions_existed else None
    try:
        for path, data in outputs.items():
            atomic_write(path, data)
        atomic_write(hooks_path, json_bytes(hooks))
        atomic_write(instructions_path, instructions)
        updated = {
            "owner": OWNER,
            "codex_home": str(home),
            "skills_dir": str(skills),
            "files": {str(p): digest(data) for p, data in outputs.items()},
            "handler": handler,
            "global_instructions_block": GLOBAL_INSTRUCTIONS.decode("utf-8"),
            "global_instructions_file_existed": manifest.get(
                "global_instructions_file_existed", instructions_existed
            ),
            "original_hooks_existed": manifest.get(
                "original_hooks_existed", original_hooks is not None
            ),
        }
        atomic_write(root / "manifest.json", json_bytes(updated))
    except Exception:
        for path, saved_content in snapshots.items():
            if saved_content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, saved_content)
        raise
    # Profiles removed from the edited catalog are removed only if still unmodified.
    for old, expected in manifest.get("files", {}).items():
        path = Path(old)
        if (
            old not in updated["files"]
            and path.is_file()
            and not path.is_symlink()
            and digest(path.read_bytes()) == expected
        ):
            path.unlink()
    return updated


def uninstall(home: Path, root: Path) -> list[str]:
    manifest = read_manifest(root)
    if not manifest:
        return ["No registered installation found."]
    if manifest.get("codex_home") != str(home):
        raise ValueError("Manifest Codex home mismatch")
    hooks_path = home / "hooks.json"
    original = load_hooks(hooks_path)
    cleaned = remove_handler(original, manifest["handler"])
    messages = []
    if cleaned != original:
        atomic_write(
            home / f"hooks.json.jev-uninstall-{uuid.uuid4().hex[:12]}.bak", json_bytes(original)
        )
        if cleaned == {"hooks": {}} and not manifest["original_hooks_existed"]:
            hooks_path.unlink(missing_ok=True)
        else:
            atomic_write(hooks_path, json_bytes(cleaned))
    else:
        # A modified command is not assumed to belong to this installation.
        messages.append(
            "The registered hook is absent or modified. Modified hooks were preserved; review /hooks."
        )
    for name, expected in manifest["files"].items():
        path = Path(name)
        if not path.exists():
            continue
        if path.is_symlink() or digest(path.read_bytes()) != expected:
            messages.append(f"Preserved locally changed file: {path}")
        else:
            path.unlink()
    instructions_path = home / "AGENTS.md"
    previous = manifest.get("global_instructions_block")
    if previous is not None:
        if instructions_path.is_symlink() or not instructions_path.is_file():
            messages.append(
                f"Preserved missing or replaced global instructions: {instructions_path}"
            )
        else:
            current = instructions_path.read_bytes()
            bom = UTF8_BOM if current.startswith(UTF8_BOM) else b""
            owned = previous.encode("utf-8")
            if not current[len(bom) :].startswith(owned):
                messages.append(
                    f"Preserved locally changed global instructions: {instructions_path}"
                )
            else:
                restored_content = bom + current[len(bom) + len(owned) :]
                if not manifest.get("global_instructions_file_existed") and not restored_content:
                    instructions_path.unlink()
                else:
                    atomic_write(instructions_path, restored_content)
    (root / "secrets.json").unlink(missing_ok=True)
    (root / "manifest.json").unlink(missing_ok=True)
    # Keep the private runtime/config for an inspectable rollback and avoid deleting
    # an active Windows interpreter. No active hook or stored key remains from us.
    messages.append(
        f"Integrations and stored API key removed. Runtime/config retained at {root}; removable after Codex exits."
    )
    return messages


def prepare_runtime(root: Path, *, install_dependencies: bool = True) -> Path:
    """Create the private interpreter and replace the runtime through a staging directory."""
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = root / "OWNER"
    if any(root.iterdir()) and not marker.exists():
        raise ValueError("Refusing an existing unowned runtime directory")
    if marker.exists() and marker.read_text(encoding="utf-8").strip() != OWNER:
        raise ValueError("Runtime ownership marker mismatch")
    atomic_write(marker, (OWNER + "\n").encode())
    if os.name != "nt":
        root.chmod(0o700)
    env_dir = root / "venv"
    python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(env_dir)
    if install_dependencies:
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "--disable-pip-version-check",
                "install",
                "typesafe-sdk>=0.7.0,<0.8",
            ],
            check=True,
        )
        subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "from typesafe_sdk import Choice, Noul, NoulCriteria, RetryPolicy, TypeSafeClient",
            ],
            check=True,
        )
    app = root / "app"
    staged = root / ("stage-" + uuid.uuid4().hex)
    staged.mkdir()
    shutil.copytree(
        Path(__file__).parent,
        staged / "jev_router",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    atomic_write(staged / "entry.py", ENTRY.encode())
    previous = root / ("previous-" + uuid.uuid4().hex)
    if app.exists():
        app.rename(previous)
    try:
        staged.rename(app)
    except Exception:
        if previous.exists():
            previous.rename(app)
        raise
    if previous.exists():
        shutil.rmtree(previous)
    return python


def install(home: Path, skills: Path, *, without_key: bool) -> None:
    """Validate existing state, stage the runtime, then register owned integration files."""
    root = home / "jev-router"
    catalog_dir = root / "catalog"
    catalog = load_catalog(catalog_dir if catalog_dir.exists() else None)
    manifest = read_manifest(root)
    validate_locations(manifest, home, skills)
    preflight(managed_outputs(home, skills, catalog), manifest)
    global_instruction_update(home, manifest)
    hooks = load_hooks(home / "hooks.json")
    check_modified_handler(hooks, manifest.get("handler"))
    for warning in config_warnings(home):
        print("WARNING:", warning)

    print(
        "Jev Router sends submitted text and saved task summaries to TypeSafe by default. "
        "An explicit context_enabled=false setting is preserved."
    )
    print("Repository files and transcripts are not read or sent by the hook.")
    print("The parent model, permissions and hook trust remain unchanged.")
    has_environment_key = bool(os.environ.get("TYPESAFE_API_KEY", "").strip())
    has_saved_key = (root / "secrets.json").is_file()
    key = None
    if not without_key and not has_environment_key and not has_saved_key:
        if not sys.stdin.isatty():
            raise ValueError(
                "Set TYPESAFE_API_KEY or use --without-key for noninteractive installation"
            )
        print(f"The key will be stored locally in plaintext: {root / 'secrets.json'}")
        print("Unix mode: 0600. Windows: user-directory access controls. Blank input cancels.")
        key = prompt_api_key()

    python = prepare_runtime(root)
    install_catalog(catalog_dir)
    settings_path = root / "settings.json"
    if not settings_path.exists():
        settings = {
            "enabled": True,
            "context_enabled": True,
            "catalog_dir": str(catalog_dir),
            "credential_file": str(root / "secrets.json"),
        }
        atomic_write(settings_path, json_bytes(settings))
    if key:
        atomic_write(root / "secrets.json", json_bytes({"api_key": key}))
    register(home, skills, root, python, catalog)
    print(f"Installed. Editable prompts and policy: {catalog_dir}")
    print(f"Global routing rule: {home / 'AGENTS.md'}")
    print(
        "Restart Codex, then review/trust the UserPromptSubmit hook under user config in /hooks; "
        "its status reads jev-codex while running."
    )
    print("Model access and live Jev classification were not tested by installation.")
    command = [
        str(python),
        "-I",
        str(root / "app" / "entry.py"),
        "doctor",
        "--config",
        str(settings_path),
    ]
    print("Doctor:", console_command(command))


def console_command(arguments: list[str]) -> str:
    """Format a copyable command for PowerShell on Windows or a POSIX shell."""
    if os.name == "nt":
        return "& " + " ".join("'" + argument.replace("'", "''") + "'" for argument in arguments)
    return shlex.join(arguments)


def validate_locations(manifest: dict[str, Any], home: Path, skills: Path) -> None:
    if not manifest:
        return
    if manifest.get("codex_home") != str(home) or manifest.get("skills_dir") != str(skills):
        raise ValueError("Installation paths changed; uninstall before relocating")


def check_modified_handler(document: dict[str, Any], registered: dict[str, Any] | None) -> None:
    """Do not add a second handler beside a manually customized installed command."""
    if not registered:
        return
    for group in document.get("hooks", {}).get("UserPromptSubmit", []):
        for handler in group.get("hooks", []):
            same_command = any(
                registered.get(field) and handler.get(field) == registered[field]
                for field in ("command", "commandWindows")
            )
            if same_command and handler != registered:
                raise ValueError(
                    "The Jev hook was edited locally; reconcile it before reinstalling"
                )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install Jev Router into local Codex")
    parser.add_argument("--codex-home", type=Path, default=codex_home())
    parser.add_argument("--skills-dir", type=Path, default=Path.home() / ".agents" / "skills")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--without-key", action="store_true", help="Skip hidden key entry")
    parser.add_argument("--uninstall", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = args.codex_home.expanduser().resolve()
    skills = args.skills_dir.expanduser().resolve()
    root = home / "jev-router"
    try:
        if args.dry_run:
            plan = {
                "action": "uninstall" if args.uninstall else "install",
                "codex_home": str(home),
                "runtime": str(root),
                "skill": str(skills / "jev-router"),
                "hook": str(home / "hooks.json"),
                "global_instructions": str(home / "AGENTS.md"),
                "will_modify_parent_model": False,
                "will_bypass_hook_trust": False,
            }
            print(json.dumps(plan, indent=2))
        elif args.uninstall:
            print("\n".join(uninstall(home, root)))
        else:
            install(home, skills, without_key=args.without_key)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        # Setup errors may explain paths; raw subprocess/provider errors are not replayed.
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        print(f"Installation not completed: {message}", file=sys.stderr)
        return 1
