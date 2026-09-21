"""Bounded task capsules isolated by session and project; never store transcripts."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .storage import atomic_write, json_bytes

CONTENT_FIELDS = {
    "task_id",
    "objective",
    "constraints",
    "completed",
    "pending",
    "facts",
    "open_questions",
    "owner",
    "status",
}
OPTIONAL_FIELDS = {"turn_id"}
MAX_CONTEXT = 6000


class StateError(ValueError):
    """Invalid or unsafe capsule storage."""


class StaleRevisionError(StateError):
    """Another writer changed the capsule since it was read."""


def _text(value: object, name: str, limit: int = 2000) -> None:
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise StateError(f"Invalid {name}")


def render_context(capsule: dict[str, Any]) -> str:
    """Render only task content, excluding storage metadata."""
    return json.dumps(
        {key: capsule[key] for key in sorted(CONTENT_FIELDS | OPTIONAL_FIELDS) if key in capsule},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    if not CONTENT_FIELDS <= set(payload) or set(payload) - CONTENT_FIELDS - OPTIONAL_FIELDS:
        raise StateError("Capsule must contain exactly the documented content fields")
    if "turn_id" in payload:
        _text(payload["turn_id"], "turn_id", 1000)
    for field in ("task_id", "objective"):
        _text(payload[field], field)
    if not payload["task_id"]:
        raise StateError("task_id cannot be empty")
    if payload["owner"] is not None:
        _text(payload["owner"], "owner", 200)
    if payload["status"] not in ("active", "completed", "cancelled"):
        raise StateError("Invalid status")
    for field in ("constraints", "completed", "pending", "open_questions"):
        values = payload[field]
        if not isinstance(values, list) or len(values) > 40:
            raise StateError(f"Invalid {field}")
        for value in values:
            _text(value, field)
    facts = payload["facts"]
    if not isinstance(facts, list) or len(facts) > 40:
        raise StateError("Invalid facts")
    for fact in facts:
        if not isinstance(fact, dict) or set(fact) != {"text", "source"}:
            raise StateError("Invalid fact")
        _text(fact["text"], "fact text")
        if fact["source"] not in ("user", "observed", "assumption"):
            raise StateError("Invalid fact source")
    rendered = render_context(payload)
    if len(rendered) > MAX_CONTEXT:
        raise StateError("Capsule exceeds 6000 characters")
    result: dict[str, Any] = json.loads(rendered)
    return result


def _refuse_links(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or (
            hasattr(candidate, "is_junction") and candidate.is_junction()
        ):
            raise StateError("Session storage cannot use symlinks or junctions")


class SessionStore:
    def __init__(
        self,
        root: Path,
        session_id: str,
        project: str,
        *,
        max_age_seconds: float = 86400,
        lock_timeout: float = 2,
    ) -> None:
        _text(session_id, "session_id", 1000)
        if not session_id or not project or max_age_seconds <= 0 or lock_timeout < 0:
            raise StateError("Invalid session storage configuration")
        self.root = root.absolute()
        _refuse_links(self.root)
        canonical_project = os.path.normcase(str(Path(project).resolve()))
        identity = json.dumps([session_id, canonical_project]).encode("utf-8")
        key = hashlib.sha256(identity).hexdigest()
        self.path = self.root / f"{key}.json"
        self.lock_path = self.root / f"{key}.lock"
        self.max_age_seconds = max_age_seconds
        self.lock_timeout = lock_timeout

    def read(self, *, include_stale: bool = False) -> dict[str, Any] | None:
        _refuse_links(self.path)
        try:
            if self.path.stat().st_size > 50000:
                raise StateError("Oversized state file")
            value = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return None
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise StateError("Corrupt session state") from exc
        if not isinstance(value, dict) or (
            not CONTENT_FIELDS | {"revision", "updated_at"} <= set(value)
            or set(value) - CONTENT_FIELDS - OPTIONAL_FIELDS - {"revision", "updated_at"}
        ):
            raise StateError("Invalid stored capsule")
        if type(value["revision"]) is not int or value["revision"] < 1:
            raise StateError("Invalid stored revision")
        stamp = value["updated_at"]
        if type(stamp) not in (int, float) or not 0 <= stamp <= time.time() + 60:
            raise StateError("Invalid stored timestamp")
        _validate({key: value[key] for key in CONTENT_FIELDS | OPTIONAL_FIELDS if key in value})
        if not include_stale and time.time() - stamp > self.max_age_seconds:
            return None
        return value

    @contextmanager
    def _lock(self) -> Iterator[None]:
        from .locking import file_lock

        _refuse_links(self.root)
        try:
            with file_lock(self.lock_path, self.lock_timeout):
                yield
        except TimeoutError as exc:
            raise StateError("Session state is locked; retry later") from exc

    def update(self, expected_revision: int, payload: dict[str, Any]) -> dict[str, Any]:
        if type(expected_revision) is not int or expected_revision < 0:
            raise StateError("Invalid expected revision")
        content = _validate(payload)
        with self._lock():
            previous = self.read(include_stale=True)
            revision = previous["revision"] if previous else 0
            if revision != expected_revision:
                raise StaleRevisionError(f"Expected revision {expected_revision}; found {revision}")
            content.update(revision=revision + 1, updated_at=time.time())
            atomic_write(self.path, json_bytes(content))
        return content

    def reset(self, expected_revision: int) -> dict[str, Any]:
        """Clear task context with a revisioned tombstone, preserving CAS semantics."""
        return self.update(
            expected_revision,
            {
                "task_id": "reset",
                "objective": "",
                "constraints": [],
                "completed": [],
                "pending": [],
                "facts": [],
                "open_questions": [],
                "owner": None,
                "status": "cancelled",
            },
        )

    def claim_reroute(self, turn_id: str) -> bool:
        """Atomically allow one extra classification per turn, keeping 32 recent IDs."""
        _text(turn_id, "turn_id", 1000)
        if not turn_id:
            raise StateError("turn_id cannot be empty")
        marker = hashlib.sha256(turn_id.encode("utf-8")).hexdigest()
        guard_path = self.path.with_suffix(".turns.json")
        with self._lock():
            _refuse_links(guard_path)
            try:
                if guard_path.stat().st_size > 5000:
                    raise StateError("Oversized reroute guard")
                turns = json.loads(guard_path.read_text(encoding="utf-8-sig"))
            except FileNotFoundError:
                turns = []
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise StateError("Corrupt reroute guard") from exc
            if (
                not isinstance(turns, list)
                or len(turns) > 32
                or any(not isinstance(item, str) or len(item) != 64 for item in turns)
            ):
                raise StateError("Invalid reroute guard")
            if marker in turns:
                return False
            atomic_write(guard_path, json_bytes([*turns[-31:], marker]))
        return True
