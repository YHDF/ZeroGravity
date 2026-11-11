#!/usr/bin/env bash
# Runs the multi-turn Python LRUCache E2E test using Docker (zero local Python required).
# Usage:
#   ./tests/test-runs/python/test_multi_turn_python.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
WORKSPACE_DIR="${WORKSPACE_DIR:-$REPO_ROOT/workspace}"
ROUTER_URL="${ROUTER_URL:-http://host.docker.internal:8000}"

mkdir -p "$WORKSPACE_DIR"

exec docker run --rm \
    --add-host=host.docker.internal:host-gateway \
    -e "ROUTER_URL=${ROUTER_URL}" \
    -e "WORKSPACE_DIR=/workspace" \
    -v "${REPO_ROOT}:/repo:ro" \
    -v "${WORKSPACE_DIR}:/workspace" \
    python:3.11-slim \
    python /repo/tests/test-runs/python/test_multi_turn_python.py

