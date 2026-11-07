#!/usr/bin/env python3
"""
Multi-turn (2 turns) test script for ZeroGravity:
Java Spring Boot 3 Gradle REST API with automated package-to-directory path resolution.
"""

import sys
import os
import json
import time
import shutil
import urllib.request
import urllib.error
from pathlib import Path

ROUTER_URL = os.environ.get("ROUTER_URL", "http://localhost:8000")
repo_ws = Path(__file__).resolve().parent.parent.parent / "workspace"
default_ws = repo_ws if repo_ws.exists() else Path(__file__).parent / "workspace"
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", default_ws))

TURN_1_PROMPT = """Build a Spring Boot 3 Gradle REST API for a Task Management application under base package `com.example.taskmanager`.
You MUST generate the following files:
1. File: build.gradle
   - Configure Gradle with Java 17 and Spring Boot 3 plugin.
   - Include dependencies for `spring-boot-starter-web` and `spring-boot-starter-test`.
2. File: src/main/resources/application.yaml
   - Configure server port 8080 and application name `task-manager`.
3. File: Task.java
   - Entity/Model class with `package com.example.taskmanager.model;`.
   - Fields: id (Long), title (String), description (String), completed (boolean). Include constructors, getters, and setters.
4. File: TaskDto.java
   - DTO record or class with `package com.example.taskmanager.dto;`. Fields: title, description, completed.
5. File: TaskService.java
   - Service with `package com.example.taskmanager.service;`.
   - In-memory store using ConcurrentHashMap, methods: getAllTasks(), getTaskById(Long id), createTask(TaskDto dto).
6. File: TaskController.java
   - REST Controller with `package com.example.taskmanager.controller;`.
   - Endpoints: GET /api/tasks, GET /api/tasks/{id}, POST /api/tasks.
7. File: TaskManagerApplication.java
   - Main Spring Boot application class with `package com.example.taskmanager;` annotated with @SpringBootApplication.

Precede every file with a clear "File: <path>" header immediately preceding its code block.
"""

TURN_2_PROMPT = """Great! Now expand our Spring Boot Task Management application by adding error handling and automated unit tests:
1. File: TaskNotFoundException.java
   - Custom runtime exception with `package com.example.taskmanager.exception;` taking Long id.
2. File: GlobalExceptionHandler.java
   - Exception handler with `package com.example.taskmanager.controller;` annotated with @RestControllerAdvice.
   - Handles TaskNotFoundException and returns 404 NOT_FOUND with an ErrorResponse(int status, String message) record.
3. File: TaskControllerTest.java
   - Test class with `package com.example.taskmanager.controller;` using JUnit 5 `@Test` and `@WebMvcTest(TaskController.class)`.
   - Mock TaskService and verify GET /api/tasks returns 200 OK, and GET /api/tasks/999 returns 404 NOT_FOUND.

Precede every file with a clear "File: <path>" header immediately preceding its code block.
"""


def post_chat(messages, timeout=600):
    payload = json.dumps({"model": "zerogravity", "messages": messages}).encode("utf-8")
    req = urllib.request.Request(
        f"{ROUTER_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


def main():
    print("=" * 60)
    print(" ZeroGravity Multi-Turn Test: Java Spring Boot & Gradle")
    print(f" Target Router:    {ROUTER_URL}")
    print(f" Target Workspace: {WORKSPACE_DIR}")
    print("=" * 60)

    # Health check
    try:
        req = urllib.request.Request(f"{ROUTER_URL}/healthz")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"[1/4] Router reachable. Status: {data.get('status')}, Local AI: {data.get('local_ai_enabled')}")
    except Exception as e:
        print(f"ERROR: Router unreachable at {ROUTER_URL}: {e}")
        sys.exit(1)

    # Clean workspace
    if (WORKSPACE_DIR / "src").exists():
        shutil.rmtree(WORKSPACE_DIR / "src")
    for f in WORKSPACE_DIR.glob("*"):
        if f.is_file() and f.name != ".gitkeep":
            f.unlink()

    # Turn 1
    print("\n" + "-" * 60)
    print(">>> TURN 1: Requesting Spring Boot 3 Task Management Service")
    print("-" * 60)
    t1_start = time.time()
    t1_reply = post_chat([{"role": "user", "content": TURN_1_PROMPT}])
    t1_sec = round(time.time() - t1_start, 1)
    print(f"Turn 1 finished in {t1_sec}s")

    turn1_files = [f for f in WORKSPACE_DIR.rglob("*") if f.is_file() and ".gemini-history" not in str(f)]
    print(f"\nFiles generated in Turn 1 ({len(turn1_files)} found):")
    for f in turn1_files:
        print(f"  - {f.relative_to(WORKSPACE_DIR)}")

    # Turn 2
    print("\n" + "-" * 60)
    print(">>> TURN 2: Adding Exception Handling & Unit / Controller Tests")
    print("-" * 60)
    t2_start = time.time()
    t2_reply = post_chat([
        {"role": "user", "content": TURN_1_PROMPT},
        {"role": "assistant", "content": t1_reply},
        {"role": "user", "content": TURN_2_PROMPT}
    ])
    t2_sec = round(time.time() - t2_start, 1)
    print(f"Turn 2 finished in {t2_sec}s")

    all_files = [f for f in WORKSPACE_DIR.rglob("*") if f.is_file() and ".gemini-history" not in str(f)]
    test_files = [f for f in (WORKSPACE_DIR / "src" / "test").rglob("*.java")] if (WORKSPACE_DIR / "src" / "test").exists() else []
    print(f"\nTotal files generated after Turn 2 ({len(all_files)} found):")
    for f in all_files:
        print(f"  - {f.relative_to(WORKSPACE_DIR)}")

    print(f"\nTest files resolved in src/test/java ({len(test_files)} found):")
    for f in test_files:
        print(f"  [OK] {f.relative_to(WORKSPACE_DIR)}")

    if len(all_files) >= 8 and len(test_files) >= 1:
        print("\n🎉 MULTI-TURN SPRING BOOT TEST PASSED!")
    else:
        print(f"\n⚠️ FAILED: expected >= 8 files and >= 1 test file, found {len(all_files)} total, {len(test_files)} test files.")
        sys.exit(1)


if __name__ == "__main__":
    main()

