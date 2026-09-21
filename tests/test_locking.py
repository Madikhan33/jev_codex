import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jev_router.locking import file_lock

HOLDER = """
import os, sys, time
from pathlib import Path
from jev_router.locking import file_lock
with file_lock(Path(sys.argv[1])):
    print('locked', flush=True)
    if sys.argv[2] == 'exit':
        os._exit(0)
    time.sleep(60)
"""


class FileLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.lock"

    def holder(self, mode):
        process = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(self.path), mode],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(self.cleanup_process, process)
        self.assertEqual(process.stdout.readline().strip(), "locked")
        return process

    @staticmethod
    def cleanup_process(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)

    def test_process_exit_releases_lock_and_retains_file(self):
        process = self.holder("exit")
        process.wait(timeout=10)
        with file_lock(self.path, 0.5):
            self.assertTrue(self.path.exists())
        self.assertTrue(self.path.exists())

    def test_terminated_process_releases_lock(self):
        process = self.holder("wait")
        with self.assertRaises(TimeoutError):
            with file_lock(self.path, 0.03):
                self.fail("Contended lock acquired")
        process.kill()
        process.wait(timeout=10)
        with file_lock(self.path, 0.5):
            pass

    def test_exception_releases_lock(self):
        with self.assertRaisesRegex(RuntimeError, "test"):
            with file_lock(self.path):
                raise RuntimeError("test")
        with file_lock(self.path, 0):
            pass

    def test_symlink_check_without_windows_creation_privilege(self):
        from unittest.mock import patch

        with patch.object(Path, "is_symlink", return_value=True), self.assertRaises(ValueError):
            with file_lock(self.path):
                self.fail("Unsafe path accepted")
