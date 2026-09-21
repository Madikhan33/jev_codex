"""Fail-open UserPromptSubmit hook; stdin JSON, stdout JSON only."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .settings import catalog_directory, get_api_key, read_settings

MAX_EVENT_BYTES = 256 * 1024
CONTROL_COMMANDS = {"/hooks", "/skills", "/model", "/quit", "/exit", "/clear", "/help", "/status"}


def hook_result(
    event: dict[str, Any], settings: dict[str, Any], *, transport_factory: Any = None
) -> dict[str, Any] | None:
    """Route only submitted text; all other event fields remain local and unread."""
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

    # Neither transcript_path, cwd, nor any repository file is opened or forwarded.
    catalog = load_catalog(catalog_directory(settings))
    policy = catalog["policy"]
    if len(prompt) > policy["max_prompt_chars"]:
        return {
            "systemMessage": "Jev Router skipped: input exceeds the configured limit. The original prompt is unchanged."
        }
    if transport_factory is None:
        from .sdk import JevTransport

        transport_factory = JevTransport
    with transport_factory(
        get_api_key(settings), model=policy["jev_model"], timeout=policy["request_timeout_seconds"]
    ) as transport:
        result = classify(prompt, transport, catalog=catalog)
    payload = compact_route(result)
    context = (
        "JEV_ROUTE_V3. Apply $jev-router. Advisory labels, not permission to edit or discard requirements. "
        "The original request remains authoritative. Model availability is unverified. "
        "No parent-model change has been applied.\n"
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
        result = hook_result(event, read_settings(config))
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
