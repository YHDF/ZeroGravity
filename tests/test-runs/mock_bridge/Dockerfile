FROM python:3.11-slim

WORKDIR /app
COPY server.py .
COPY fixtures/ ./fixtures/

ENV PORT=5000
EXPOSE 5000

RUN useradd --create-home --uid 10001 mock
USER mock

HEALTHCHECK --interval=5s --timeout=3s --retries=10 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=2)"

CMD ["python", "server.py"]

