"""Opt-in paid Jev evaluation. Labeled examples are expectations, not predictions."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from jev_router.catalog import load_catalog
from jev_router.contracts import Catalog
from jev_router.routing import Request, classify
from jev_router.settings import catalog_directory, get_api_key, read_settings


def evaluate_cases(
    cases: list[dict[str, Any]], request: Request, catalog: Catalog
) -> dict[str, Any]:
    """Measure categories and annotated intent/profile labels using one transport."""
    if not cases:
        raise ValueError("At least one labeled case is required")
    true_positives = false_positives = false_negatives = exact_matches = calls = 0
    profile_correct = profile_total = intent_correct = intent_total = 0
    details = []
    for case in cases:
        started = time.perf_counter()
        result = classify(case["prompt"], request, context=case.get("context", ""), catalog=catalog)
        elapsed_ms = (time.perf_counter() - started) * 1000
        expected = set(case["categories"])
        predicted = {route["work_type"] for route in result["routes"]}
        true_positives += len(expected & predicted)
        false_positives += len(predicted - expected)
        false_negatives += len(expected - predicted)
        exact_matches += predicted == expected
        calls += result["usage"].get("classification_calls", 0)

        profiles = {route["work_type"]: route["profile"] for route in result["routes"]}
        profile_errors = []
        for category, acceptable in case.get("acceptable_profiles", {}).items():
            profile_total += 1
            if profiles.get(category) in acceptable:
                profile_correct += 1
            else:
                profile_errors.append(category)
        intent_matches = None
        if "expected_intent" in case:
            intent_total += 1
            intent_matches = result["intent"]["value"] == case["expected_intent"]
            intent_correct += intent_matches
        details.append(
            {
                "id": case["id"],
                "missing": sorted(expected - predicted),
                "extra": sorted(predicted - expected),
                "profile_errors": profile_errors,
                "intent_matches": intent_matches,
                "review_required": result["review_required"],
                "elapsed_ms": round(elapsed_ms, 2),
                "usage": result["usage"],
            }
        )

    predicted_total = true_positives + false_positives
    expected_total = true_positives + false_negatives
    return {
        "cases": len(cases),
        "micro_precision": true_positives / predicted_total if predicted_total else None,
        "micro_recall": true_positives / expected_total if expected_total else None,
        "exact_match": exact_matches / len(cases),
        "classification_calls": calls,
        "profile_accuracy_measured": profile_total > 0,
        "profile_cases": profile_total,
        "profile_accuracy": profile_correct / profile_total if profile_total else None,
        "intent_cases": intent_total,
        "intent_accuracy": intent_correct / intent_total if intent_total else None,
        "codex_quality_measured": False,
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run paid Jev calls against labeled examples")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("limit must be positive")
    settings = read_settings(args.config)
    catalog = load_catalog(catalog_directory(settings))
    fixture_path = Path(__file__).parent / "tests" / "cases.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))["cases"][: args.limit]
    policy = catalog["policy"]
    from jev_router.sdk import JevTransport

    with JevTransport(
        get_api_key(settings),
        model=policy["jev_model"],
        timeout=policy["request_timeout_seconds"],
    ) as transport:
        report = evaluate_cases(cases, transport, catalog)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        raise SystemExit(
            f"Evaluation stopped ({type(error).__name__}); no fabricated result."
        ) from None
