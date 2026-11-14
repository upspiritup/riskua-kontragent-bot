# Образ нової версії RiskUA: лише Python і залежності з pyproject.toml, без браузера.
# Збирається з кореня репозиторію: docker compose build (див. docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/riskua

COPY pyproject.toml ./
COPY riskua ./riskua
RUN pip install .

RUN useradd --system --no-create-home riskua
USER riskua

CMD ["python", "-m", "riskua.bot"]
