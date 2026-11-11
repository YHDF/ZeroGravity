FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# Install lightweight virtual X11 + noVNC so headed Google sign-in works inside Docker
# without requiring Python or Playwright on the host machine.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        xvfb \
        x11vnc \
        novnc \
        websockify \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --ignore-installed -r requirements.txt \
    && playwright install chromium

COPY . .
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

ENV BROWSER_PROFILE_DIR=/data/browser_profile
ENV PORT=5000
ENV NOVNC_PORT=6080

EXPOSE 5000 6080

ENTRYPOINT ["/app/entrypoint.sh"]
