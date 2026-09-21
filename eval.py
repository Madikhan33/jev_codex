"""Opt-in paid Jev evaluation. Authored expectations are not model-quality evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from jev_router.catalog import load_catalog
from jev_router.contracts import Catalog
from jev_router.questions import INTENTS
from jev_router.routing import Request, classify, compact_route
from jev_router.settings import catalog_directory, get_api_key, read_settings

STRATEGIES = {
    "single_agent",
    "resolve_scope",
    "assign_specialist",
    "consider_delegation",
    "coordinate_team",
}


def validate_cases(cases: list[dict[str, Any]], catalog: Catalog) -> None:
    """Reject invalid labels before spending any provider calls."""
    if not cases:
        raise ValueError("At least one labeled case is required")
    identifiers = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each case must be an object")
        identifier = case.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("Case IDs must be nonempty and unique")
        identifiers.add(identifier)
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            raise ValueError("Each case needs a prompt")
        if not isinstance(case.get("context", ""), str):
            raise ValueError("Context must be text")
        categories = case.get("categories")
        if not isinstance(categories, list) or any(
            not isinstance(item, str) or item not in catalog["categories"] for item in categories
        ):
            raise ValueError("Unknown expected category")
        if len(categories) != len(set(categories)):
            raise ValueError("Duplicate expected category")
        profiles = case.get("acceptable_profiles", {})
        if not isinstance(profiles, dict):
            raise ValueError("Profile expectations must be an object")
        for category, acceptable in profiles.items():
            if category not in categories or not isinstance(acceptable, list) or not acceptable:
                raise ValueError("Profile expectations require an expected category and choices")
            if any(
                item is not None and (not isinstance(item, str) or item not in catalog["profiles"])
                for item in acceptable
            ):
                raise ValueError("Unknown expected profile")
        if "expected_intent" in case and "acceptable_intents" in case:
            raise ValueError("Use expected_intent or acceptable_intents, not both")
        if "expected_intent" in case or "acceptable_intents" in case:
            intents = case.get("acceptable_intents", [case.get("expected_intent")])
            if (
                not isinstance(intents, list)
                or not intents
                or any(not isinstance(item, str) or item not in INTENTS for item in intents)
            ):
                raise ValueError("Unknown expected intent")
        if "acceptable_strategies" in case:
            strategies = case["acceptable_strategies"]
            if (
                not isinstance(strategies, list)
                or not strategies
                or any(not isinstance(item, str) or item not in STRATEGIES for item in strategies)
            ):
                raise ValueError("Unknown expected strategy")
        if (
            "expected_review_required" in case
            and type(case["expected_review_required"]) is not bool
        ):
            raise ValueError("Expected review flag must be boolean")
        if (
            len(case["prompt"]) > catalog["policy"]["max_prompt_chars"]
            or len(case.get("context", "")) > catalog["policy"]["max_context_chars"]
        ):
            raise ValueError("Case exceeds configured input limits")


def evaluate_cases(
    cases: list[dict[str, Any]], request: Request, catalog: Catalog
) -> dict[str, Any]:
    """Measure classification policy, including abstentions and transport failures.

    Context is supplied explicitly by the fixture. This does not exercise automatic
    context recovery, Codex spawning, account access, or worker task quality.
    """
    validate_cases(cases, catalog)
    true_positives = false_positives = false_negatives = exact_matches = calls = 0
    profile_correct = profile_total = profile_selected = intent_correct = intent_total = 0
    strategy_correct = strategy_total = review_correct = review_total = 0
    errors = passed = 0
    details = []

    def counted_request(state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return request(state, questions)

    for case in cases:
        started = time.perf_counter()
        result = None
        error = None
        try:
            result = classify(
                case["prompt"], counted_request, context=case.get("context", ""), catalog=catalog
            )
        except Exception as exc:
            # Provider exceptions can contain submitted text or credentials.
            error = type(exc).__name__
            errors += 1
        elapsed_ms = (time.perf_counter() - started) * 1000
        expected = set(case["categories"])
        predicted = {route["work_type"] for route in result["routes"]} if result else set()
        true_positives += len(expected & predicted)
        false_positives += len(predicted - expected)
        false_negatives += len(expected - predicted)
        category_match = result is not None and predicted == expected
        exact_matches += category_match
        profiles = (
            {route["work_type"]: route["profile"] for route in result["routes"]} if result else {}
        )
        profile_decisions = (
            {route["work_type"]: route["profile_decision"] for route in result["routes"]}
            if result
            else {}
        )
        profile_errors = []
        for category, acceptable in case.get("acceptable_profiles", {}).items():
            profile_total += 1
            profile_selected += profiles.get(category) is not None
            decision = profile_decisions.get(category)
            if (
                category in profiles
                and profiles[category] in acceptable
                and decision is not None
                and decision["accepted"]
            ):
                profile_correct += 1
            else:
                profile_errors.append(category)
        route = compact_route(result) if result else None
        intent_matches = strategy_matches = review_matches = None
        if "expected_intent" in case or "acceptable_intents" in case:
            intent_total += 1
            intents = case.get("acceptable_intents", [case.get("expected_intent")])
            intent_matches = route is not None and route["intent"] in intents
            intent_correct += intent_matches
        if "acceptable_strategies" in case:
            strategy_total += 1
            strategy_matches = (
                route is not None and route["strategy"] in case["acceptable_strategies"]
            )
            strategy_correct += strategy_matches
        if "expected_review_required" in case:
            review_total += 1
            review_matches = (
                result is not None and result["review_required"] == case["expected_review_required"]
            )
            review_correct += review_matches
        case_passed = (
            category_match
            and not profile_errors
            and all(
                match is not False for match in (intent_matches, strategy_matches, review_matches)
            )
        )
        passed += case_passed
        details.append(
            {
                "id": case["id"],
                "passed": case_passed,
                "error_type": error,
                "missing": sorted(expected - predicted),
                "extra": sorted(predicted - expected),
                "profiles": profiles,
                "profile_decisions": profile_decisions,
                "checked_axes": ["categories"]
                + (["profiles"] if case.get("acceptable_profiles") else [])
                + (["intent"] if intent_matches is not None else [])
                + (["strategy"] if strategy_matches is not None else [])
                + (["review_required"] if review_matches is not None else []),
                "profile_errors": profile_errors,
                "intent_matches": intent_matches,
                "strategy_matches": strategy_matches,
                "review_matches": review_matches,
                "review_required": result["review_required"] if result else None,
                "route": route,
                "elapsed_ms": round(elapsed_ms, 2),
                "usage": result["usage"] if result else None,
            }
        )

    predicted_total = true_positives + false_positives
    expected_total = true_positives + false_negatives
    return {
        "cases": len(cases),
        "expectations_passed_cases": passed,
        "expectations_failed_cases": len(cases) - passed,
        "pass_basis": "annotated expectations only; unannotated axes and dispatch are not assessed",
        "error_cases": errors,
        "micro_precision": true_positives / predicted_total if predicted_total else None,
        "micro_recall": true_positives / expected_total if expected_total else None,
        "exact_match": exact_matches / len(cases),
        "classification_calls": calls,
        "profile_accuracy_measured": profile_total > 0,
        "profile_cases": profile_total,
        "profile_accuracy": profile_correct / profile_total if profile_total else None,
        "profile_selection_rate": profile_selected / profile_total if profile_total else None,
        "intent_cases": intent_total,
        "intent_accuracy": intent_correct / intent_total if intent_total else None,
        "strategy_cases": strategy_total,
        "strategy_accuracy": strategy_correct / strategy_total if strategy_total else None,
        "review_cases": review_total,
        "review_accuracy": review_correct / review_total if review_total else None,
        "codex_quality_measured": False,
        "codex_spawn_measured": False,
        "automatic_context_recovery_measured": False,
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run paid Jev calls against labeled examples")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--cases", type=Path, default=Path(__file__).parent / "tests" / "cases.json"
    )
    parser.add_argument(
        "--catalog", type=Path, help="Override installed catalog for reproducible tests"
    )
    parser.add_argument(
        "--output", type=Path, help="Save report without input prompts or credentials"
    )
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("limit must be positive")
    settings = read_settings(args.config)
    catalog = load_catalog(args.catalog or catalog_directory(settings))
    fixture_bytes = args.cases.read_bytes()
    cases = json.loads(fixture_bytes.decode("utf-8-sig"))["cases"][: args.limit]
    validate_cases(cases, catalog)
    policy = catalog["policy"]
    from jev_router.sdk import JevTransport

    with JevTransport(
        get_api_key(settings), model=policy["jev_model"], timeout=policy["request_timeout_seconds"]
    ) as transport:
        report = evaluate_cases(cases, transport, catalog)
    report["run"] = {
        "utc": datetime.now(UTC).isoformat(),
        "jev_model": policy["jev_model"],
        "sdk_version": version("typesafe-sdk"),
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "catalog_sha256": hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest(),
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "routing_sha256": hashlib.sha256(
            (Path(__file__).parent / "jev_router" / "routing.py").read_bytes()
        ).hexdigest(),
        "context_source": "explicit authored fixture, not automatic session recovery",
    }
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    # Exit status gates authored expectations, not unannotated fields or model execution.
    return 1 if report["expectations_failed_cases"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        raise SystemExit(
            f"Evaluation stopped ({type(error).__name__}); no fabricated result."
        ) from None
