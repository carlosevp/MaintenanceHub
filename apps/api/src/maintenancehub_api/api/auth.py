from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.auth.providers import (
    LdapProvider,
    OidcProvider,
    get_provider,
    issue_user_token,
    upsert_user_from_identity,
)
from maintenancehub_api.auth.security import create_access_token
from maintenancehub_api.config import get_settings
from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, authenticate_service_secret, get_current_user
from maintenancehub_api.domain.audit import write_audit
from maintenancehub_api.models import User, UserRole
from maintenancehub_api.schemas.auth import LoginRequest, MeResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

# ephemeral OIDC state store (process-local; fine for mock/dev)
_OIDC_STATES: set[str] = set()


class ServiceLoginRequest(BaseModel):
    client_id: str
    client_secret: str = Field(min_length=1)


class MockOidcLogin(BaseModel):
    email: str = "oidc.user@example.com"
    display_name: str = "OIDC User"
    groups: list[str] = Field(default_factory=lambda: ["mh-viewers"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    settings = get_settings()
    provider = get_provider()

    if settings.auth_mode == "local_dev":
        try:
            identity = provider.authenticate_password(db, body.email, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        user = (
            db.query(User)
            .options(joinedload(User.roles).joinedload(UserRole.role))
            .filter(User.email == identity.email)
            .first()
        )
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User inactive")
        return TokenResponse(access_token=issue_user_token(user))

    if settings.auth_mode == "ldap":
        if not isinstance(provider, LdapProvider):
            provider = LdapProvider()
        try:
            identity = provider.authenticate_password(db, body.email, body.password)
        except (ValueError, NotImplementedError) as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        user = upsert_user_from_identity(db, identity)
        write_audit(
            db,
            actor_id=user.id,
            action="login",
            entity_type="user",
            entity_id=user.id,
            summary={"mode": "ldap"},
        )
        return TokenResponse(access_token=issue_user_token(user))

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Password login is not available in AUTH_MODE={settings.auth_mode}; use OIDC start",
    )


@router.get("/oidc/start")
def oidc_start() -> RedirectResponse:
    settings = get_settings()
    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=400, detail="AUTH_MODE is not oidc")
    state = secrets.token_urlsafe(16)
    _OIDC_STATES.add(state)
    provider = OidcProvider()
    return RedirectResponse(provider.start_url(state))


@router.get("/oidc/mock-login")
def oidc_mock_login(
    state: str,
    email: str = "oidc.user@example.com",
    display_name: str = "OIDC User",
    groups: str = "mh-viewers",
) -> RedirectResponse:
    """Dev/test mock IdP — only when OIDC_MOCK=true."""
    settings = get_settings()
    if not settings.oidc_mock:
        raise HTTPException(status_code=404, detail="OIDC mock disabled")
    if state not in _OIDC_STATES:
        raise HTTPException(status_code=400, detail="Invalid state")
    provider = OidcProvider()
    code = provider.issue_mock_code(
        email=email,
        display_name=display_name,
        groups=[g.strip() for g in groups.split(",") if g.strip()],
    )
    return RedirectResponse(
        f"{settings.public_base_url}/api/v1/auth/oidc/callback?code={code}&state={state}"
    )


@router.get("/oidc/callback", response_model=TokenResponse)
def oidc_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    if settings.auth_mode != "oidc":
        raise HTTPException(status_code=400, detail="AUTH_MODE is not oidc")
    if state not in _OIDC_STATES:
        raise HTTPException(status_code=400, detail="Invalid state")
    _OIDC_STATES.discard(state)
    provider = OidcProvider()
    try:
        identity = provider.exchange_code(code)
    except (ValueError, NotImplementedError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = upsert_user_from_identity(db, identity)
    write_audit(
        db,
        actor_id=user.id,
        action="login",
        entity_type="user",
        entity_id=user.id,
        summary={"mode": "oidc"},
    )
    return TokenResponse(access_token=issue_user_token(user))


@router.post("/service/token", response_model=TokenResponse)
def service_token(body: ServiceLoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    cred = authenticate_service_secret(db, body.client_id, body.client_secret)
    token = create_access_token(
        cred.client_id,
        extra={"typ": "service", "scopes": cred.scopes or []},
    )
    return TokenResponse(access_token=token)


@router.post("/logout")
def logout() -> dict[str, str]:
    return {"message": "ok"}


@router.get("/me", response_model=MeResponse)
def me(user: AuthUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        roles=sorted(user.roles) if not user.is_service else sorted(f"scope:{s}" for s in user.scopes),
    )
