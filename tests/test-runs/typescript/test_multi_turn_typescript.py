#!/usr/bin/env python3
"""
Multi-turn (2 turns) TypeScript PriorityQueue test script for ZeroGravity.
"""

import sys
import os
import json
import time
import urllib.request
from pathlib import Path

ROUTER_URL = os.environ.get("ROUTER_URL", "http://localhost:8000")
repo_ws = Path(__file__).resolve().parents[3] / "workspace"
default_ws = repo_ws if repo_ws.exists() else Path(__file__).parent / "workspace"
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", default_ws))

TURN_1_PROMPT = """Build a modular TypeScript Priority Task Queue project. You MUST generate the following 4 files:
1. File: package.json
   - Name `ts-priority-queue`, scripts: `"build": "tsc"`, `"start": "tsc && node dist/cli.js"`, `"test": "tsc && node dist/queue.test.js"`.
   - Include `"typescript": "^5.6.0"` and `"@types/node": "^20.0.0"` in `devDependencies`.
2. File: tsconfig.json
   - Target `ES2022`, module `commonjs`, `rootDir`: `./src`, `outDir`: `./dist`, `strict`: true, `esModuleInterop`: true.
3. File: src/types.ts
   - Export type `Priority = "low" | "medium" | "high"`.
   - Export interface `TaskItem { id: string; title: string; priority: Priority; createdAt: number; }`.
4. File: src/priorityQueue.ts
   - Import `TaskItem` and `Priority` from `./types`.
   - Export class `PriorityQueue` with methods:
     - `enqueue(task: Omit<TaskItem, "createdAt">): TaskItem`
     - `dequeue(): TaskItem | undefined` (returns highest priority task first: high > medium > low, and FIFO within the same priority)
     - `size(): number`
     - `peek(): TaskItem | undefined`

Precede every file with a clear "File: <path>" header immediately preceding its code block.
"""

TURN_2_PROMPT = """Great! Now expand our TypeScript PriorityQueue project by adding a CLI demo and a self-contained test suite. Generate the following 3 files:
1. File: src/priorityQueue.ts
   - Keep existing functionality and add a new method `filterByPriority(priority: Priority): TaskItem[]` and validation in `enqueue` that throws an `Error("Task title cannot be empty")` if `title.trim()` is empty.
2. File: src/cli.ts
   - Import `PriorityQueue` from `./priorityQueue`.
   - Enqueue 3 sample tasks (`low`, `high`, `medium`), print the queue size, and dequeue all items printing their order.
3. File: src/queue.test.ts
   - Use Node's built-in `import assert from "node:assert/strict"`.
   - Test that `dequeue()` returns `"high"` before `"medium"` and `"low"`.
   - Test `filterByPriority("high")`.
   - Test that `enqueue` with an empty title throws an Error.
   - Print `"ALL TESTS PASSED"` at the end.

Precede every file with a clear "File: <path>" header immediately preceding its code block.
"""


def post_json(url: str, payload: dict, timeout: int = 600) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_ts_files(dir_path: Path):
    if not dir_path.exists():
        return []
    return [f for f in dir_path.rglob("*.ts") if "node_modules" not in f.parts]


def main():
    print("=" * 60)
    print(" ZeroGravity Multi-Turn Test: TypeScript PriorityQueue")
    print(f" Target Router:    {ROUTER_URL}")
    print(f" Target Workspace: {WORKSPACE_DIR}")
    print("=" * 60)

    try:
        with urllib.request.urlopen(f"{ROUTER_URL}/healthz", timeout=5) as r:
            health = json.loads(r.read().decode("utf-8"))
            print(f"[1/4] Router reachable. Status: {health.get('status')}, signed_in: {health.get('browser_signed_in')}")
    except Exception as e:
        print(f"ERROR: Cannot reach router at {ROUTER_URL}: {e}")
        sys.exit(1)

    print("\n" + "-" * 60)
    print(">>> TURN 1: Sending initial prompt for TypeScript PriorityQueue...")
    print("-" * 60)
    t0 = time.time()
    t1_res = post_json(
        f"{ROUTER_URL}/v1/chat/completions",
        {"model": "zerogravity", "messages": [{"role": "user", "content": TURN_1_PROMPT}]},
    )
    print(f"Turn 1 completed in {time.time() - t0:.1f}s")
    t1_reply = t1_res["choices"][0]["message"]["content"]

    t1_files = get_ts_files(WORKSPACE_DIR)
    print(f"Workspace TS files after Turn 1 ({len(t1_files)} found):")
    for f in t1_files:
        print(f"  - {f.relative_to(WORKSPACE_DIR)}")

    print("\n" + "-" * 60)
    print(">>> TURN 2: Sending follow-up for filterByPriority, CLI & tests...")
    print("-" * 60)
    t0 = time.time()
    t2_res = post_json(
        f"{ROUTER_URL}/v1/chat/completions",
        {
            "model": "zerogravity",
            "messages": [
                {"role": "user", "content": TURN_1_PROMPT},
                {"role": "assistant", "content": t1_reply},
                {"role": "user", "content": TURN_2_PROMPT},
            ],
        },
    )
    print(f"Turn 2 completed in {time.time() - t0:.1f}s")
    t2_reply = t2_res["choices"][0]["message"]["content"]
    print("\nAssistant Reply (preview):\n", t2_reply[:350], "...\n")

    all_ts_files = get_ts_files(WORKSPACE_DIR)
    print(f"Total workspace TS files after Turn 2 ({len(all_ts_files)} found):")
    for f in all_ts_files:
        print(f"  - {f.relative_to(WORKSPACE_DIR)}")

    if len(all_ts_files) >= 4:
        print(f"\n[PASS] MULTI-TURN TYPESCRIPT TEST PASSED: Generated {len(all_ts_files)} TypeScript files across 2 turns.")
    else:
        print(f"\n[FAIL] Expected >= 4 TS files total, found: {len(all_ts_files)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

