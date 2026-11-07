"""
Unit tests for the browser bridge HTTP API.

The Playwright automator is fully mocked, so these tests need neither a browser
binary nor network access (only the `playwright` Python package for imports).
"""
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402


class TestBridgeServer(unittest.TestCase):
    def setUp(self):
        # Do not enter the lifespan context: it would try to launch Chromium.
        self.client = TestClient(server.app)

    def test_healthz_reports_auth_state(self):
        with patch.object(server.automator, "is_authenticated", AsyncMock(return_value=True)), \
                patch.object(server.automator, "is_signed_in", AsyncMock(return_value=False)):
            res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["authenticated"])
        self.assertFalse(body["signed_in"])

    def test_healthz_handles_automator_errors(self):
        with patch.object(server.automator, "is_authenticated", AsyncMock(side_effect=Exception("boom"))):
            res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "error")

    def test_generate_rejects_empty_prompt(self):
        res = self.client.post("/generate", json={"prompt": "   "})
        self.assertEqual(res.status_code, 400)

    def test_generate_success_forwards_options(self):
        send = AsyncMock(return_value="File: main.py\n```python\nprint('hi')\n```")
        with patch.object(server.automator, "send_prompt", send):
            res = self.client.post("/generate", json={"prompt": "hello", "new_chat": True, "timeout": 30})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")
        self.assertIn("print('hi')", res.json()["raw_output"])
        send.assert_awaited_once_with("hello", timeout=30, new_chat=True)

    def test_generate_timeout_maps_to_504(self):
        with patch.object(server.automator, "send_prompt", AsyncMock(side_effect=TimeoutError("too slow"))):
            res = self.client.post("/generate", json={"prompt": "hello"})
        self.assertEqual(res.status_code, 504)

    def test_generate_unauthenticated_maps_to_401(self):
        with patch.object(server.automator, "send_prompt", AsyncMock(side_effect=RuntimeError("Browser not authenticated"))):
            res = self.client.post("/generate", json={"prompt": "hello"})
        self.assertEqual(res.status_code, 401)

    def test_generate_unexpected_error_maps_to_500(self):
        with patch.object(server.automator, "send_prompt", AsyncMock(side_effect=ValueError("bad"))):
            res = self.client.post("/generate", json={"prompt": "hello"})
        self.assertEqual(res.status_code, 500)


if __name__ == "__main__":
    unittest.main()

