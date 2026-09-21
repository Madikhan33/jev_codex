import tempfile
import unittest
from pathlib import Path

from jev_router.catalog import load_catalog
from jev_router.dispatch import (
    DispatchJournal,
    advance_dispatch,
    plan_assignment,
    validate_dispatch_event,
)


class DispatchTests(unittest.TestCase):
    def test_assignment_fields_survive_lifecycle_and_replanning(self):
        selected = self.event(profile="luna_high", owner="interface")
        accepted = advance_dispatch(
            selected,
            self.event(
                "dispatch_accepted", agent_id="worker1", tool_evidence="Spawn returned worker1"
            ),
        )
        self.assertEqual(accepted["profile"], "luna_high")
        plan = self.plan("sol_high", existing=accepted)
        self.assertTrue(plan["retained"])
        self.assertEqual(plan["agent_id"], "worker1")

    def test_available_agent_string_is_not_a_registry(self):
        with self.assertRaises(ValueError):
            plan_assignment(
                {"owner": "interface", "profile": "luna_low"},
                self.catalog,
                "some_jev_luna_low_substring",
            )

    def test_null_followup_retains_known_same_task_worker(self):
        previous = self.event(
            "dispatch_accepted",
            profile="luna_high",
            owner="interface",
            agent_id="worker1",
            tool_evidence="Spawn returned worker1",
        )
        result = self.plan(None, existing=previous)
        self.assertTrue(result["retained"])
        self.assertIsNone(result["recommended_profile"])
        self.assertEqual(result["profile"], "luna_high")
        self.assertEqual(result["agent_id"], "worker1")

    def setUp(self):
        self.catalog = load_catalog()
        self.available = [f"jev_{name}" for name in self.catalog["profiles"]]

    def plan(self, profile, **kwargs):
        return plan_assignment(
            {"owner": "interface", "profile": profile}, self.catalog, self.available, **kwargs
        )

    def event(self, status="selected", **kwargs):
        return dict(
            task_id="task1",
            agent_type="jev_luna_high",
            selection_source="jev",
            status=status,
            **kwargs,
        )

    def test_exact_mapping_all_seven_profiles(self):
        expected = {
            "luna_low": ("gpt-5.6-luna", "low"),
            "luna_medium": ("gpt-5.6-luna", "medium"),
            "luna_high": ("gpt-5.6-luna", "high"),
            "sol_medium": ("gpt-5.6-sol", "medium"),
            "sol_high": ("gpt-5.6-sol", "high"),
            "astra_low": ("gpt-6-astra", "low"),
            "astra_medium": ("gpt-6-astra", "medium"),
        }
        for profile, mapping in expected.items():
            with self.subTest(profile=profile):
                evidence = ["new_constraints:Established conflicting cross-system invariants"]
                plan = self.plan(profile, evidence=evidence if profile.startswith("astra") else [])
                self.assertEqual((plan["model"], plan["effort"]), mapping)
                self.assertEqual(plan["agent_type"], f"jev_{profile}")
                self.assertEqual(plan["status"], "recommendation")
                self.assertFalse(plan["actual_model_verified"])

    def test_missing_profile_and_unavailable_never_invent_fallback(self):
        self.assertEqual(self.plan(None)["status"], "needs_context")
        self.available = []
        result = self.plan("astra_medium")
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["model"])

    def test_initial_astra_selection_needs_evidence_without_inventing_fallback(self):
        result = self.plan("astra_low")
        self.assertEqual(result["status"], "needs_evidence")
        self.assertEqual(result["recommended_profile"], "astra_low")
        self.assertIsNone(result["model"])
        for invalid in (False, "", {}):
            with self.subTest(evidence=invalid), self.assertRaises(ValueError):
                self.plan("astra_low", evidence=invalid)

    def test_selected_assignment_must_stop_before_replacement(self):
        previous = dict(self.plan("luna_medium"), status="selected")
        result = self.plan(
            "sol_high",
            existing=previous,
            evidence=["failed_check:Reproduced a stale response overwriting edits"],
        )
        self.assertEqual(result["profile"], "luna_medium")
        self.assertEqual(result["escalation_blocked"], "stop_existing_first")

    def test_owner_transfer_is_explicit_and_requires_finished_assignment(self):
        previous = dict(self.plan("sol_medium"), status="dispatch_accepted", owner="server")
        result = self.plan("luna_medium", existing=previous)
        self.assertEqual(result["status"], "ownership_change_blocked")
        self.assertIsNone(result["model"])
        previous["status"] = "stopped"
        result = self.plan("luna_medium", existing=previous)
        self.assertEqual(result["owner"], "interface")
        self.assertEqual(result["profile"], "luna_medium")
        self.assertFalse(result["retained"])

    def test_lead_selection_requires_provenance(self):
        group = {"owner": "interface", "profile": "sol_medium", "selection_source": "lead"}
        with self.assertRaises(ValueError):
            plan_assignment(group, self.catalog, self.available)
        group["selection_reason"] = "Context identifies a multi-state UI feature"
        self.assertEqual(
            plan_assignment(group, self.catalog, self.available)["selection_source"], "lead"
        )

    def test_related_assignment_retained_and_escalation_gated(self):
        old = dict(self.plan("sol_medium"), status="completed", agent_id="agent1")
        self.assertTrue(self.plan("luna_low", existing=old)["retained"])
        self.assertEqual(self.plan("astra_low", existing=old)["profile"], "sol_medium")
        with self.assertRaises(ValueError):
            self.plan("astra_low", existing=old, evidence=["user is dissatisfied"])
        evidence = ["failed_check:Concurrent edits reproducibly overwrite a newer revision"]
        self.assertEqual(
            self.plan("sol_high", existing=old, evidence=evidence)["profile"], "sol_high"
        )
        old["status"] = "blocked"
        self.assertEqual(
            self.plan("sol_high", existing=old, evidence=evidence)["profile"], "sol_medium"
        )

    def test_events_require_real_tool_report_and_verification(self):
        with self.assertRaises(ValueError):
            validate_dispatch_event(self.event(secret="must not persist"))
        with self.assertRaises(ValueError):
            validate_dispatch_event(self.event(tool_evidence="x" * 2001))
        with self.assertRaises(ValueError):
            validate_dispatch_event(self.event("dispatch_accepted"))
        with self.assertRaises(ValueError):
            validate_dispatch_event(self.event(actual_model_verified=True))
        with self.assertRaises(ValueError):
            validate_dispatch_event(self.event("dispatch_failed", agent_id="agent1"))
        with self.assertRaises(ValueError):
            validate_dispatch_event(self.event("completed", agent_id="agent1", tool_evidence="ok"))

    def test_blocked_writer_cannot_be_replaced(self):
        selected = advance_dispatch(None, self.event())
        accepted = advance_dispatch(
            selected,
            self.event(
                "dispatch_accepted", agent_id="agent1", tool_evidence="spawn returned agent1"
            ),
        )
        blocked = advance_dispatch(accepted, self.event("blocked", agent_id="agent1"))
        with self.assertRaises(ValueError):
            advance_dispatch(blocked, self.event())
        with self.assertRaises(ValueError):
            advance_dispatch(
                blocked,
                self.event(
                    "dispatch_accepted", agent_id="agent2", tool_evidence="spawn returned agent2"
                ),
            )
        stopped = advance_dispatch(blocked, self.event("stopped", agent_id="agent1"))
        self.assertEqual(advance_dispatch(stopped, self.event())["status"], "selected")

    def test_journal_isolates_sessions_and_persists_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = DispatchJournal(root, "one", "project")
            first.record(self.event())
            first.record(self.event("dispatch_accepted", agent_id="agent1", tool_evidence="spawn"))
            reopened = DispatchJournal(root, "one", "project")
            with self.assertRaises(ValueError):
                reopened.record(self.event())
            self.assertEqual(len(reopened.read()), 2)
            self.assertEqual(DispatchJournal(root, "two", "project").read(), [])
            self.assertEqual(DispatchJournal(root, "one", "another").read(), [])

    def test_project_path_is_canonical_and_history_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal = DispatchJournal(root, "one", str(root / "project"))
            alias = DispatchJournal(root, "one", str(root / "child" / ".." / "project"))
            self.assertEqual(journal.path, alias.path)
            journal.record(self.event())
            for _ in range(105):
                journal.record(self.event())
            self.assertEqual(len(journal.read()), 100)

    def test_retained_assignment_keeps_selection_provenance(self):
        old = dict(self.plan("sol_medium"), selection_source="lead", status="completed")
        self.assertEqual(self.plan("luna_low", existing=old)["selection_source"], "lead")


if __name__ == "__main__":
    unittest.main()
