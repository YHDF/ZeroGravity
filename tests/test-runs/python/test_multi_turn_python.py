#!/usr/bin/env python3
"""
Multi-turn (2 turns) Python LRUCache test script for ZeroGravity.
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

TURN_1_PROMPT = """Build a modular Python LRU Cache project using only the Python standard library. You MUST generate the following 2 files:
1. File: src/lru_cache.py
   - Implement class `LRUCache` using `collections.OrderedDict` with `capacity: int` (raise `ValueError("Capacity must be >= 1")` if `capacity < 1`).
   - Methods:
     - `get(key: str, default=None)`: returns the value if present and marks the key as most recently used, otherwise returns `default`.
     - `put(key: str, value) -> None`: inserts or updates the key as most recently used, evicting the least recently used item if over `capacity`.
     - `delete(key: str) -> bool`: removes the key and returns `True` if it existed, else `False`.
     - `size() -> int` and `keys() -> list[str]` (ordered from least to most recently used).
2. File: src/cli.py
   - Import `LRUCache` from `lru_cache` (or `src.lru_cache`).
   - Create an `LRUCache(capacity=3)`, insert `"a": 1`, `"b": 2`, `"c": 3`, access `"a"`, insert `"d": 4` (which should evict `"b"`), and print the remaining keys and values.

Precede every file with a clear "File: <path>" header immediately preceding its code block.
"""

TURN_2_PROMPT = """Great! Now expand our Python LRU Cache project by adding statistics tracking and a `unittest` test suite. Generate the following 2 files:
1. File: src/lru_cache.py
   - Keep all existing functionality on `LRUCache` and add hit/miss tracking (`hits` and `misses` counters incremented in `get()`) plus a method `stats() -> dict` returning `{"hits": self.hits, "misses": self.misses, "size": self.size(), "capacity": self.capacity}`.
2. File: tests/test_lru_cache.py
   - Use Python's built-in `unittest` module (`unittest.TestCase`).
   - Add tests verifying:
     - LRU eviction order when capacity is exceeded and after `get()` refreshes a key.
     - `ValueError` is raised when `capacity < 1`.
     - `stats()` accurately counts cache `hits` and `misses`.
     - `delete()` removes keys properly.

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


def get_py_files(dir_path: Path):
    if not dir_path.exists():
        return []
    return [f for f in dir_path.rglob("*.py") if ".gemini-history" not in str(f)]


def main():
    print("=" * 60)
    print(" ZeroGravity Multi-Turn Test: Python LRUCache")
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
    print(">>> TURN 1: Sending initial prompt for Python LRUCache...")
    print("-" * 60)
    t0 = time.time()
    t1_res = post_json(
        f"{ROUTER_URL}/v1/chat/completions",
        {"model": "zerogravity", "messages": [{"role": "user", "content": TURN_1_PROMPT}]},
    )
    print(f"Turn 1 completed in {time.time() - t0:.1f}s")
    t1_reply = t1_res["choices"][0]["message"]["content"]

    t1_files = get_py_files(WORKSPACE_DIR)
    print(f"Workspace Python files after Turn 1 ({len(t1_files)} found):")
    for f in t1_files:
        print(f"  - {f.relative_to(WORKSPACE_DIR)}")

    print("\n" + "-" * 60)
    print(">>> TURN 2: Sending follow-up for stats() & unittest suite...")
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

    all_py_files = get_py_files(WORKSPACE_DIR)
    print(f"Total workspace Python files after Turn 2 ({len(all_py_files)} found):")
    for f in all_py_files:
        print(f"  - {f.relative_to(WORKSPACE_DIR)}")

    if len(all_py_files) >= 3:
        print(f"\n[PASS] MULTI-TURN PYTHON TEST PASSED: Generated {len(all_py_files)} Python files across 2 turns.")
    else:
        print(f"\n[FAIL] Expected >= 3 Python files total, found: {len(all_py_files)}")
        sys.exit(1)


if __name__ == "__main__":
    main()

