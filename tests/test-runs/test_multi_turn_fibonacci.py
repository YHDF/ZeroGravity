#!/usr/bin/env python3
"""
Multi-turn (2 turns) test script for ZeroGravity.
Prompts Gemini Web via Quota Router to generate:
- Turn 1: At least 2 JavaScript (.js) files (fibonacci.js, cli.js)
- Turn 2: At least 2 new JavaScript (.js) files (memoizedFibonacci.js, benchmark.js)
"""

import sys
import os
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

ROUTER_URL = os.environ.get("ROUTER_URL", "http://localhost:8000")
repo_ws = Path(__file__).resolve().parent.parent.parent / "workspace"
default_ws = repo_ws if repo_ws.exists() else Path(__file__).parent / "workspace"
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", default_ws))

TURN_1_PROMPT = """Build a modular Node.js Fibonacci project. You MUST generate at least two separate JavaScript (.js) files:
1. File: src/fibonacci.js
   - Export an iterative function `fibonacci(n)` and a recursive function `fibonacciRecursive(n)`.
   - Include argument validation (throw Error if n < 0 or not an integer).
2. File: src/cli.js
   - Import `fibonacci` from `./fibonacci.js`.
   - Read the number `n` from process.argv (default to 10 if omitted) and print the sequence.

Declare each file with a clear "File: <path>" header immediately preceding its code block.
"""

TURN_2_PROMPT = """Great! Now expand our Fibonacci project by creating at least two NEW separate JavaScript (.js) files:
1. File: src/memoizedFibonacci.js
   - Export `memoizedFibonacci(n)` using a Map or closure cache.
   - Also export a generator function `fibonacciSequence(limit)`.
2. File: src/benchmark.js
   - Import `fibonacci` from `./fibonacci.js` and `memoizedFibonacci` from `./memoizedFibonacci.js`.
   - Measure and compare the execution time of calculating the 40th Fibonacci number using console.time / console.timeEnd.

Declare each file with a clear "File: <path>" header immediately preceding its code block.
"""


def post_json(url: str, payload: dict, timeout: int = 600) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_js_files(dir_path: Path):
    if not dir_path.exists():
        return []
    return list(dir_path.rglob("*.js"))


def main():
    print("=" * 60)
    print(" ZeroGravity Multi-Turn Test: Fibonacci JS Generator")
    print(f" Target Router:    {ROUTER_URL}")
    print(f" Target Workspace: {WORKSPACE_DIR}")
    print("=" * 60)

    # 1. Health check
    try:
        with urllib.request.urlopen(f"{ROUTER_URL}/healthz", timeout=5) as r:
            health = json.loads(r.read().decode("utf-8"))
            print(f"[1/4] Router reachable. Status: {health.get('status')}, local_ai: {health.get('local_ai_enabled')}")
    except Exception as e:
        print(f"ERROR: Cannot reach router at {ROUTER_URL}: {e}")
        sys.exit(1)

    # -------------------------------------------------------------
    # TURN 1
    # -------------------------------------------------------------
    print("\n" + "-" * 60)
    print(">>> TURN 1: Sending initial prompt for 2 JS files...")
    print("-" * 60)
    t1_payload = {
        "model": "zerogravity",
        "messages": [
            {"role": "user", "content": TURN_1_PROMPT}
        ]
    }
    t0 = time.time()
    t1_res = post_json(f"{ROUTER_URL}/v1/chat/completions", t1_payload)
    print(f"Turn 1 completed in {time.time() - t0:.1f}s")

    t1_reply = t1_res["choices"][0]["message"]["content"]
    print("\nAssistant Reply (preview):\n", t1_reply[:350], "...\n")

    t1_files = get_js_files(WORKSPACE_DIR)
    print(f"Workspace JS files after Turn 1 ({len(t1_files)} found):")
    for f in t1_files:
        print(f"  - {f.relative_to(WORKSPACE_DIR)}")

    if len(t1_files) < 2:
        print(f"WARNING: Turn 1 produced {len(t1_files)} JS files (< 2 expected).")
    else:
        print(f"SUCCESS: Turn 1 produced {len(t1_files)} JS files.")

    # -------------------------------------------------------------
    # TURN 2 (Multi-Turn continuation in same chat)
    # -------------------------------------------------------------
    print("\n" + "-" * 60)
    print(">>> TURN 2: Sending follow-up in same conversation context...")
    print("-" * 60)
    t2_payload = {
        "model": "zerogravity",
        "messages": [
            {"role": "user", "content": TURN_1_PROMPT},
            {"role": "assistant", "content": t1_reply},
            {"role": "user", "content": TURN_2_PROMPT}
        ]
    }
    t0 = time.time()
    t2_res = post_json(f"{ROUTER_URL}/v1/chat/completions", t2_payload)
    print(f"Turn 2 completed in {time.time() - t0:.1f}s")

    t2_reply = t2_res["choices"][0]["message"]["content"]
    print("\nAssistant Reply (preview):\n", t2_reply[:350], "...\n")

    all_files = get_js_files(WORKSPACE_DIR)
    print(f"Total workspace JS files after Turn 2 ({len(all_files)} found):")
    for f in all_files:
        print(f"  - {f.relative_to(WORKSPACE_DIR)}")

    if len(all_files) >= 4:
        print(f"\n🎉 MULTI-TURN TEST PASSED: Generated {len(all_files)} JavaScript files across 2 turns.")
    else:
        print(f"\n⚠️ Expected >= 4 JS files total, found: {len(all_files)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

