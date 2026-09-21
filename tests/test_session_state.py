import json
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jev_router.session_state import SessionStore, StaleRevisionError, StateError, render_context


def capsule(**changes):
    value = dict(
        task_id="task-1",
        objective="Fix save race",
        constraints=["Preserve API"],
        completed=[],
        pending=["Test concurrent saves"],
        facts=[dict(text="Race observed", source="observed")],
        open_questions=[],
        owner="frontend",
        status="active",
    )
    return value | changes


class SessionStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = SessionStore(self.root / "state", "../session", str(self.root))

    def test_roundtrip_revision_and_isolation(self):
        self.assertIsNone(self.store.read())
        result = self.store.update(0, capsule(turn_id="turn-1"))
        self.assertEqual(result["revision"], 1)
        self.assertEqual(result, self.store.read())
        self.assertNotIn("updated_at", render_context(result))
        self.assertIsNone(SessionStore(self.root / "state", "another", str(self.root)).read())
        self.assertIsNone(
            SessionStore(self.root / "state", "../session", str(self.root / "other")).read()
        )
        self.assertEqual(self.store.path.parent, self.root / "state")

    def test_stale_update_and_reset(self):
        self.store.update(0, capsule())
        with self.assertRaises(StaleRevisionError):
            self.store.update(0, capsule(objective="stale"))
        cleared = self.store.reset(1)
        self.assertEqual(cleared["revision"], 2)
        self.assertEqual(cleared["status"], "cancelled")
        self.assertIsNone(cleared["owner"])
        new = self.store.update(2, capsule(task_id="task-2", owner=None))
        self.assertIsNone(new["owner"])

    def test_expired_read_preserves_revision(self):
        result = self.store.update(0, capsule())
        result["updated_at"] = time.time() - 90000
        self.store.path.write_text(json.dumps(result), encoding="utf-8-sig")
        self.assertIsNone(self.store.read())
        self.assertEqual(self.store.read(include_stale=True)["revision"], 1)
        with self.assertRaises(StaleRevisionError):
            self.store.update(0, capsule())
        self.store.update(1, capsule())

    def test_concurrent_compare_and_swap(self):
        def save(_):
            try:
                self.store.update(0, capsule())
                return True
            except StaleRevisionError:
                return False

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(save, range(6)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.store.read()["revision"], 1)

    def test_invalid_capsules_fail_closed(self):
        for bad in [
            capsule(unexpected=True),
            capsule(facts=[{"text": "x", "source": "invented"}]),
            capsule(objective="x" * 2001),
            capsule(constraints=["x" * 1900] * 4),
            capsule(owner=4),
            capsule(status="unknown"),
        ]:
            with self.subTest(bad=bad), self.assertRaises(StateError):
                self.store.update(0, bad)
        self.store.root.mkdir(exist_ok=True)
        self.store.path.write_text("{corrupt", encoding="utf-8")
        with self.assertRaises(StateError):
            self.store.read()
        with self.assertRaises(StateError):
            self.store.update(0, capsule())

    def test_processes_share_compare_and_swap_lock(self):
        script = """
import json, sys
from pathlib import Path
from jev_router.session_state import SessionStore, StaleRevisionError
store = SessionStore(Path(sys.argv[1]), '../session', sys.argv[2])
try:
    store.update(0, json.loads(sys.argv[3]))
except StaleRevisionError:
    print('stale')
else:
    print('saved')
"""
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    script,
                    str(self.store.root),
                    str(self.root),
                    json.dumps(capsule()),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(4)
        ]
        outcomes = []
        for process in processes:
            output, error = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, error)
            outcomes.append(output.strip())
        self.assertEqual(outcomes.count("saved"), 1)
        self.assertEqual(outcomes.count("stale"), 3)

    def test_bounded_lock_timeout(self):
        from jev_router.locking import file_lock

        self.store.lock_timeout = 0.03
        started = time.monotonic()
        with file_lock(self.store.lock_path):
            with self.assertRaises(StateError):
                self.store.update(0, capsule())
        self.assertLess(time.monotonic() - started, 1)

    def test_persistent_unlocked_file_is_not_busy(self):
        self.store.root.mkdir()
        self.store.lock_path.touch()
        self.store.update(0, capsule())
        self.assertEqual(self.store.read()["revision"], 1)
        self.assertTrue(self.store.lock_path.exists())

    def test_reroute_guard_once_per_turn(self):
        self.assertTrue(self.store.claim_reroute("first"))
        self.assertFalse(self.store.claim_reroute("first"))
        self.assertTrue(self.store.claim_reroute("second"))
        self.assertIsNone(self.store.read())
        for index in range(40):
            self.store.claim_reroute(str(index))
        guard = json.loads(self.store.path.with_suffix(".turns.json").read_text())
        self.assertEqual(len(guard), 32)

    def test_symlink_storage_refused(self):
        target = self.root / "target"
        target.mkdir()
        link = self.root / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with self.assertRaises(StateError):
            SessionStore(link, "session", str(self.root))


if __name__ == "__main__":
    unittest.main()
