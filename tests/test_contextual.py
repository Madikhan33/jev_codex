import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_router import FakeAPI, choice

from jev_router.catalog import load_catalog
from jev_router.contextual import route_with_context
from jev_router.hook import hook_result
from jev_router.session_state import SessionStore


def capsule():
    return {
        "task_id": "button",
        "objective": "Change only button background to #ffffff",
        "constraints": ["No layout or backend changes"],
        "completed": [],
        "pending": ["Correct background color"],
        "facts": [{"text": "Button exists", "source": "observed"}],
        "open_questions": [],
        "owner": "interface",
        "status": "active",
    }


class ContextAPI(FakeAPI):
    def __init__(self, relation="correct", mass=0.94):
        super().__init__({"ui_style": 0.99}, {"ui_style": "luna_xhigh"})
        self.relation = relation
        self.mass = mass
        self.context_calls = []

    def __call__(self, state, questions):
        self.context_calls.append((state, questions))
        if "relation" in questions:
            return {
                "answers": {
                    "relation": choice(questions["relation"]["criteria"], self.relation, self.mass)
                }
            }
        return super().__call__(state, questions)


class ContextualTests(unittest.TestCase):
    def test_split_related_labels_preserve_reference_without_inventing_action(self):
        api = ContextAPI()

        def split_relation(state, questions):
            response = api(state, questions)
            if "relation" in questions:
                distribution = dict.fromkeys(questions["relation"]["criteria"], 0.0)
                distribution.update(
                    {"correct": 0.4, "continue": 0.4, "narrow": 0.1, "unclear": 0.1}
                )
                response["answers"]["relation"] = {
                    "type": "choice",
                    "choice": "correct",
                    "confidence": 0.5,
                    "probabilities": distribution,
                }
            return response

        result = route_with_context("Fix it", split_relation, self.catalog, self.saved)
        self.assertTrue(result["context_used"])
        self.assertEqual(result["relation"], "related_unspecified")
        self.assertFalse(result["relation_decision"]["accepted"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = SessionStore(self.root / "state", "session", str(self.root / "project"))
        self.saved = self.store.update(0, capsule())
        self.catalog = load_catalog()

    def test_followup_uses_capsule_without_inventing_difficulty(self):
        api = ContextAPI()
        result = route_with_context("Исправь это", api, self.catalog, self.saved)
        self.assertEqual(len(api.context_calls), 3)
        self.assertTrue(result["context_used"])
        self.assertIn("#ffffff", api.calls[0][0]["context"])
        self.assertEqual(result["result"]["groups"][0]["profile"], "luna_xhigh")

    def test_new_task_drops_old_context_before_category_and_profile_selection(self):
        api = ContextAPI("new_task")
        result = route_with_context("New task: change background", api, self.catalog, self.saved)
        self.assertFalse(result["context_used"])
        self.assertTrue(all(call[0]["context"] == "" for call in api.calls))

    def test_uncertain_relation_does_not_inherit_task(self):
        api = ContextAPI("continue", 0.4)
        result = route_with_context("Do it", api, self.catalog, self.saved)
        self.assertEqual(result["relation"], "unclear")
        self.assertFalse(result["context_used"])

    def test_cancel_does_not_launch_more_classification_or_mutate_ownership(self):
        api = ContextAPI("cancel")
        result = route_with_context("Stop", api, self.catalog, self.saved)
        self.assertIsNone(result["result"])
        self.assertEqual(len(api.context_calls), 1)
        self.assertEqual(self.store.read()["owner"], "interface")

    def test_hook_session_and_project_stay_local(self):
        api = ContextAPI()

        class Transport:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return api

            def __exit__(self, *args):
                pass

        settings = {"context_enabled": True, "state_dir": str(self.root / "state")}
        event = {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Исправь это",
            "session_id": "session",
            "cwd": str(self.root / "project"),
            "turn_id": "turn1",
            "transcript_path": "/never/open",
        }
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "test", "JEV_ROUTER_DISABLE": "0"}):
            result = hook_result(
                event,
                settings,
                transport_factory=Transport,
                config_path=self.root / "custom-settings.json",
            )
        sent = json.dumps(api.context_calls)
        self.assertNotIn(str(self.root), sent)
        self.assertNotIn("/never/open", sent)
        payload = json.loads(result["hookSpecificOutput"]["additionalContext"].split("\n", 1)[1])
        self.assertEqual(payload["session"]["revision"], 1)
        self.assertEqual(
            payload["session"]["runtime"]["config"],
            str((self.root / "custom-settings.json").resolve()),
        )
        self.assertEqual(payload["context"]["relation"], "correct")

    def test_expired_capsule_is_not_sent(self):
        api = ContextAPI()

        class Transport:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return api

            def __exit__(self, *args):
                pass

        state = self.store.read()
        state["updated_at"] = 1
        self.store.path.write_text(json.dumps(state), encoding="utf-8")
        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "test", "JEV_ROUTER_DISABLE": "0"}):
            result = hook_result(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Fix it",
                    "session_id": "session",
                    "cwd": str(self.root / "project"),
                },
                {"context_enabled": True, "state_dir": str(self.root / "state")},
                transport_factory=Transport,
            )
        self.assertNotIn("relation", api.context_calls[0][1])
        self.assertEqual(api.calls[0][0]["context"], "")
        self.assertIn("stale", result["hookSpecificOutput"]["additionalContext"])

    def test_context_limit_rejects_before_network(self):
        api = ContextAPI()
        catalog = load_catalog()
        catalog["policy"]["max_context_chars"] = 10
        with self.assertRaises(ValueError):
            route_with_context("Fix it", api, catalog, self.saved)
        self.assertEqual(api.context_calls, [])
