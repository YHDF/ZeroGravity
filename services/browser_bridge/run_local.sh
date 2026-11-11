#!/usr/bin/env bash
# Runs the ZeroGravity Gemini browser bridge inside Docker (default, zero host Python
# dependencies required) or natively with --native.
#
# Examples:
#   # Sign in to a specific Google account (opens interactive noVNC viewer on http://localhost:6080)
#   ./services/browser_bridge/run_local.sh --headed
#
#   # Sign in with a dedicated profile directory for a specific Google account
#   ./services/browser_bridge/run_local.sh --profile-dir "$HOME/.zg-work" --headed
#
#   # Run headless in Docker reusing that signed-in Google account
#   ./services/browser_bridge/run_local.sh --profile-dir "$HOME/.zg-work"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PROFILE_DIR="${REPO_ROOT}/data/browser_profile"
HEADED="false"
PORT="5000"
NOVNC_PORT="6080"
NATIVE="false"
BROWSER_EXECUTABLE="${BROWSER_EXECUTABLE_PATH:-}"
CHANNEL="${BROWSER_CHANNEL:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --headed|-Headed)
            HEADED="true"
            shift
            ;;
        --profile-dir|-ProfileDir)
            PROFILE_DIR="$2"
            shift 2
            ;;
        --port|-Port)
            PORT="$2"
            shift 2
            ;;
        --novnc-port|-NoVncPort)
            NOVNC_PORT="$2"
            shift 2
            ;;
        --native|-Native)
            NATIVE="true"
            shift
            ;;
        --browser-executable|-BrowserExecutable)
            BROWSER_EXECUTABLE="$2"
            shift 2
            ;;
        --channel|-Channel)
            CHANNEL="$2"
            shift 2
            ;;
        -h|--help)
            sed -n '2,14p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

mkdir -p "$PROFILE_DIR"
RESOLVED_PROFILE_DIR="$(cd "$PROFILE_DIR" && pwd)"

WORKSPACE_DIR="$REPO_ROOT/workspace"
mkdir -p "$WORKSPACE_DIR"
RESOLVED_WORKSPACE_DIR="$(cd "$WORKSPACE_DIR" && pwd)"

if [[ "$NATIVE" == "false" && -z "$BROWSER_EXECUTABLE" && -z "$CHANNEL" ]]; then
    HEADLESS_VAL="true"
    if [[ "$HEADED" == "true" ]]; then
        HEADLESS_VAL="false"
    fi
    IMAGE_NAME="zerogravity/gemini-bridge:local"

    echo "Building Docker image $IMAGE_NAME ..."
    docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"

    docker rm -f gemini-bridge >/dev/null 2>&1 || true

    echo "======================================================================"
    echo "Starting Dockerized Gemini Bridge on http://localhost:${PORT}"
    echo "  profile : ${RESOLVED_PROFILE_DIR}"
    echo "  headless: ${HEADLESS_VAL}"
    if [[ "$HEADED" == "true" ]]; then
        VNC_URL="http://localhost:${NOVNC_PORT}/vnc.html?autoconnect=true&resize=scale"
        echo "  login UI: ${VNC_URL}"
        echo "  -> Open the URL above in your browser, sign into your Google account,"
        echo "     then press Ctrl+C here when finished to save the session."
        (
            sleep 3
            if command -v xdg-open >/dev/null 2>&1; then
                xdg-open "$VNC_URL" >/dev/null 2>&1 || true
            elif command -v open >/dev/null 2>&1; then
                open "$VNC_URL" >/dev/null 2>&1 || true
            elif command -v cmd.exe >/dev/null 2>&1; then
                cmd.exe /c start "" "$VNC_URL" >/dev/null 2>&1 || true
            fi
        ) &
    fi
    echo "======================================================================"

    DOCKER_ARGS=(
        run --rm -it
        --name gemini-bridge
        -p "${PORT}:5000"
        -p "${NOVNC_PORT}:6080"
        -e "BROWSER_PROFILE_DIR=/data/browser_profile"
        -e "ZEROGRAVITY_HEADLESS=${HEADLESS_VAL}"
        -e "PORT=5000"
        -e "NOVNC_PORT=6080"
        -v "${RESOLVED_PROFILE_DIR}:/data/browser_profile"
        -v "${RESOLVED_WORKSPACE_DIR}:/workspace"
    )

    if docker network ls --filter "name=0g_zerogravity-net" -q | grep -q .; then
        DOCKER_ARGS+=(--network "0g_zerogravity-net")
    fi

    exec docker "${DOCKER_ARGS[@]}" "$IMAGE_NAME"
fi

# Optional Native Host Mode
cd "$SCRIPT_DIR"
VENV="$SCRIPT_DIR/.venv"
PYTHON="$VENV/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo "Creating virtual environment in $VENV ..."
    python3 -m venv "$VENV"
    "$PYTHON" -m pip install --upgrade pip
    "$PYTHON" -m pip install -r requirements.txt
fi

if [[ -z "$BROWSER_EXECUTABLE" && -z "$CHANNEL" ]]; then
    "$PYTHON" -m playwright install chromium
fi

export BROWSER_PROFILE_DIR="$RESOLVED_PROFILE_DIR"
export BROWSER_EXECUTABLE_PATH="$BROWSER_EXECUTABLE"
export BROWSER_CHANNEL="$CHANNEL"
export ZEROGRAVITY_HEADLESS="$( [[ "$HEADED" == "true" ]] && echo "false" || echo "true" )"
export PORT="$PORT"

exec "$PYTHON" server.py

