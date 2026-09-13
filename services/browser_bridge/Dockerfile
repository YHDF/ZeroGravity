FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

ENV BROWSER_PROFILE_DIR=/data/browser_profile
ENV PORT=5000

EXPOSE 5000

CMD ["python", "server.py"]
