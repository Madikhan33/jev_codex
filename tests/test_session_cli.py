import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_router import FakeAPI
from test_session_state import capsule

from jev_router.cli import main


class SessionCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "settings.json"
        self.config.write_text(json.dumps({"enabled": True, "keep_me": 42}), encoding="utf-8")
        self.args = [
            "--config",
            str(self.config),
            "--session-id",
            "s1",
            "--project",
            str(self.root),
        ]

    def run_command(self, action, data=None, extra=None):
        output, errors = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
            patch("sys.stdin", io.StringIO(json.dumps(data))),
        ):
            code = main(["session", action, *self.args, *(extra or [])])
        return code, json.loads(output.getvalue()) if output.getvalue() else None

    def test_enable_save_conflict_clear_disable_preserve_settings(self):
        self.assertEqual(self.run_command("enable")[0], 0)
        self.assertEqual(json.loads(self.config.read_text())["keep_me"], 42)
        code, saved = self.run_command("save", capsule(), ["--expected-revision", "0"])
        self.assertEqual(code, 0)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(self.run_command("save", capsule(), ["--expected-revision", "0"])[0], 1)
        self.assertEqual(self.run_command("show")[1]["capsule"]["revision"], 1)
        self.assertEqual(
            self.run_command("clear", extra=["--expected-revision", "1"])[1]["status"], "cancelled"
        )
        self.assertFalse(self.run_command("disable")[1]["context_enabled"])
        self.assertEqual(self.run_command("save", capsule(), ["--expected-revision", "2"])[0], 1)

    def test_record_trace_retains_registered_assignment(self):
        event = {
            "status": "selected",
            "task_id": "t1",
            "agent_type": "jev_sol_medium",
            "profile": "sol_medium",
            "owner": "interface",
            "selection_source": "jev",
        }
        self.assertEqual(self.run_command("record", event)[0], 0)
        event = {
            "status": "dispatch_accepted",
            "task_id": "t1",
            "agent_type": "jev_sol_medium",
            "selection_source": "jev",
            "agent_id": "worker1",
            "tool_evidence": "Spawn returned worker1",
        }
        self.assertEqual(self.run_command("record", event)[0], 0)
        trace = self.run_command("trace")[1]
        self.assertEqual(trace["assignments"]["t1"]["profile"], "sol_medium")
        self.assertFalse(trace["actual_model_verified"])
        plan = self.run_command(
            "plan",
            {
                "group": {"owner": "interface", "profile": "sol_high"},
                "available_agents": ["jev_sol_medium", "jev_sol_high"],
                "existing": trace["assignments"]["t1"],
            },
        )[1]
        self.assertEqual(plan["profile"], "sol_medium")
        self.assertTrue(plan["retained"])

    def test_resolved_reroute_is_bounded_per_turn(self):
        self.run_command("enable")
        self.run_command("save", capsule(), ["--expected-revision", "0"])
        api = FakeAPI({"backend_logic": 0.99})

        class Transport:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return api

            def __exit__(self, *args):
                pass

        with (
            patch("jev_router.sdk.JevTransport", Transport),
            patch.dict("os.environ", {"TYPESAFE_API_KEY": "test"}),
        ):
            self.assertEqual(
                self.run_command("route", {"prompt": "Fix it"}, ["--turn-id", "turn1"])[0], 0
            )
            self.assertEqual(
                self.run_command("route", {"prompt": "Fix it"}, ["--turn-id", "turn1"])[0], 1
            )
        self.assertEqual(len(api.calls), 2)
        self.assertIn("Fix save race", api.calls[0][0]["context"])
