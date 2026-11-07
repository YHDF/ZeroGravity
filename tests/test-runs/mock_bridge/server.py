"""
Mock Gemini browser bridge for CI.

Implements the same HTTP contract as services/browser_bridge/server.py
(GET /healthz, POST /generate) but replays *recorded* Gemini Web responses
from ./fixtures instead of driving a real browser. This lets CI exercise the
full router pipeline (prompt conditioning -> extraction -> validation ->
workspace writes -> .gemini-history) deterministically and without a Google
account.

Extra endpoint for assertions:
  GET /__requests  -> list of {"fixture", "new_chat", "prompt_chars"} received so far

Standard library only, so the image needs no pip install.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

# Ordered (most specific first): (fixture file, keywords that must ALL appear in the prompt)
ROUTES = [
    ("fibonacci_turn2.md", ["memoizedFibonacci"]),
    ("fibonacci_turn1.md", ["Fibonacci"]),
    ("springboot_turn2.md", ["TaskNotFoundException"]),
    ("springboot_turn1.md", ["Task Management"]),
]

RECEIVED = []


def pick_fixture(prompt: str):
    for fixture, keywords in ROUTES:
        if all(k in prompt for k in keywords):
            return fixture
    return None


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 (http.server API)
        if self.path == "/healthz":
            self._send(200, {"status": "ok", "authenticated": True, "signed_in": False, "browser_active": True, "mock": True})
        elif self.path == "/__requests":
            self._send(200, {"requests": RECEIVED})
        else:
            self._send(404, {"detail": "Not found"})

    def do_POST(self):  # noqa: N802 (http.server API)
        if self.path != "/generate":
            self._send(404, {"detail": "Not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"detail": "Invalid JSON"})
            return

        prompt = req.get("prompt", "")
        if not prompt.strip():
            self._send(400, {"detail": "Prompt must not be empty."})
            return

        fixture = pick_fixture(prompt)
        RECEIVED.append({"fixture": fixture, "new_chat": bool(req.get("new_chat")), "prompt_chars": len(prompt)})
        if fixture is None:
            self._send(500, {"detail": "Mock bridge: no recorded fixture matches this prompt."})
            return

        with open(os.path.join(FIXTURE_DIR, fixture), encoding="utf-8") as fh:
            self._send(200, {"raw_output": fh.read(), "status": "success"})

    def log_message(self, fmt, *args):
        print(f"[mock-bridge] {self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"[mock-bridge] serving recorded fixtures from {FIXTURE_DIR} on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()  # nosec B104

