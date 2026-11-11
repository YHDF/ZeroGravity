#!/usr/bin/env bash
set -euo pipefail

if [[ "${ZEROGRAVITY_HEADLESS:-true}" == "false" ]]; then
    export DISPLAY=:99
    rm -f /tmp/.X99-lock

    echo "[gemini-bridge] Starting virtual X11 display (Xvfb :99)..."
    # Start Xvfb, x11vnc, and websockify in detached sessions (setsid) so pressing Ctrl+C
    # does not kill the X11 server before Chromium flushes its SQLite cookie store.
    setsid Xvfb :99 -screen 0 1280x800x24 -ac +extension GLX +render -noreset >/dev/null 2>&1 &
    sleep 1

    echo "[gemini-bridge] Starting VNC + noVNC web viewer on port ${NOVNC_PORT:-6080}..."
    setsid x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -quiet >/dev/null 2>&1 &
    setsid websockify --web=/usr/share/novnc/ "${NOVNC_PORT:-6080}" localhost:5900 >/dev/null 2>&1 &

    echo "======================================================================"
    echo "  HEADED LOGIN MODE ACTIVE (noVNC)"
    echo "  Open in your browser to sign into your Google account:"
    echo "    http://localhost:${NOVNC_PORT:-6080}/vnc.html?autoconnect=true&resize=scale"
    echo "  Once signed in, watch for '[Google Sign-In Detected]' in the logs"
    echo "  before pressing Ctrl+C."
    echo "======================================================================"
fi

if [[ $# -gt 0 ]]; then
    exec "$@"
fi

exec python server.py
