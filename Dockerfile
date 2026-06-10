FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    APP_ENV=production \
    PORT=8080 \
    RISKUA_DEBTORS_BROWSER_HEADLESS=true \
    RISKUA_DEBTORS_BROWSER_CHANNEL=

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && python -m playwright install --with-deps chromium \
    && chmod -R 755 /ms-playwright

COPY . .

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/logs /app/data/checks \
    && chown -R app:app /app /ms-playwright

USER app

EXPOSE 8080

CMD ["python", "main.py"]
