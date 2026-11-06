"""Read-only public + internal banner API — minimal DTO, no secrets (M12/M18).

`/api/v1/public/banner` — browser embeds (CORS, cache, rate-limit).
`/api/v1/internal/banner` — OpenShift-stable cluster DNS path (same DTO).

Auth is optional. When a service credential authenticates, it must include
`banner:read`. Never put long-lived `client_secret` values in browsers.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from maintenancehub_api.config import get_settings
from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user
from maintenancehub_api.domain import banner as banner_domain

router = APIRouter(tags=["banner"])
_bearer = HTTPBearer(auto_error=False)

# Simple in-process rate limit for public embeds (per client IP).
_RATE_LOCK = Lock()
_RATE_HITS: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


def _check_rate_limit(request: Request) -> None:
    settings = get_settings()
    limit = max(1, int(getattr(settings, "banner_rate_limit_per_minute", 60)))
    window = 60.0
    ip = _client_ip(request)
    now = time.monotonic()
    with _RATE_LOCK:
        q = _RATE_HITS[ip]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(status_code=429, detail="Banner rate limit exceeded")
        q.append(now)


def optional_banner_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Session = Depends(get_db),
) -> AuthUser | None:
    if creds is None or not creds.credentials:
        return None
    return get_current_user(creds, db)


def _authorize(user: AuthUser | None) -> None:
    if user is not None and user.is_service and not user.has_scope("banner:read"):
        raise HTTPException(status_code=403, detail="banner:read required")


def _apply_cache_headers(response: Response) -> None:
    settings = get_settings()
    max_age = max(0, int(getattr(settings, "banner_cache_max_age_seconds", 30)))
    response.headers["Cache-Control"] = f"public, max-age={max_age}"
    response.headers["Vary"] = "Authorization, Origin"
    # Help hosts fail closed on accidental caching of auth'd responses by CDNs
    response.headers["X-Content-Type-Options"] = "nosniff"


def _resolve_advance_hours(advance_hours: float | None) -> float:
    settings = get_settings()
    default = float(getattr(settings, "banner_advance_hours", 24.0))
    value = default if advance_hours is None else float(advance_hours)
    return max(0.0, min(value, 168.0))


def _banner_payload(
    *,
    db: Session,
    application_key: str,
    environment_key: str | None,
    advance_hours: float | None,
) -> list[dict]:
    hours = _resolve_advance_hours(advance_hours)
    return banner_domain.list_banner_messages(
        db,
        application_key=application_key,
        environment_key=environment_key,
        advance_hours=hours,
    )


@router.get(
    "/public/banner",
    summary="Public banner messages (browser embeds)",
    response_description="Minimal confirmed maintenance/outage notices for one app(+env).",
)
def public_banner(
    request: Request,
    response: Response,
    application_key: str = Query(..., min_length=1, max_length=128),
    environment_key: str | None = Query(default=None, max_length=64),
    advance_hours: float | None = Query(
        default=None,
        ge=0,
        le=168,
        description="How far ahead to show upcoming confirmed windows (default from BANNER_ADVANCE_HOURS).",
    ),
    user: AuthUser | None = Depends(optional_banner_user),
    db: Session = Depends(get_db),
    origin: Annotated[str | None, Header()] = None,  # noqa: ARG001 — documented for CORS/Vary
) -> list[dict]:
    """Confirmed notices for exact ``application_key`` (+ optional ``environment_key``).

    - Auth optional. Service tokens need ``banner:read``.
    - Never returns approved-only windows as outages.
    - Never returns description / timeline / secrets.
    - CORS + short Cache-Control; rate-limited per client IP.
    """
    _authorize(user)
    _check_rate_limit(request)
    _apply_cache_headers(response)
    return _banner_payload(
        db=db,
        application_key=application_key,
        environment_key=environment_key,
        advance_hours=advance_hours,
    )


@router.get(
    "/internal/banner",
    summary="Internal banner messages (OpenShift / cluster DNS)",
    response_description="Same minimal DTO as /public/banner for stable in-cluster callers.",
)
def internal_banner(
    response: Response,
    application_key: str = Query(..., min_length=1, max_length=128),
    environment_key: str | None = Query(default=None, max_length=64),
    advance_hours: float | None = Query(default=None, ge=0, le=168),
    user: AuthUser | None = Depends(optional_banner_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """OpenShift-stable path — prefer service DNS, e.g.

    ``http://maintenancehub-api:8000/api/v1/internal/banner?...``

    Same filtering and public DTO as ``/public/banner``. Not rate-limited like
    the public edge (cluster mesh policy applies). Auth optional; service
    tokens still require ``banner:read``.
    """
    _authorize(user)
    # Shorter cache for internal polling BFFs
    response.headers["Cache-Control"] = "private, max-age=15"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return _banner_payload(
        db=db,
        application_key=application_key,
        environment_key=environment_key,
        advance_hours=advance_hours,
    )
