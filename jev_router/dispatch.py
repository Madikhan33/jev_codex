"""Plan available assignments and validate reported tool outcomes without spawning."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .contracts import Catalog
from .storage import atomic_write, json_bytes

EVIDENCE_REASONS = {"new_constraints", "failed_check", "blocker"}
STATUSES = {"selected", "dispatch_accepted", "dispatch_failed", "completed", "blocked", "stopped"}
TRANSITIONS = {
    "selected": {"selected", "dispatch_accepted", "dispatch_failed", "blocked", "stopped"},
    "dispatch_accepted": {"completed", "blocked", "stopped"},
    "blocked": {"blocked", "dispatch_accepted", "completed", "stopped"},
    "dispatch_failed": {"selected", "stopped"},
    "completed": {"selected"},
    "stopped": {"selected"},
}


def _text(value: Any, name: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must contain 1..{limit} characters")
    return value.strip()


def validate_evidence(evidence: Any) -> list[str]:
    """Accept bounded reason:detail records; free-form dissatisfaction is not evidence."""
    if not isinstance(evidence, list) or len(evidence) > 8:
        raise ValueError("evidence must be a list of at most 8 reason:detail strings")
    result = []
    for item in evidence:
        item = _text(item, "evidence", 1000)
        reason, separator, detail = item.partition(":")
        if not separator or reason not in EVIDENCE_REASONS or len(detail.strip()) < 12:
            raise ValueError("evidence needs new_constraints, failed_check or blocker and detail")
        result.append(item)
    return result


def plan_assignment(
    group: dict[str, Any],
    catalog: Catalog,
    available_agents: list[str],
    existing: dict[str, Any] | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    """Return a recommendation, never a claim that a worker has actually started.

    Existing means the same task's assignment. Callers must not pass an unrelated
    task. Evidence is a lead's explicit report, not independently verified telemetry.
    """
    reasons = validate_evidence([] if evidence is None else evidence)
    if not isinstance(available_agents, list) or any(
        not isinstance(agent, str) or not agent.strip() for agent in available_agents
    ):
        raise ValueError("available_agents must be a list of actual agent type names")
    owner = _text(group.get("owner"), "owner", 100)
    source = group.get("selection_source", "jev")
    if source not in {"jev", "lead"}:
        raise ValueError("selection_source must be jev or lead")
    if source == "lead":
        _text(group.get("selection_reason"), "selection_reason")
    profile = group.get("profile")
    result: dict[str, Any] = {
        "status": "recommendation",
        "owner": owner,
        "recommended_profile": profile,
        "profile": None,
        "agent_type": None,
        "model": None,
        "effort": None,
        "selection_source": source,
        "actual_model_verified": False,
        "evidence": reasons,
        "retained": False,
    }
    if profile is None:
        if existing is None:
            result["status"] = "needs_context"
            return result
        # A short correction need not discard an already established same-task
        # assignment. Keep the null recommendation visible in the result.
        profile = existing.get("profile")
    if profile not in catalog["profiles"]:
        raise ValueError("Unknown requested profile")
    if existing:
        old_profile = existing.get("profile")
        if old_profile not in catalog["profiles"]:
            raise ValueError("Unknown existing profile")
        if existing.get("agent_type") != f"jev_{old_profile}":
            raise ValueError("Existing agent does not match its profile")
        unfinished = existing.get("status") in {"selected", "dispatch_accepted", "blocked"}
        if owner != existing.get("owner"):
            if unfinished:
                result.update(
                    status="ownership_change_blocked", previous_owner=existing.get("owner")
                )
                return result
            # A stopped/completed assignment permits an explicit ownership transfer.
            # It is a new selection, not retention of the previous worker.
            existing = None
    if existing:
        old_profile = existing["profile"]
        stronger = catalog["profiles"][profile]["rank"] > catalog["profiles"][old_profile]["rank"]
        active = existing.get("status") in {"selected", "dispatch_accepted", "blocked"}
        if not stronger or not reasons or active:
            profile = old_profile
            result.update(
                owner=existing["owner"],
                retained=True,
                agent_id=existing.get("agent_id"),
                selection_source=existing.get("selection_source", "jev"),
            )
            if stronger:
                result["escalation_blocked"] = "stop_existing_first" if active else "needs_evidence"
    agent_type = f"jev_{profile}"
    if agent_type not in available_agents:
        result.update(status="unavailable", unavailable_agent_type=agent_type)
        return result
    configured = catalog["profiles"][profile]
    if profile == "sol_xhigh" and not result["retained"] and not reasons:
        result.update(
            status="needs_evidence",
            escalation_blocked="Explain the hard constraint, failed check or blocker requiring Sol xhigh",
        )
        return result
    result.update(
        profile=profile,
        agent_type=agent_type,
        model=configured["model"],
        effort=configured["effort"],
    )
    return result


def validate_dispatch_event(event: dict[str, Any]) -> dict[str, Any]:
    """Validate a lead's report; never label reported model identity as verified."""
    allowed = {
        "task_id",
        "agent_type",
        "selection_source",
        "status",
        "agent_id",
        "tool_evidence",
        "verification",
        "evidence",
        "actual_model_verified",
        "evidence_source",
        "profile",
        "owner",
    }
    if not isinstance(event, dict) or set(event) - allowed:
        raise ValueError("Unknown dispatch event fields")
    result = dict(event)
    for field in ("tool_evidence", "verification", "profile", "owner"):
        if field in result:
            result[field] = _text(
                result[field], field, 2000 if field in {"tool_evidence", "verification"} else 100
            )
    status = result.get("status")
    if status not in STATUSES:
        raise ValueError("Unknown dispatch status")
    for field in ("task_id", "agent_type"):
        result[field] = _text(result.get(field), field, 200)
    if result.get("selection_source") not in {"jev", "lead"}:
        raise ValueError("selection_source must be jev or lead")
    if result.get("actual_model_verified", False) is not False:
        raise ValueError("Actual model telemetry is not available")
    result["actual_model_verified"] = False
    result["evidence_source"] = "caller_reported"
    result["evidence"] = validate_evidence(result.get("evidence", []))
    if result.get("agent_id") is not None:
        result["agent_id"] = _text(result["agent_id"], "agent_id", 200)
    if status in {"dispatch_accepted", "completed"}:
        _text(result.get("agent_id"), "agent_id", 200)
        _text(result.get("tool_evidence"), "tool_evidence")
    if status == "completed":
        _text(result.get("verification"), "verification")
    if status == "dispatch_failed" and result.get("agent_id") is not None:
        raise ValueError("A failed dispatch cannot claim an accepted agent")
    return result


