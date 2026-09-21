"""Local settings and credentials, separate from all model-visible content."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()


def default_settings_path() -> Path:
    return codex_home() / "jev-router" / "settings.json"


def read_settings(path: Path | None = None) -> dict[str, Any]:
    target = path or default_settings_path()
    if target.exists():
        result = json.loads(target.read_text(encoding="utf-8-sig"))
        if not isinstance(result, dict):
            raise ValueError("Settings must be a JSON object")
    else:
        result = {}
    result.setdefault("enabled", True)
    if type(result["enabled"]) is not bool:
        raise ValueError("enabled must be a JSON boolean")
    result.setdefault("context_enabled", True)
    if type(result["context_enabled"]) is not bool:
        raise ValueError("context_enabled must be a JSON boolean")
    result.setdefault("state_dir", str(target.parent / "sessions"))
    result.setdefault("credential_file", str(target.parent / "secrets.json"))
    for name in ("credential_file", "catalog_dir", "state_dir"):
        if name in result and (not isinstance(result[name], str) or not result[name].strip()):
            raise ValueError(f"{name} must be a nonempty path")
    return result


def catalog_directory(settings: dict[str, Any]) -> Path | None:
    """Resolve an optional installed catalog without requiring an installation."""
    directory = settings.get("catalog_dir")
    return Path(directory).expanduser() if directory else None


def get_api_key(settings: dict[str, Any]) -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    credential = Path(settings["credential_file"]).expanduser()
    if credential.is_file():
        data = json.loads(credential.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("Credential file must contain a JSON object")
        key = data.get("api_key", "")
        if isinstance(key, str) and key.strip():
            return key.strip()
    raise RuntimeError("TYPESAFE_API_KEY is not configured")


def prompt_api_key() -> str:
    """Read a key without echo; noninteractive input must never silently echo it."""
    import getpass
    import warnings

    if not sys.stdin.isatty():
        raise ValueError("Credential entry requires an interactive terminal")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        key = getpass.getpass("TypeSafe API key (hidden): ").strip()
    if not key or "\n" in key or "\r" in key:
        raise ValueError("A nonempty single-line API key is required")
    return key


def configure_credentials(config: Path | None, settings: dict[str, Any]) -> int:
    """Persist a manually entered key outside model-visible output."""
    from .storage import atomic_write, json_bytes

    root = (config or default_settings_path()).parent
    if not (root / "manifest.json").is_file():
        print("Install the router first: install.py --without-key", file=sys.stderr)
        return 1
    if not sys.stdin.isatty():
        print("Run configure in an interactive terminal to enter a hidden key.", file=sys.stderr)
        return 1
    target = Path(settings["credential_file"]).expanduser()
    print(f"Store key locally in plaintext: {target}")
    print("Input is hidden. Blank input cancels. Never paste your key into a Codex chat.")
    key = prompt_api_key()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(target, json_bytes({"api_key": key}))
    print("Key saved. Environment variable TYPESAFE_API_KEY takes precedence if set.")
    return 0
