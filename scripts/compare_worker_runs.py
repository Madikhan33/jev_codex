"""Compare recorded worker trials; this script never invokes a model or invents measurements."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import median
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jev_router.catalog import load_catalog

TASKS = Path(__file__).resolve().parents[1] / "tests" / "worker_tasks.json"
REQUIRED = {
    "task_id",
    "profile",
    "status",
    "checks_passed",
    "elapsed_ms",
    "tool_evidence",
    "repetition",
}


def compare_runs(rows: object, tasks_path: Path = TASKS) -> dict[str, Any]:
    tasks = {task["id"] for task in json.loads(tasks_path.read_text(encoding="utf-8-sig"))}
    profiles = load_catalog()["profiles"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("Input must be a nonempty list of actual execution trials")
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    seen = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or not REQUIRED <= row.keys()
            or row.keys() - REQUIRED - {"tokens", "cost"}
        ):
            raise ValueError("Trial has missing or unknown fields")
        if not isinstance(row["task_id"], str) or row["task_id"] not in tasks:
            raise ValueError("Unknown task_id")
        if not isinstance(row["profile"], str) or row["profile"] not in profiles:
            raise ValueError("Unknown profile")
        if row["status"] not in ("completed", "failed") or type(row["checks_passed"]) is not bool:
            raise ValueError("Invalid execution status/checks")
        if type(row["repetition"]) is not int or row["repetition"] < 1:
            raise ValueError("repetition must be a positive integer")
        evidence = row["tool_evidence"]
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("Concrete execution and acceptance-check evidence is required")
        for field in ("elapsed_ms", "tokens", "cost"):
            value = row.get(field)
            if value is None and field != "elapsed_ms":
                continue
            if value is None or type(value) not in (int, float):
                raise ValueError(f"Invalid {field} measurement")
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid {field} measurement")
            if field == "elapsed_ms" and value == 0:
                raise ValueError("elapsed_ms must be positive")
            if field == "tokens" and type(value) is not int:
                raise ValueError("tokens must be an integer")
        identity = (row["task_id"], row["profile"], row["repetition"])
        if identity in seen:
            raise ValueError("Duplicate task/profile/repetition")
        seen.add(identity)
        groups.setdefault(identity[:2], []).append(row)
    summary = []
    for (task, profile), trials in sorted(groups.items()):
        item = dict(
            task_id=task,
            profile=profile,
            attempts=len(trials),
            success_rate=sum(r["status"] == "completed" and r["checks_passed"] for r in trials)
            / len(trials),
            median_elapsed_ms=median(r["elapsed_ms"] for r in trials),
        )
        for field in ("tokens", "cost"):
            measurements = [r.get(field) for r in trials]
            item[f"median_{field}"] = (
                median([v for v in measurements if v is not None])
                if all(v is not None for v in measurements)
                else None
            )
        summary.append(item)
    return {
        "groups": summary,
        "actual_model_verified": False,
        "limitations": "Profiles are caller-reported. Evidence references are required but not independently verified. "
        "No winner is ranked. Use identical isolated fixtures, checks, budgets and repetitions; "
        "missing token/cost measurements remain null. Cost must use one currency across trials.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = compare_runs(json.loads(args.input.read_text(encoding="utf-8-sig")))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
