"""MaintenanceHub API entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from maintenancehub_api.api import (
    admin_jobs,
    auth,
    calendar_tokens,
    catalog,
    dashboard,
    events,
    health,
    notifications,
    subscriptions,
)
from maintenancehub_api.config import get_settings
from maintenancehub_api.db import Base, SessionLocal, engine
from maintenancehub_api import models as _models  # noqa: F401 — register models on Base.metadata
from maintenancehub_api.domain.notifications import ensure_default_templates
from maintenancehub_api.seed import seed_demo

logger = logging.getLogger("maintenancehub")


def _ensure_sqlite_dir() -> None:
    settings = get_settings()
    if settings.is_sqlite and ":///" in settings.database_url:
        raw = settings.database_url.split(":///", 1)[1]
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    _ensure_sqlite_dir()
    # Dev convenience: create tables if migrations not yet applied
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_default_templates(db)
        if settings.seed_demo_data and settings.auth_mode == "local_dev":
            seed_demo(db)
            logger.info("Demo data seeded (local_dev)")
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    # Validate settings (fail-closed) at import/boot
    settings = get_settings()

    app = FastAPI(
        title="MaintenanceHub API",
        version="0.1.0",
        description=(
            "Internal Maintenance & Outage Communication Platform. "
            "Not a monitoring product — /healthz and /readyz are platform probes only."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(_request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": "about:blank",
                "title": "HTTP Error",
                "status": exc.status_code,
                "detail": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "type": "about:blank",
                "title": "Validation Error",
                "status": 422,
                "detail": "Request validation failed",
                "errors": exc.errors(),
            },
        )

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(catalog.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(subscriptions.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(admin_jobs.router, prefix="/api/v1")
    app.include_router(calendar_tokens.router, prefix="/api/v1")

    return app


app = create_app()
