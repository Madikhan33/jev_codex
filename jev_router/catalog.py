"""Load and validate editable prompts and routing policy before any API call."""

from __future__ import annotations

import math
import re
import shutil
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

PACKAGE = Path(__file__).resolve().parent
DATA = PACKAGE / "data"
PROMPTS = PACKAGE / "prompts"
IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
MODEL_ID = re.compile(r"[a-zA-Z0-9._:/-]+")


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
    catalog = {
        "categories": read_toml(prompt_directory / "domains.toml")["categories"],
        "profiles": read_toml(prompt_directory / "profiles.toml")["profiles"],
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
            shutil.copyfile(PROMPTS / name, directory / name)
        shutil.copyfile(DATA / "policy.toml", directory / "policy.toml")
    if not (directory / "routing.toml").exists():
        shutil.copyfile(PROMPTS / "routing.toml", directory / "routing.toml")
    if not (directory / "context.toml").exists():
        shutil.copyfile(PROMPTS / "context.toml", directory / "context.toml")


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
        if profile.get("family") not in {"luna", "sol", "astra"}:
            raise ValueError("Unknown model family")
        if not MODEL_ID.fullmatch(profile["model"]):
            raise ValueError("Invalid configured model ID")
        if profile.get("effort") not in {"low", "medium", "high"}:
            raise ValueError("Unsupported policy effort")
        is_astra = profile["family"] == "astra" or "astra" in profile["model"].lower()
        if is_astra and profile["effort"] not in {"low", "medium"}:
            raise ValueError("Astra is restricted to low or medium")
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
