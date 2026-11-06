FROM python:3.12-slim AS base

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY apps/api/pyproject.toml /app/apps/api/pyproject.toml
COPY apps/api/src /app/apps/api/src
COPY db /app/db
COPY scripts /app/scripts

RUN pip install --no-cache-dir /app/apps/api \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/api/src \
    DATABASE_URL=sqlite:////app/data/maintenancehub.db \
    ENVIRONMENT=development \
    AUTH_MODE=local_dev \
    PATH="/home/appuser/.local/bin:${PATH}"

USER 10001
WORKDIR /app
EXPOSE 8000
CMD ["uvicorn", "maintenancehub_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
