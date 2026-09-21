"""Fail-open UserPromptSubmit hook; stdin JSON, stdout JSON only."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .settings import catalog_directory, default_settings_path, get_api_key, read_settings

MAX_EVENT_BYTES = 256 * 1024
CONTROL_COMMANDS = {"/hooks", "/skills", "/model", "/quit", "/exit", "/clear", "/help", "/status"}


def hook_result(
    event: dict[str, Any],
    settings: dict[str, Any],
    *,
    transport_factory: Any = None,
    config_path: Path | None = None,
) -> dict[str, Any] | None:
    """Route text and default-enabled task capsules; never open transcripts or project files."""
    if os.environ.get("JEV_ROUTER_DISABLE") == "1" or not settings.get("enabled", True):
        return None
    if event.get("hook_event_name") != "UserPromptSubmit":
        return None
    prompt = event.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    if prompt.strip().split(maxsplit=1)[0] in CONTROL_COMMANDS:
        return None
    # Disabled and control-command paths need neither catalog parsing nor SDK imports.
    from .catalog import load_catalog
    from .routing import classify, compact_route

    # cwd/session_id only partition local state; neither is sent to TypeSafe.
    catalog = load_catalog(catalog_directory(settings))
    policy = catalog["policy"]
    if len(prompt) > policy["max_prompt_chars"]:
        return {
            "systemMessage": "Jev Router skipped: input exceeds the configured limit. The original prompt is unchanged."
        }
    if transport_factory is None:
        from .sdk import JevTransport

        transport_factory = JevTransport
    session = None
    capsule = None
    if settings.get("context_enabled", False):
        from .session_state import SessionStore

        session_id, project = event.get("session_id"), event.get("cwd")
        if isinstance(session_id, str) and session_id and isinstance(project, str) and project:
            store = SessionStore(Path(settings["state_dir"]), session_id, project)
            latest = store.read(include_stale=True)
            capsule = store.read()
            session = {
                "session_id": session_id,
                "project": project,
                "turn_id": event.get("turn_id"),
                "revision": latest["revision"] if latest else 0,
                "state": "fresh" if capsule else "stale" if latest else "missing",
            }
            if capsule and capsule["status"] == "cancelled":
                session["state"] = "cancelled"
                capsule = None
            entry = Path(__file__).parent.parent / "entry.py"
            if not entry.is_file():
                entry = Path(__file__).parent.parent / "run.py"
            session["runtime"] = {
                "python": sys.executable,
                "entry": str(entry),
                "config": str((config_path or default_settings_path()).resolve()),
            }
    context_route = None
    with transport_factory(
        get_api_key(settings), model=policy["jev_model"], timeout=policy["request_timeout_seconds"]
    ) as transport:
        if capsule:
            from .contextual import route_with_context

            context_route = route_with_context(
                prompt, transport, catalog, capsule, directory=catalog_directory(settings)
            )
            result = context_route["result"]
        else:
            result = classify(prompt, transport, catalog=catalog)
    payload = (
        compact_route(result)
        if result
        else {
            "v": 3,
            "intent": "unclear",
            "strategy": "resolve_scope",
            "review_required": True,
            "groups": [],
            "uncertain": [],
            "uncovered": False,
            "capabilities_verified": False,
        }
    )
    if session:
        payload["session"] = session
    if context_route:
        payload["context"] = {
            key: context_route[key]
            for key in (
                "relation",
                "context_used",
                "context_revision",
                "task_id",
                "additional_relation_calls",
            )
        }
    context = (
        "JEV_ROUTE_V3. Apply $jev-router. Advisory labels, not permission to edit or discard requirements. "
        "The original request remains authoritative. Model availability is unverified. "
        "No parent-model change has been applied. "
        "When session metadata is present, maintain its task capsule via the skill's session workflow.\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )
    return {
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}
    }


def main(config: Path | None = None) -> int:
    """Emit hook JSON only; any failure leaves the original Codex prompt intact."""
    try:
        raw = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
        if len(raw) > MAX_EVENT_BYTES:
            raise ValueError("Hook event exceeds input limit")
        event = json.loads(raw.decode("utf-8"))
        if not isinstance(event, dict):
            raise ValueError("Hook event must be an object")
        result = hook_result(event, read_settings(config), config_path=config)
    except Exception:
        # SDK exceptions can contain input, authorization data or response bodies.
        # Their raw messages never go into logs or Codex's developer context.
        result = {
            "systemMessage": "Jev Router unavailable; continuing with the original prompt and current model. Run the router doctor command for local setup checks."
        }
    if result is not None:
        # ASCII escaping also works with Windows consoles using a legacy code page.
        print(json.dumps(result, ensure_ascii=True))
    return 0
