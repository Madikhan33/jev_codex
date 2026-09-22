"""Two-stage classification followed by deterministic ownership and strategy rules."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from .catalog import load_catalog
from .contracts import (
    Catalog,
    CategoryScore,
    ChoiceDecision,
    OwnershipGroup,
    Policy,
    RoutingResult,
    Usage,
    WorkRoute,
)
from .questions import COORDINATION, INTENTS, detection_questions, profile_questions

# JSON from an external provider is untrusted until the readers below validate it.
Request = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
IMPLEMENTATION_OWNERS = {"interface", "server", "ai", "infrastructure", "tooling"}


def probability(value: object) -> float:
    """Accept finite probabilities only; booleans are not numeric answers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Probability must be numeric")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise ValueError("Probability outside [0, 1]")
    return number


def read_noul(answers: dict[str, Any], key: str) -> float:
    """Read a required yes/no answer without inventing a missing result."""
    answer = answers[key]
    if not isinstance(answer, dict) or answer.get("type") != "noul":
        raise ValueError(f"Expected a Noul answer for {key}")
    return probability(answer["noul"])


def read_choice(
    answers: dict[str, Any],
    key: str,
    allowed: set[str],
    policy: Policy,
) -> ChoiceDecision:
    """Validate the full distribution, then apply probability and margin thresholds."""
    answer = answers[key]
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        raise ValueError(f"Expected a Choice answer for {key}")
    chosen = answer.get("choice")
    if not isinstance(chosen, str) or chosen not in allowed:
        raise ValueError(f"Unknown choice for {key}")
    distribution = answer.get("probabilities")
    if not isinstance(distribution, dict) or set(distribution) != allowed:
        raise ValueError("Choice probability keys do not match the question")
    probabilities = {label: probability(value) for label, value in distribution.items()}
    if abs(sum(probabilities.values()) - 1.0) > 0.02:
        raise ValueError("Choice distribution is not normalized")
    selected_probability = probabilities[chosen]
    runner_up = max(
        (value for label, value in probabilities.items() if label != chosen),
        default=0,
    )
    if selected_probability + 1e-6 < runner_up:
        raise ValueError("Selected choice is not a maximum-probability candidate")
    is_accepted = (
        selected_probability >= policy["profile_threshold"]
        and selected_probability - runner_up >= policy["profile_margin"]
    )
    return {
        "value": chosen,
        "probability": selected_probability,
        "confidence": probability(answer["confidence"]),
        "accepted": is_accepted,
    }


def merge_groups(routes: list[WorkRoute], catalog: Catalog) -> list[OwnershipGroup]:
    """Combine related categories; an uncertain profile keeps its owner unresolved."""
    routes_by_owner: dict[str, list[WorkRoute]] = defaultdict(list)
    for route in routes:
        owner = catalog["categories"][route["work_type"]]["owner"]
        routes_by_owner[owner].append(route)

    implementation_owners = [owner for owner in routes_by_owner if owner in IMPLEMENTATION_OWNERS]
    if "verification" in routes_by_owner and len(implementation_owners) == 1:
        # Routine tests can stay with their implementation owner. An explicitly
        # requested independent review still overrides this advisory grouping.
        owner = implementation_owners[0]
        routes_by_owner[owner].extend(routes_by_owner.pop("verification"))

    groups: list[OwnershipGroup] = []
    for owner, owned_routes in sorted(routes_by_owner.items()):
        known_profiles = [
            route["profile"] for route in owned_routes if route["profile"] is not None
        ]
        selected_profile = None
        if len(known_profiles) == len(owned_routes):
            selected_profile = max(
                known_profiles, key=lambda name: catalog["profiles"][name]["rank"]
            )
        profile = catalog["profiles"][selected_profile] if selected_profile else None
        groups.append(
            {
                "owner": owner,
                "work_types": [route["work_type"] for route in owned_routes],
                "profile": selected_profile,
                "agent_type": f"jev_{selected_profile}" if selected_profile else None,
                "model": profile["model"] if profile else None,
                "effort": profile["effort"] if profile else None,
            }
        )
    return groups


def response_answers(response: dict[str, Any]) -> dict[str, Any]:
    answers = response["answers"]
    if not isinstance(answers, dict):
        raise ValueError("Provider answers must be an object")
    return answers


def select_profiles(
    selected: list[CategoryScore],
    answers: dict[str, Any],
    catalog: Catalog,
) -> list[WorkRoute]:
    routes: list[WorkRoute] = []
    allowed = set(catalog["profiles"]) | {"needs_context"}
    for category in selected:
        decision = read_choice(
            answers, f"profile.{category['work_type']}", allowed, catalog["policy"]
        )
        profile = None
        if decision["accepted"] and decision["value"] != "needs_context":
            profile = decision["value"]
        routes.append({**category, "profile": profile, "profile_decision": decision})
    return routes


