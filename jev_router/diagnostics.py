"""Local installation checks. No API calls, key output or hook-trust mutations."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .catalog import load_catalog
from .installer import config_warnings, load_hooks, read_manifest
from .settings import catalog_directory, default_settings_path, get_api_key
from .storage import digest


def inspect_installation(
    config: Path | None,
    settings: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Return per-check status even when one local integration file is malformed."""
    target = config or default_settings_path()
    checks: dict[str, Any] = {
        "python": sys.version.split()[0],
        "sdk_importable": importlib.util.find_spec("typesafe_sdk") is not None,
        "codex_on_path": shutil.which("codex") is not None,
        "settings_file": str(target),
        "enabled": settings["enabled"] and os.environ.get("JEV_ROUTER_DISABLE") != "1",
        "network_tested": False,
        "hook_trust": "Review in Codex with /hooks; not modified by this tool",
        "model_availability": "Not verified for this account",
        "context_enabled": settings.get("context_enabled", False),
        "context_source": "Explicit local task capsules; no transcript access",
    }
    try:
        get_api_key(settings)
        checks["key_configured"] = True
    except (OSError, ValueError, RuntimeError):
        checks["key_configured"] = False
    try:
        load_catalog(catalog_directory(settings))
        checks["catalog_valid"] = True
    except (OSError, ValueError, KeyError, TypeError):
        checks["catalog_valid"] = False

    root = target.resolve().parent
    checks.update(registered=False, integration_files_intact=False, hook_registered=False)
    warnings = []
    try:
        manifest = read_manifest(root)
        checks["registered"] = bool(manifest)
        checks["integration_files_intact"] = bool(manifest) and all(
            Path(path).is_file() and digest(Path(path).read_bytes()) == expected
            for path, expected in manifest.get("files", {}).items()
        )
        home = Path(manifest["codex_home"]) if manifest else root.parent
        groups = load_hooks(home / "hooks.json").get("hooks", {}).get("UserPromptSubmit", [])
        checks["hook_registered"] = bool(manifest) and any(
            manifest["handler"] == handler for group in groups for handler in group.get("hooks", [])
        )
        warnings.extend(config_warnings(home))
    except (OSError, ValueError, KeyError, TypeError):
        warnings.append(
            "Installation metadata or Codex configuration is unreadable; inspect local files."
        )
    checks["configuration_warnings"] = warnings
    required = (
        "sdk_importable",
        "key_configured",
        "catalog_valid",
        "enabled",
        "registered",
        "integration_files_intact",
        "hook_registered",
    )
    return checks, all(checks[name] for name in required) and not warnings
