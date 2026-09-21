"""CLI integration for task capsules and reported agent lifecycle events."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .settings import default_settings_path
from .storage import atomic_write, json_bytes


def read_object() -> dict[str, Any]:
    raw = sys.stdin.read(24001)
    if len(raw) > 24000:
        raise ValueError("Session input exceeds 24000 characters")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Session input must be a JSON object")
    return value


def session_command(args: argparse.Namespace, settings: dict[str, Any]) -> dict[str, Any]:
    from .session_state import SessionStore, render_context

    action = args.action
    if action in {"enable", "disable"}:
        settings["context_enabled"] = action == "enable"
        target = args.config or default_settings_path()
        atomic_write(target, json_bytes(settings))
        return {
            "context_enabled": settings["context_enabled"],
            "data_sent": "Current prompt and saved task capsule; never transcripts or repository files",
        }
    if not args.session_id or not args.project:
        raise ValueError("Use session_id and project from the actual hook metadata")
    if action in {"research", "message"}:
        from .teamwork import plan_message, plan_research

        return (plan_research if action == "research" else plan_message)(read_object())
    root = Path(settings["state_dir"])
    store = SessionStore(root, args.session_id, args.project)
    if action == "show":
        latest = store.read(include_stale=True)
        return {"capsule": latest, "fresh": store.read() is not None}
    if action in {"save", "clear"}:
        if not settings["context_enabled"]:
            raise ValueError("Context mode is disabled")
        if args.expected_revision is None:
            raise ValueError("An expected revision is required")
        capsule = (
            store.update(args.expected_revision, read_object())
            if action == "save"
            else store.reset(args.expected_revision)
        )
        return {
            "revision": capsule["revision"],
            "task_id": capsule["task_id"],
            "status": capsule["status"],
        }
    if action == "route":
        if not settings["context_enabled"]:
            raise ValueError("Context mode is disabled")
        fresh_capsule = store.read()
        if fresh_capsule is None or fresh_capsule["status"] == "cancelled":
            raise ValueError("Save a fresh resolved task capsule first")
        data = read_object()
        prompt = data.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("A prompt is required")
        from .catalog import load_catalog
        from .routing import classify, compact_route
        from .sdk import JevTransport
        from .settings import catalog_directory, get_api_key

        catalog = load_catalog(catalog_directory(settings))
        context = render_context(fresh_capsule)
        policy = catalog["policy"]
        if len(prompt) > policy["max_prompt_chars"] or len(context) > policy["max_context_chars"]:
            raise ValueError("Input exceeds configured limits")
        if not args.turn_id or not store.claim_reroute(args.turn_id):
            raise ValueError("Explicit rerouting is limited to once per turn")
        with JevTransport(
            get_api_key(settings),
            model=policy["jev_model"],
            timeout=policy["request_timeout_seconds"],
        ) as transport:
            result = classify(prompt, transport, context=context, catalog=catalog)
        return {
            "route": compact_route(result),
            "context_revision": fresh_capsule["revision"],
            "usage": result["usage"],
        }
    from .dispatch import DispatchJournal, plan_assignment

    journal = DispatchJournal(root, args.session_id, args.project)
    if action == "trace":
        return {
            "events": journal.read(),
            "assignments": journal.assignments(),
            "evidence_source": "caller_reported",
            "actual_model_verified": False,
        }
    if action == "record":
        return journal.record(read_object())
    if action == "plan":
        from .catalog import load_catalog
        from .settings import catalog_directory

        data = read_object()
        return plan_assignment(
            data["group"],
            load_catalog(catalog_directory(settings)),
            data["available_agents"],
            existing=data.get("existing"),
            evidence=data.get("evidence"),
        )
    raise ValueError("Unknown session action")
