"""Local planning helpers. They neither browse nor deliver agent messages.

Inputs describe observations made by the lead, not trusted runtime telemetry.
Keep semantic decisions with Codex and enforce small, explicit tool contracts here.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .storage import json_bytes


def _object(data: Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("Expected an object containing only documented fields")
    return data


def _text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} needs 1..{limit} characters")
    return value.strip()


def _flag(data: dict[str, Any], field: str, default: bool = False) -> bool:
    value = data.get(field, default)
    if type(value) is not bool:
        raise ValueError(f"{field} must be boolean")
    return value


def plan_research(data: dict[str, Any]) -> dict[str, Any]:
    """Choose the source for one knowledge gap without an extra classifier call."""
    _object(
        data,
        {
            "question",
            "gap",
            "explicit_search",
            "current",
            "evidence_sufficient",
            "web_allowed",
            "web_available",
            "attempts",
        },
    )
    question = _text(data.get("question"), "question", 1000)
    gap = data.get("gap")
    if gap not in {"none", "repository", "external", "requirements"}:
        raise ValueError("gap must be none, repository, external or requirements")
    flags = {
        name: _flag(data, name)
        for name in ("explicit_search", "current", "evidence_sufficient", "web_available")
    }
    allowed = _flag(data, "web_allowed", True)
    attempts = data.get("attempts", 0)
    if type(attempts) is not int or not 0 <= attempts <= 2:
        raise ValueError("attempts must be an integer from 0 to 2")
    explicit_pending = flags["explicit_search"] and attempts == 0
    # Product decisions and private state cannot be recovered from public search.
    # An explicit public search is honored, but leaves those local gaps outstanding.
    if gap == "requirements" and not explicit_pending:
        action, reason = "ask_user", "A missing user decision is not a public fact"
    elif gap == "repository" and not explicit_pending:
        action, reason = "inspect_local", "Inspect the relevant code, tests or local documentation"
    elif explicit_pending or (
        (flags["current"] or gap == "external") and not flags["evidence_sufficient"]
    ):
        if not allowed:
            action, reason = "report_gap", "Web use is forbidden for this task"
        elif not flags["web_available"]:
            action, reason = "report_gap", "No web tool is available"
        elif attempts >= 2:
            action, reason = "report_gap", "Two focused research rounds did not resolve the gap"
        else:
            action, reason = "search_web", "Verify the external fact using primary sources"
    else:
        action, reason = "proceed", "Available evidence is sufficient for this step"
    return {
        "action": action,
        "reason": reason,
        "question": question,
        "remaining_rounds": max(0, 2 - attempts),
        "local_followup": {"repository": "inspect_local", "requirements": "ask_user"}.get(gap),
        "evidence_source": "caller_reported",
        "executed": False,
    }


def plan_message(data: dict[str, Any]) -> dict[str, Any]:
    """Validate one compact peer message against a caller-supplied live roster.

    Return arguments to use with the host's messaging tool, never a delivery receipt.
    Previous IDs are supplied by the lead's task ledger; this helper is stateless.
    """
    _object(
        data,
        {
            "task_id",
            "sender",
            "recipient",
            "kind",
            "body",
            "evidence",
            "roster",
            "peer_messaging",
            "previous_ids",
        },
    )
    task_id = _text(data.get("task_id"), "task_id", 200)
    sender = _text(data.get("sender"), "sender", 200)
    recipient = _text(data.get("recipient"), "recipient", 200)
    if sender == recipient:
        raise ValueError("A peer message needs a different recipient")
    kind = data.get("kind")
    if kind not in {"question", "answer", "contract", "blocker", "result"}:
        raise ValueError("Unknown message kind")
    body = _text(data.get("body"), "body", 1200)
    evidence = data.get("evidence", [])
    if not isinstance(evidence, list) or len(evidence) > 4:
        raise ValueError("evidence needs at most four short references")
    refs = [_text(ref, "evidence", 300) for ref in evidence]
    roster = data.get("roster")
    if not isinstance(roster, dict) or not 1 <= len(roster) <= 32:
        raise ValueError("roster must contain actual same-team agent IDs and statuses")
    for agent, status in roster.items():
        _text(agent, "agent ID", 200)
        if status not in {"running", "idle", "stopped"}:
            raise ValueError("Unknown roster status")
    if sender not in roster or recipient not in roster or roster[sender] != "running":
        raise ValueError("Sender must be running and both agents must belong to the team")
    previous = data.get("previous_ids", [])
    if not isinstance(previous, list) or len(previous) > 100:
        raise ValueError("previous_ids must contain at most 100 IDs")
    for item in previous:
        _text(item, "previous ID", 64)
    direct = _flag(data, "peer_messaging")
    payload = dict(
        task_id=task_id, sender=sender, recipient=recipient, kind=kind, body=body, evidence=refs
    )
    message_id = hashlib.sha256(json_bytes(payload)).hexdigest()
    if message_id in previous:
        action = "skip_duplicate"
    elif roster[recipient] == "stopped":
        action = "report_unavailable"
    elif roster[recipient] == "idle":
        action = "request_lead_followup"
    else:
        action = "send_peer" if direct else "relay_via_lead"
    text = f"[{task_id}] {kind}: {body}"
    if refs:
        text += "\nEvidence: " + "; ".join(refs)
    return {
        "action": action,
        "message_id": message_id,
        "target": recipient,
        "message": text,
        "notify_lead": kind in {"contract", "blocker"},
        "characters": len(text),
        "delivered": False,
        "evidence_source": "caller_reported",
    }
