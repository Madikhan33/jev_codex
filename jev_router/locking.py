"""Crash-safe, bounded advisory file locks shared by local state stores."""

from __future__ import annotations

import errno
import math
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _check_path(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or (
            hasattr(candidate, "is_junction") and candidate.is_junction()
        ):
            raise ValueError("Lock storage cannot use symlinks or junctions")


def _acquire(descriptor: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release(descriptor: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def file_lock(path: Path, timeout: float = 2) -> Iterator[None]:
    """Lock one byte/inode; process exit releases ownership, not the persistent file.

    Lock files must never be removed during normal operation: removing an inode
    while another process holds it would allow two independent owners.
    """
    if not math.isfinite(timeout) or timeout < 0:
        raise ValueError("Lock timeout must be finite and nonnegative")
    _check_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _check_path(path)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    acquired = False
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                _acquire(descriptor)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("State storage is locked; retry later") from None
                time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        yield
    finally:
        try:
            if acquired:
                _release(descriptor)
        finally:
            os.close(descriptor)
