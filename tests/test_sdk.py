"""Real SDK serialization and parsing, with HTTP intercepted before the network."""

import importlib.util
import json
import logging
import os
import unittest
from unittest.mock import patch

from test_router import FakeAPI

from jev_router.routing import classify


@unittest.skipUnless(importlib.util.find_spec("typesafe_sdk"), "optional SDK contract tests")
class SDKTests(unittest.TestCase):
    def test_real_sdk_two_stage_protocol_and_no_debug_logging(self):
        import httpx2
        import typesafe_sdk

        from jev_router.sdk import JevTransport

        api = FakeAPI({"frontend_api": 0.98, "backend_api": 0.98}, coordination="separable")
        requests = []

        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            result = api(body["state"], body["questions"])
            return httpx2.Response(200, json={"model": "jev-latest", **result})

        real_client = typesafe_sdk.TypeSafeClient

        def client(**kwargs):
            return real_client(**kwargs, transport=httpx2.MockTransport(handle))

        with (
            patch.dict(os.environ, {"TYPESAFE_LOG_LEVEL": "debug"}),
            patch.object(typesafe_sdk, "TypeSafeClient", side_effect=client),
        ):
            with JevTransport("test-not-a-real-key", model="jev-latest", timeout=5) as transport:
                result = classify("Build cards UI and API", transport)
            self.assertTrue(logging.getLogger("typesafe_sdk").disabled)
        self.assertEqual(len(requests), 2)
        self.assertEqual(result["strategy"], "consider_delegation")
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(requests[0]["state"]["request"], "Build cards UI and API")
