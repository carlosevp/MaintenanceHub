FROM python:3.12-slim AS base

RUN useradd --create-home --uid 10001 appuser
WORKDIR /app

COPY apps/api/pyproject.toml /app/apps/api/pyproject.toml
COPY apps/api/src /app/apps/api/src
COPY apps/worker/pyproject.toml /app/apps/worker/pyproject.toml
COPY apps/worker/src /app/apps/worker/src

RUN pip install --no-cache-dir /app/apps/api \
    && pip install --no-cache-dir /app/apps/worker \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

USER 10001
ENV PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////app/data/maintenancehub.db \
    WORKER_POLL_SECONDS=15

CMD ["python", "-m", "maintenancehub_worker.main"]
