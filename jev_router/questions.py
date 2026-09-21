"""Build TypeSafe question payloads from the human-editable prompts directory."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .contracts import Catalog

_DEFAULTS = tomllib.loads(
    (Path(__file__).parent / "prompts" / "routing.toml").read_text(encoding="utf-8-sig")
)
# Retained for callers that enumerate the public control labels.
SCOPE = _DEFAULTS["scope"]
INTENTS = _DEFAULTS["intent"]["criteria"]
COORDINATION = _DEFAULTS["coordination"]["criteria"]
UNKNOWN_PROFILE = _DEFAULTS["profile"]["needs_context"]


def detection_questions(catalog: Catalog) -> dict[str, Any]:
    """Ask independent category questions and controls in one provider request."""
    prompts = catalog["routing"]
    questions: dict[str, Any] = {}
    for name, category in catalog["categories"].items():
        questions[f"work.{name}"] = {
            "type": "noul",
            "instructions": {
                "question": category["question"],
                "scope": prompts["scope"],
                "positive_examples": category["positive_examples"],
                "negative_examples": category["negative_examples"],
            },
            "criteria": {"true": category["yes"], "false": category["no"]},
        }
    # TypeSafe evaluates questions independently. A scope rule on a category does
    # not also constrain intent/coordination; each question needs its own scope.
    for name in ("intent", "coordination"):
        questions[name] = {
            "type": "choice",
            "instructions": {"question": prompts[name]["question"], "scope": prompts["scope"]},
            "criteria": dict(prompts[name]["criteria"]),
        }
    uncovered = prompts["uncovered"]
    questions["uncovered"] = {
        "type": "noul",
        "instructions": {
            "question": uncovered["question"],
            "scope": prompts["scope"],
            "catalog": {
                name: category["title"] for name, category in catalog["categories"].items()
            },
        },
        "criteria": {"true": uncovered["yes"], "false": uncovered["no"]},
    }
    return questions


def profile_questions(catalog: Catalog, selected: list[str]) -> dict[str, Any]:
    """Ask a profile question only for each accepted category, never for absent work."""
    prompts = catalog["routing"]
    criteria = {name: profile["criterion"] for name, profile in catalog["profiles"].items()}
    criteria["needs_context"] = prompts["profile"]["needs_context"]
    questions = {}
    for name in selected:
        category = catalog["categories"][name]
        questions[f"profile.{name}"] = {
            "type": "choice",
            "instructions": {
                "question": prompts["profile"]["question"],
                "scope": prompts["scope"],
                "work_type": category["title"],
                "definition": category["yes"],
                "outside_scope": category["no"],
                "calibration": category["profile_notes"],
                "decision_basis": prompts["profile"]["decision_basis"],
            },
            "criteria": dict(criteria),
        }
    return questions
