"""
API-level tests for the quota router (services/router/src/app.py).

The Gemini browser bridge is replaced by an in-process fake httpx client, and the
workspace is redirected to a temporary directory, so no containers are required.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# Redirect workspace writes BEFORE importing the app modules (they read it at import time).
_TMP_WORKSPACE = tempfile.mkdtemp(prefix="zg-router-test-")
os.environ["WORKSPACE_ROOT"] = _TMP_WORKSPACE

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app as router_app  # noqa: E402

GEMINI_REPLY = """Here you go.

File: src/hello.py
```python
def greet(name):
    return f"Hello {name}"
```
"""


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Minimal stand-in for httpx.AsyncClient that records bridge calls."""

    calls = []
    reply = GEMINI_REPLY
    raise_exc = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, timeout=None):
        return _FakeResponse(200, {"status": "ok"})

    async def post(self, url, json=None, timeout=None):
        if _FakeAsyncClient.raise_exc:
            raise _FakeAsyncClient.raise_exc
        _FakeAsyncClient.calls.append({"url": url, "json": json})
        return _FakeResponse(200, {"raw_output": _FakeAsyncClient.reply, "status": "success"})


class TestRouterApi(unittest.TestCase):
    def setUp(self):
        _FakeAsyncClient.calls = []
        _FakeAsyncClient.reply = GEMINI_REPLY
        _FakeAsyncClient.raise_exc = None
        self.patcher = patch.object(router_app.httpx, "AsyncClient", _FakeAsyncClient)
        self.patcher.start()
        self.client = TestClient(router_app.app)

    def tearDown(self):
        self.patcher.stop()

    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["browser_bridge_connected"])
        self.assertIn("local_ai_enabled", body)

    def test_models_endpoint(self):
        ids = [m["id"] for m in self.client.get("/v1/models").json()["data"]]
        self.assertIn("zerogravity", ids)
        self.assertIn("0g", ids)

    def test_openwebui_meta_task_is_intercepted(self):
        payload = {"model": "zerogravity", "messages": [{"role": "user", "content": "### Task:\nGenerate a concise, 3-5 word title"}]}
        res = self.client.post("/v1/chat/completions", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertIn("title", res.json()["choices"][0]["message"]["content"])
        self.assertEqual(_FakeAsyncClient.calls, [], "meta tasks must not reach Gemini")

    def test_chat_completion_writes_files_and_flags_new_chat(self):
        payload = {"model": "zerogravity", "messages": [{"role": "user", "content": "Create src/hello.py"}]}
        res = self.client.post("/v1/chat/completions", json=payload)
        self.assertEqual(res.status_code, 200)
        content = res.json()["choices"][0]["message"]["content"]
        self.assertIn("ZeroGravity Workspace Files Created", content)

        written = os.path.join(_TMP_WORKSPACE, "src", "hello.py")
        self.assertTrue(os.path.isfile(written))
        with open(written, encoding="utf-8") as fh:
            self.assertIn("def greet", fh.read())

        self.assertEqual(len(_FakeAsyncClient.calls), 1)
        self.assertTrue(_FakeAsyncClient.calls[0]["json"]["new_chat"])
        self.assertTrue(os.path.isdir(os.path.join(_TMP_WORKSPACE, ".gemini-history")))

    def test_follow_up_turn_continues_same_chat(self):
        stale_file = os.path.join(_TMP_WORKSPACE, "turn1_file.txt")
        with open(stale_file, "w", encoding="utf-8") as fh:
            fh.write("keep me on turn 2")
        payload = {
            "model": "zerogravity",
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "answer"},
                {"role": "user", "content": "Create src/hello.py"},
            ],
        }
        self.client.post("/v1/chat/completions", json=payload)
        self.assertFalse(_FakeAsyncClient.calls[0]["json"]["new_chat"])
        self.assertTrue(os.path.isfile(stale_file), "follow-up turns must preserve existing workspace files")

    def test_auto_project_subfolder_when_workspace_is_root(self):
        _FakeAsyncClient.reply = (
            "Project: ts-priority-queue\n\n"
            "File: src/hello.py\n"
            "```python\ndef greet(name):\n    return f'Hello {name}'\n```\n"
        )
        with patch.dict(os.environ, {"HOST_WORKSPACE_PATH": "./workspace"}):
            res1 = self.client.post(
                "/v1/chat/completions",
                json={"model": "zerogravity", "messages": [{"role": "user", "content": "Create src/hello.py"}]},
            )
            self.assertEqual(res1.status_code, 200)
            turn1_reply = res1.json()["choices"][0]["message"]["content"]
            self.assertIn("ZeroGravity Project Folder:", turn1_reply)
            self.assertTrue(os.path.isfile(os.path.join(_TMP_WORKSPACE, "ts-priority-queue", "src", "hello.py")))

            # Turn 2 in same conversation should automatically write into the same project folder
            _FakeAsyncClient.reply = (
                "File: src/extra.py\n"
                "```python\nX = 42\n```\n"
            )
            res2 = self.client.post(
                "/v1/chat/completions",
                json={
                    "model": "zerogravity",
                    "messages": [
                        {"role": "user", "content": "Create src/hello.py"},
                        {"role": "assistant", "content": turn1_reply},
                        {"role": "user", "content": "Now add src/extra.py"},
                    ],
                },
            )
            self.assertEqual(res2.status_code, 200)
            self.assertTrue(os.path.isfile(os.path.join(_TMP_WORKSPACE, "ts-priority-queue", "src", "extra.py")))

    def test_bridge_unreachable_returns_503(self):
        _FakeAsyncClient.raise_exc = httpx.ConnectError("refused")
        res = self.client.post("/generate", json={"prompt": "Create src/hello.py"})
        self.assertEqual(res.status_code, 503)

    def test_bridge_timeout_returns_504(self):
        _FakeAsyncClient.raise_exc = httpx.ReadTimeout("slow")
        res = self.client.post("/generate", json={"prompt": "Create src/hello.py"})
        self.assertEqual(res.status_code, 504)

    def test_path_traversal_is_rejected(self):
        _FakeAsyncClient.reply = "File: ../../etc/evil.py\n```python\nprint('x')\n```\n"
        res = self.client.post("/generate", json={"prompt": "do it"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "validation_failed")
        self.assertFalse(os.path.exists(os.path.join(_TMP_WORKSPACE, "..", "..", "etc", "evil.py")))

    def test_empty_messages_rejected(self):
        res = self.client.post("/v1/chat/completions", json={"model": "zerogravity", "messages": []})
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()