def advance_dispatch(previous: dict[str, Any] | None, event: dict[str, Any]) -> dict[str, Any]:
    """Keep an accepted or blocked writer's identity until explicitly stopped."""
    current = validate_dispatch_event(event)
    if previous is None:
        if current["status"] != "selected":
            raise ValueError("A task must start with selection")
        return current
    previous = validate_dispatch_event(previous)
    if current["task_id"] != previous["task_id"]:
        raise ValueError("Cannot transition between different tasks")
    if current["status"] not in TRANSITIONS[previous["status"]]:
        raise ValueError("Illegal dispatch transition")
    if previous["status"] not in {"completed", "stopped", "dispatch_failed"}:
        for field in ("profile", "owner"):
            if field in previous:
                if field in current and current[field] != previous[field]:
                    raise ValueError("Stop the previous assignment before changing ownership")
                current[field] = previous[field]
        if current["selection_source"] != previous["selection_source"]:
            raise ValueError("Selection provenance cannot change during an assignment")
        if current["agent_type"] != previous["agent_type"]:
            raise ValueError("Stop the previous assignment before replacing it")
        if previous.get("agent_id") is not None:
            if current.get("agent_id") != previous["agent_id"]:
                raise ValueError("An accepted or blocked writer retains ownership")
    return current


class DispatchJournal:
    """Session-scoped bounded reports with exclusive writes and persistent ownership."""

    def __init__(self, root: Path, session_id: str, project: str) -> None:
        _text(session_id, "session_id", 500)
        _text(project, "project", 2000)
        canonical_project = os.path.normcase(str(Path(project).resolve()))
        namespace = hashlib.sha256(json_bytes([session_id, canonical_project])).hexdigest()
        self.root = root.absolute()
        self.path = self.root / f"{namespace}.dispatch.json"
        self.lock = self.root / f"{namespace}.dispatch.lock"

    def _check_paths(self) -> None:
        for path in (self.root, *self.root.parents, self.path, self.lock):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ValueError("Refusing symlink in dispatch journal path")

    def _load(self) -> dict[str, Any]:
        self._check_paths()
        if not self.path.exists():
            return {"events": [], "tasks": {}}
        if self.path.stat().st_size > 2_000_000:
            raise ValueError("Dispatch journal exceeds size limit")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            raise ValueError("Malformed dispatch journal")
        if not isinstance(data.get("tasks"), dict) or len(data["tasks"]) > 100:
            raise ValueError("Malformed dispatch task state")
        if len(data["events"]) > 100:
            raise ValueError("Too many dispatch events")
        data["events"] = [validate_dispatch_event(event) for event in data["events"]]
        for task_id, event in data["tasks"].items():
            data["tasks"][task_id] = validate_dispatch_event(event)
            if event["task_id"] != task_id:
                raise ValueError("Dispatch task key does not match its event")
        return data

    def read(self) -> list[dict[str, Any]]:
        return [validate_dispatch_event(event) for event in self._load()["events"][-100:]]

    def assignments(self) -> dict[str, Any]:
        """Retain current ownership even when its older events leave the history window."""
        return dict(self._load()["tasks"])

    def record(self, event: dict[str, Any]) -> dict[str, Any]:
        self._check_paths()
        self.root.mkdir(parents=True, exist_ok=True)
        from .locking import file_lock

        with file_lock(self.lock):
            data = self._load()
            current = validate_dispatch_event(event)
            task_id = current["task_id"]
            current = advance_dispatch(data["tasks"].get(task_id), current)
            if task_id not in data["tasks"] and len(data["tasks"]) >= 100:
                finished = next(
                    (
                        key
                        for key, value in data["tasks"].items()
                        if value["status"] in {"completed", "stopped"}
                    ),
                    None,
                )
                if finished is None:
                    raise ValueError("Too many unfinished assignments")
                del data["tasks"][finished]
            data["tasks"][task_id] = current
            data["events"] = [*data["events"], current][-100:]
            content = json_bytes(data)
            if len(content) > 2_000_000:
                raise ValueError("Dispatch journal exceeds size limit")
            atomic_write(self.path, content)
            return current