def choose_strategy(
    intent: ChoiceDecision,
    coordination: ChoiceDecision,
    groups: list[OwnershipGroup],
) -> str:
    """Separate assignment from concurrency; advisory uncertainty is not a global stop."""
    if not intent["accepted"] or intent["value"] == "unclear":
        return "resolve_scope"
    if intent["value"] in {"explain", "non_software"}:
        return "single_agent"
    if not groups:
        return "resolve_scope"
    if len(groups) > 1:
        if coordination["accepted"] and coordination["value"] == "separable":
            return "consider_delegation"
        return "coordinate_team"
    return "assign_specialist"


def summarize_usage(responses: list[dict[str, Any]]) -> Usage:
    """Unknown usage remains null; a missing field is never counted as zero."""
    totals: dict[str, int | None] = {}
    for field in ("input_tokens", "output_tokens"):
        values: list[int] = []
        for response in responses:
            usage = response.get("usage")
            value = usage.get(field) if isinstance(usage, dict) else None
            if type(value) is not int or value < 0:
                break
            values.append(value)
        if len(values) == len(responses):
            totals[field] = sum(values)
        else:
            totals[field] = None
    return {
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "classification_calls": len(responses),
    }


def classify(
    prompt: str,
    request: Request,
    *,
    context: str = "",
    catalog: Catalog | None = None,
    top_k: int | None = None,
) -> RoutingResult:
    """Classify work, select profiles and return the public v3 route.

    At most two sequential provider calls are made. The second depends on accepted
    categories. Input and provider errors propagate to the CLI or fail-open hook.
    """
    catalog = catalog or load_catalog()
    policy = catalog["policy"]
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("A nonempty prompt is required")
    if not isinstance(context, str):
        raise TypeError("context must be a string")
    if len(prompt) > policy["max_prompt_chars"] or len(context) > policy["max_context_chars"]:
        raise ValueError("Input exceeds configured limits; content was not truncated or sent")
    candidate_limit = policy["top_k"] if top_k is None else top_k
    if type(candidate_limit) is not int or candidate_limit < 1:
        raise ValueError("top_k must be a positive integer")

    state = {"request": prompt, "context": context}
    detection_response = request(state, detection_questions(catalog))
    answers = response_answers(detection_response)
    ranked: list[CategoryScore] = [
        {
            "work_type": name,
            "domain": category["domain"],
            "probability": read_noul(answers, f"work.{name}"),
        }
        for name, category in catalog["categories"].items()
    ]
    ranked.sort(key=lambda category: (-category["probability"], category["work_type"]))
    selected = [
        category for category in ranked if category["probability"] >= policy["yes_threshold"]
    ]
    uncertain = [
        category
        for category in ranked
        if policy["no_threshold"] < category["probability"] < policy["yes_threshold"]
    ]
    intent = read_choice(answers, "intent", set(INTENTS), policy)
    coordination = read_choice(answers, "coordination", set(COORDINATION), policy)
    uncovered = read_noul(answers, "uncovered")

    responses = [detection_response]
    routes: list[WorkRoute] = []
    if selected:
        questions = profile_questions(catalog, [category["work_type"] for category in selected])
        profile_response = request(state, questions)
        responses.append(profile_response)
        routes = select_profiles(selected, response_answers(profile_response), catalog)

    groups = merge_groups(routes, catalog)
    has_uncovered_work = uncovered > policy["no_threshold"]
    missing_work = not routes and intent["value"] != "non_software"
    unclear_coordination = len(groups) > 1 and (
        not coordination["accepted"] or coordination["value"] == "unclear"
    )
    review_required = bool(
        uncertain
        or has_uncovered_work
        or missing_work
        or unclear_coordination
        or not intent["accepted"]
        or intent["value"] == "unclear"
        or any(route["profile"] is None for route in routes)
    )
    candidates = [
        category for category in ranked if category["probability"] > policy["no_threshold"]
    ]
    return {
        "schema_version": 3,
        "intent": intent,
        "coordination": coordination,
        "routes": routes,
        "groups": groups,
        "top_candidates": candidates[:candidate_limit],
        "uncertain": uncertain,
        "uncovered_probability": uncovered,
        "has_uncovered_work": has_uncovered_work,
        "review_required": review_required,
        "strategy": choose_strategy(intent, coordination, groups),
        "capabilities_verified": False,
        "usage": summarize_usage(responses),
    }


def compact_route(result: RoutingResult) -> dict[str, Any]:
    """Expose validated labels only, never raw user input or provider instructions."""
    return {
        "v": 3,
        "intent": result["intent"]["value"] if result["intent"]["accepted"] else "unclear",
        "strategy": result["strategy"],
        "coordination": (
            result["coordination"]["value"] if result["coordination"]["accepted"] else "unclear"
        ),
        "review_required": result["review_required"],
        "groups": result["groups"],
        "uncertain": [category["work_type"] for category in result["uncertain"]],
        "uncovered": result["has_uncovered_work"],
        "capabilities_verified": False,
    }
