"""Opt-in live evaluation of relation detection followed by contextual routing."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval import validate_cases
from jev_router.catalog import load_catalog
from jev_router.contextual import route_with_context
from jev_router.routing import classify, compact_route
from jev_router.sdk import JevTransport
from jev_router.settings import get_api_key, read_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "tests/context_cases.json",
    )
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--id", action="append", default=[])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("limit must be positive")
    raw = args.cases.read_bytes()
    cases = json.loads(raw.decode("utf-8-sig"))["cases"]
    if set(args.id) - {case["id"] for case in cases}:
        parser.error("unknown case id")
    cases = [case for case in cases if not args.id or case["id"] in args.id][: args.limit]
    catalog = load_catalog(args.catalog)
    validate_cases(cases, catalog)
    rows = []
    with JevTransport(
        get_api_key(read_settings(args.config)),
        model=catalog["policy"]["jev_model"],
        timeout=catalog["policy"]["request_timeout_seconds"],
    ) as transport:
        for case in cases:
            snapshot = {
                "task_id": case["id"],
                "objective": case.get("context", ""),
                "constraints": [],
                "completed": [],
                "pending": [],
                "facts": [],
                "open_questions": [],
                "owner": None,
                "status": "active",
                "revision": 1,
            }
            started = time.perf_counter()
            try:
                if case.get("context"):
                    outcome = route_with_context(
                        case["prompt"], transport, catalog, snapshot, directory=args.catalog
                    )
                    result = outcome["result"]
                    relation, used = outcome["relation"], outcome["context_used"]
                else:
                    result = classify(case["prompt"], transport, catalog=catalog)
                    relation, used = None, False
                profiles = (
                    {route["work_type"]: route["profile"] for route in result["routes"]}
                    if result
                    else {}
                )
                expectations = case.get("acceptable_profiles", {})
                rows.append(
                    {
                        "id": case["id"],
                        "relation": relation,
                        "context_used": used,
                        "route": compact_route(result) if result else None,
                        "profiles": profiles,
                        "profile_expectations_match": all(
                            key in profiles and profiles[key] in values
                            for key, values in expectations.items()
                        )
                        if expectations
                        else None,
                        "error_type": None,
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                )
            except Exception as exc:
                rows.append({"id": case["id"], "error_type": type(exc).__name__})
    context_path = (
        args.catalog or Path(__file__).resolve().parents[1] / "jev_router/prompts"
    ) / "context.toml"
    report = {
        "utc": datetime.now(UTC).isoformat(),
        "sdk_version": version("typesafe-sdk"),
        "fixture_sha256": hashlib.sha256(raw).hexdigest(),
        "context_prompt_sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
        "model": catalog["policy"]["jev_model"],
        "context_source": "synthetic explicit snapshots, not automatic transcript extraction",
        "cases": rows,
        "parent_model_changed": False,
        "model_execution_measured": False,
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "cases": len(rows),
                "profile_expectations_matched": sum(
                    row.get("profile_expectations_match") is True for row in rows
                ),
                "errors": sum(row["error_type"] is not None for row in rows),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(f"Context evaluation stopped ({type(error).__name__}).") from None
