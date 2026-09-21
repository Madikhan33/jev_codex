"""Measure local overhead and question size, without credentials or API calls."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import timeit
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jev_router.catalog import load_catalog
from jev_router.questions import detection_questions, profile_questions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("iterations must be positive")
    catalog = load_catalog()
    detection = detection_questions(catalog)
    profiles = profile_questions(catalog, ["ui_layout", "backend_api"])
    durations = timeit.repeat(load_catalog, number=args.iterations, repeat=5)
    report = {
        "network_measured": False,
        "python": sys.version.split()[0],
        "iterations_per_sample": args.iterations,
        "samples": len(durations),
        "catalog_load_median_ms": round(statistics.median(durations) * 1000 / args.iterations, 3),
        "detection_questions": len(detection),
        "detection_json_bytes": len(json.dumps(detection, ensure_ascii=False).encode()),
        "two_category_profile_json_bytes": len(json.dumps(profiles, ensure_ascii=False).encode()),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
