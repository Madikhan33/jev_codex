import unittest

from jev_router.teamwork import plan_message, plan_research


class ResearchTests(unittest.TestCase):
    def plan(self, **kwargs):
        return plan_research(
            dict(
                question="Which API contract applies?", gap="external", web_available=True, **kwargs
            )
        )

    def test_external_gap_uses_web_then_stops_after_verified_evidence(self):
        self.assertEqual(self.plan()["action"], "search_web")
        result = self.plan(current=True, evidence_sufficient=True, attempts=1)
        self.assertEqual(result["action"], "proceed")
        self.assertFalse(result["executed"])

    def test_missing_private_decisions_and_repository_facts_do_not_use_web(self):
        for gap, expected in (("requirements", "ask_user"), ("repository", "inspect_local")):
            with self.subTest(gap=gap):
                self.assertEqual(
                    plan_research(
                        dict(question="Missing fact", gap=gap, current=True, web_available=True)
                    )["action"],
                    expected,
                )

    def test_explicit_search_even_with_existing_evidence_then_no_repeat(self):
        self.assertEqual(
            self.plan(explicit_search=True, evidence_sufficient=True)["action"], "search_web"
        )
        self.assertEqual(
            self.plan(explicit_search=True, evidence_sufficient=True, attempts=1)["action"],
            "proceed",
        )

    def test_explicit_search_does_not_erase_local_gap(self):
        result = plan_research(
            {
                "question": "Compare public patterns",
                "gap": "requirements",
                "explicit_search": True,
                "web_available": True,
            }
        )
        self.assertEqual(result["action"], "search_web")
        self.assertEqual(result["local_followup"], "ask_user")

    def test_unavailable_forbidden_and_exhausted_search_report_gap(self):
        self.assertEqual(self.plan(web_allowed=False)["action"], "report_gap")
        self.assertEqual(
            plan_research(dict(question="Fact", gap="external"))["action"], "report_gap"
        )
        self.assertEqual(self.plan(attempts=2)["action"], "report_gap")

    def test_known_stable_fact_needs_no_tool(self):
        self.assertEqual(
            plan_research(dict(question="Known fact", gap="none"))["action"], "proceed"
        )

    def test_invalid_types_and_unbounded_inputs_rejected(self):
        for invalid in (
            {"attempts": True},
            {"attempts": 3},
            {"current": "false"},
            {"web_allowed": None},
            {"unrecognized": 1},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.plan(**invalid)


class MessageTests(unittest.TestCase):
    def payload(self, **kwargs):
        return dict(
            task_id="ui-api",
            sender="/root/ui",
            recipient="/root/api",
            kind="question",
            body="What is the error response schema?",
            evidence=["api/errors.py:12"],
            roster={"/root/ui": "running", "/root/api": "running"},
            peer_messaging=True,
            **kwargs,
        )

    def test_direct_message_is_compact_but_not_claimed_delivered(self):
        result = plan_message(self.payload())
        self.assertEqual(result["action"], "send_peer")
        self.assertEqual(result["target"], "/root/api")
        self.assertIn("api/errors.py:12", result["message"])
        self.assertEqual(result["characters"], len(result["message"]))
        self.assertFalse(result["delivered"])
        self.assertFalse(result["notify_lead"])

    def test_message_identity_changes_with_recipient_and_evidence(self):
        payload = self.payload()
        first = plan_message(payload)["message_id"]
        payload["evidence"] = ["api/errors.py:16"]
        self.assertNotEqual(first, plan_message(payload)["message_id"])

    def test_duplicate_is_not_resent(self):
        first = plan_message(self.payload())
        again = plan_message(self.payload(previous_ids=[first["message_id"]]))
        self.assertEqual(again["action"], "skip_duplicate")

    def test_idle_stopped_and_missing_peer_tools_have_explicit_fallbacks(self):
        payload = self.payload()
        payload["peer_messaging"] = False
        self.assertEqual(plan_message(payload)["action"], "relay_via_lead")
        payload["roster"]["/root/api"] = "idle"
        self.assertEqual(plan_message(payload)["action"], "request_lead_followup")
        payload["roster"]["/root/api"] = "stopped"
        self.assertEqual(plan_message(payload)["action"], "report_unavailable")

    def test_contract_and_blocker_notify_lead(self):
        for kind in ("contract", "blocker"):
            payload = self.payload()
            payload["kind"] = kind
            self.assertTrue(plan_message(payload)["notify_lead"])

    def test_unknown_peer_and_self_message_rejected(self):
        for recipient in ("/another-team/agent", "/root/ui"):
            payload = self.payload()
            payload["recipient"] = recipient
            with self.assertRaises(ValueError):
                plan_message(payload)

    def test_bounds_and_types(self):
        for key, value in (
            ("body", "x" * 1201),
            ("evidence", ["x"] * 5),
            ("roster", []),
            ("previous_ids", "id"),
            ("peer_messaging", "true"),
            ("kind", "reassign"),
        ):
            payload = self.payload()
            payload[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                plan_message(payload)


if __name__ == "__main__":
    unittest.main()
