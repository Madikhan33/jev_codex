"""Classify a follow-up's relation before reusing a bounded local task capsule."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .contracts import Catalog
from .routing import Request, classify, read_choice, response_answers
from .session_state import render_context


def context_questions(directory: Path | None = None) -> dict[str, Any]:
    path = (
        directory / "context.toml" if directory else Path(__file__).parent / "prompts/context.toml"
    )
    if not path.is_file():
        path = Path(__file__).parent / "prompts/context.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    labels = {
        "new_task",
        "continue",
        "correct",
        "narrow",
        "approve",
        "cancel",
        "question",
        "unclear",
    }
    if set(data["criteria"]) != labels or any(
        not isinstance(value, str) or not value.strip()
        for value in [data["question"], data["scope"], *data["criteria"].values()]
    ):
        raise ValueError("Invalid context classification criteria")
    return {
        "relation": {
            "type": "choice",
            "instructions": {"question": data["question"], "scope": data["scope"]},
            "criteria": data["criteria"],
        }
    }


def route_with_context(
    prompt: str,
    request: Request,
    catalog: Catalog,
    capsule: dict[str, Any],
    *,
    directory: Path | None = None,
) -> dict[str, Any]:
    """Use at most three logical calls, with no transcript access or model escalation."""
    context = render_context(capsule)
    if not prompt.strip() or len(prompt) > catalog["policy"]["max_prompt_chars"]:
        raise ValueError("Invalid prompt length")
    if len(context) > catalog["policy"]["max_context_chars"]:
        raise ValueError("Context exceeds configured limit")
    questions = context_questions(directory)
    response = request({"request": prompt, "context": context}, questions)
    decision = read_choice(
        response_answers(response),
        "relation",
        set(questions["relation"]["criteria"]),
        catalog["policy"],
    )
    relation = decision["value"] if decision["accepted"] else "unclear"
    use_context = relation in {"continue", "correct", "narrow", "approve", "question"}
    # Several relation labels can split probability while agreeing on the same
    # referent. Preserve uncertainty about action, without discarding that referent.
    if not decision["accepted"]:
        distribution = response_answers(response)["relation"]["probabilities"]
        related_mass = sum(
            distribution[name] for name in ("continue", "correct", "narrow", "approve", "question")
        )
        if related_mass >= catalog["policy"]["yes_threshold"]:
            relation, use_context = "related_unspecified", True
    # Cancellation needs the lead to stop real workers, not another classification call.
    result = (
        None
        if relation == "cancel"
        else classify(prompt, request, context=context if use_context else "", catalog=catalog)
    )
    return {
        "result": result,
        "relation": relation,
        "relation_decision": decision,
        "context_used": use_context,
        "context_revision": capsule["revision"],
        "task_id": capsule["task_id"],
        "additional_relation_calls": 1,
        "relation_usage": response.get("usage"),
    }
