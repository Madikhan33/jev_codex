"""Load and validate editable prompts and routing policy before any API call."""

from __future__ import annotations

import hashlib
import math
import re
import tomllib
from pathlib import Path
from typing import Any, cast

from .contracts import Catalog
from .questions import (
    COORDINATION as COORDINATION,
)
from .questions import (
    INTENTS as INTENTS,
)
from .questions import (
    SCOPE as SCOPE,
)
from .questions import (
    UNKNOWN_PROFILE as UNKNOWN_PROFILE,
)
from .questions import (
    detection_questions as detection_questions,
)
from .questions import (
    profile_questions as profile_questions,
)
from .storage import atomic_write

PACKAGE = Path(__file__).resolve().parent
DATA = PACKAGE / "data"
PROMPTS = PACKAGE / "prompts"
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
MODEL_ID = re.compile(r"[a-zA-Z0-9._:/-]+")
LEGACY_PROFILES_SHA256 = "b1cdfd70766b951488742b20cba92a448d130fad7cdc5da288d34a714553e6de"
MODEL_BY_FAMILY = {
    "luna": "gpt-6-luna",
    "sol": "gpt-6-sol",
}
EFFORTS_BY_FAMILY = {
    "luna": {"xhigh", "max"},
    "sol": {"medium", "high", "xhigh"},
}


def default_legacy_profiles(path: Path) -> bool:
    return (
        path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == LEGACY_PROFILES_SHA256
    )


def read_toml(path: Path) -> dict[str, Any]:
    """Read UTF-8 TOML, accepting the BOM produced by some Windows editors."""
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))


def load_catalog(directory: Path | None = None) -> Catalog:
    """Load bundled prompts or a complete installed catalog.

    Older installations lack routing.toml; only that new file falls back to the
    bundled copy. Missing category/profile/policy files remain configuration errors.
    """
    prompt_directory = directory or PROMPTS
    policy_directory = directory or DATA
    routing_path = prompt_directory / "routing.toml"
    if not routing_path.exists():
        routing_path = PROMPTS / "routing.toml"
    profile_path = prompt_directory / "profiles.toml"
    if directory is not None and default_legacy_profiles(profile_path):
        profile_path = PROMPTS / "profiles.toml"
    catalog = {
        "categories": read_toml(prompt_directory / "domains.toml")["categories"],
        "profiles": read_toml(profile_path)["profiles"],
        "policy": read_toml(policy_directory / "policy.toml")["policy"],
        "routing": read_toml(routing_path),
    }
    validate_catalog(catalog)
    return cast(Catalog, catalog)


def install_catalog(directory: Path) -> None:
    """Seed a fresh catalog, or add the new control prompts to a legacy catalog."""
    is_new = not directory.exists()
    directory.mkdir(parents=True, exist_ok=True)
    if is_new:
        for name in ("domains.toml", "profiles.toml"):
            atomic_write(directory / name, (PROMPTS / name).read_bytes())
        atomic_write(directory / "policy.toml", (DATA / "policy.toml").read_bytes())
    elif default_legacy_profiles(directory / "profiles.toml"):
        atomic_write(directory / "profiles.toml", (PROMPTS / "profiles.toml").read_bytes())
    if not (directory / "routing.toml").exists():
        atomic_write(directory / "routing.toml", (PROMPTS / "routing.toml").read_bytes())
    if not (directory / "context.toml").exists():
        atomic_write(directory / "context.toml", (PROMPTS / "context.toml").read_bytes())


def require_text(section: dict[str, Any], fields: tuple[str, ...], name: str) -> None:
    for field in fields:
        value = section.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name}.{field} must be nonempty text")


def validate_catalog(catalog: dict[str, Any]) -> None:
    """Reject malformed configuration before building questions or spawning agents."""
    categories = catalog["categories"]
    profiles = catalog["profiles"]
    policy = catalog["policy"]
    if not isinstance(categories, dict) or not isinstance(profiles, dict):
        raise ValueError("Categories and profiles must be TOML tables")
    if not categories or not profiles:
        raise ValueError("Categories and profiles cannot be empty")

    for name, category in categories.items():
        if not IDENTIFIER.fullmatch(name) or not isinstance(category, dict):
            raise ValueError("Invalid category definition")
        require_text(
            category, ("domain", "owner", "title", "question", "yes", "no", "profile_notes"), name
        )
        for field in ("positive_examples", "negative_examples"):
            examples = category.get(field)
            if not isinstance(examples, list) or not examples:
                raise ValueError(f"{name}.{field} must contain examples")
            if any(not isinstance(example, str) or not example.strip() for example in examples):
                raise ValueError(f"{name}.{field} must contain nonempty text")

    for name, profile in profiles.items():
        if (
            not IDENTIFIER.fullmatch(name)
            or name == "needs_context"
            or not isinstance(profile, dict)
        ):
            raise ValueError("Invalid profile definition")
        require_text(profile, ("model", "criterion"), name)
        family = profile.get("family")
        if family not in EFFORTS_BY_FAMILY:
            raise ValueError("Unknown model family")
        if profile["model"] != MODEL_BY_FAMILY[family]:
            raise ValueError(f"Configured model must be {MODEL_BY_FAMILY[family]} for {family}")
        if profile.get("effort") not in EFFORTS_BY_FAMILY[family]:
            raise ValueError(f"Unsupported effort for {family}: {profile.get('effort')}")
        if type(profile.get("rank")) is not int:
            raise ValueError("Profile rank must be an integer")

    validate_policy(policy)
    routing = catalog["routing"]
    require_text(routing, ("scope",), "routing")
    for name, choices in (("intent", INTENTS), ("coordination", COORDINATION)):
        section = routing[name]
        require_text(section, ("question",), name)
        if set(section["criteria"]) != set(choices):
            raise ValueError(f"{name} choices must retain the supported labels")
        require_text(section["criteria"], tuple(choices), name)
    require_text(routing["uncovered"], ("question", "yes", "no"), "uncovered")
    require_text(routing["profile"], ("question", "decision_basis", "needs_context"), "profile")


def validate_policy(policy: dict[str, Any]) -> None:
    numeric_fields = (
        "no_threshold",
        "yes_threshold",
        "profile_threshold",
        "profile_margin",
        "request_timeout_seconds",
    )
    for name in numeric_fields:
        value = policy.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"{name} must be a finite number")
    if not 0 <= policy["no_threshold"] < policy["yes_threshold"] <= 1:
        raise ValueError("Invalid category thresholds")
    if not 0.5 <= policy["profile_threshold"] <= 1 or not 0 <= policy["profile_margin"] <= 1:
        raise ValueError("Invalid profile thresholds")
    for name in ("top_k", "max_prompt_chars", "max_context_chars"):
        if type(policy.get(name)) is not int or policy[name] < 1:
            raise ValueError(f"{name} must be a positive integer")
    if not 0 < policy["request_timeout_seconds"] <= 10:
        raise ValueError("Request timeout must be between 0 and 10 seconds")
    require_text(policy, ("jev_model",), "policy")
    if not MODEL_ID.fullmatch(policy["jev_model"]):
        raise ValueError("Invalid Jev model ID")
