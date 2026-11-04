"""Pluggable identity providers (ADR-003).

local_dev | oidc | ldap — fail-closed in staging/production for local_dev (config).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.auth.security import create_access_token, verify_password
from maintenancehub_api.config import get_settings
from maintenancehub_api.models import (
    GroupRoleMapping,
    Role,
    RoleName,
    User,
    UserRole,
)


@dataclass
class IdentityInfo:
    email: str
    display_name: str
    external_subject: str
    groups: list[str]


class AuthProvider(Protocol):
    def authenticate_password(self, db: Session, username: str, password: str) -> IdentityInfo: ...


# In-memory OIDC mock store for tests / oidc_mock
_OIDC_CODES: dict[str, IdentityInfo] = {}
_LDAP_MOCK_USERS: dict[str, dict] = {
    "ldap.user@example.com": {
        "password": "ldap-pass",
        "display_name": "LDAP User",
        "subject": "ldap:uid=ldap.user",
        "groups": ["mh-publishers"],
    }
}


class LocalDevProvider:
    def authenticate_password(self, db: Session, username: str, password: str) -> IdentityInfo:
        user = db.query(User).filter(User.email == username.lower()).first()
        if not user or not verify_password(password, user.password_hash):
            raise ValueError("Invalid credentials")
        return IdentityInfo(
            email=user.email,
            display_name=user.display_name,
            external_subject=user.external_subject or f"local:{user.id}",
            groups=[],
        )


class OidcProvider:
    """OIDC authorization-code flow. Real token exchange stubbed; mock IdP when OIDC_MOCK=true."""

    def start_url(self, state: str) -> str:
        settings = get_settings()
        if settings.oidc_mock or not settings.oidc_issuer:
            return f"{settings.public_base_url}/api/v1/auth/oidc/mock-login?state={state}"
        params = urlencode(
            {
                "client_id": settings.oidc_client_id,
                "response_type": "code",
                "scope": settings.oidc_scopes,
                "redirect_uri": settings.oidc_redirect_uri,
                "state": state,
            }
        )
        return f"{settings.oidc_issuer.rstrip('/')}/authorize?{params}"

    def issue_mock_code(self, email: str, display_name: str, groups: list[str] | None = None) -> str:
        code = secrets.token_urlsafe(16)
        _OIDC_CODES[code] = IdentityInfo(
            email=email.lower(),
            display_name=display_name,
            external_subject=f"oidc:{email.lower()}",
            groups=groups or ["mh-viewers"],
        )
        return code

    def exchange_code(self, code: str) -> IdentityInfo:
        settings = get_settings()
        if settings.oidc_mock or code in _OIDC_CODES:
            info = _OIDC_CODES.pop(code, None)
            if not info:
                raise ValueError("Invalid or expired OIDC code")
            return info
        # Production path would call token + userinfo endpoints with client secret from env
        raise NotImplementedError(
            "Live OIDC token exchange requires OIDC_ISSUER configuration; "
            "set OIDC_MOCK=true for local/test harness"
        )

    def authenticate_password(self, db: Session, username: str, password: str) -> IdentityInfo:
        raise ValueError("Password login is not available in AUTH_MODE=oidc")


class LdapProvider:
    def authenticate_password(self, db: Session, username: str, password: str) -> IdentityInfo:
        settings = get_settings()
        if settings.ldap_mock or not settings.ldap_url:
            entry = _LDAP_MOCK_USERS.get(username.lower())
            if not entry or entry["password"] != password:
                raise ValueError("Invalid LDAP credentials")
            return IdentityInfo(
                email=username.lower(),
                display_name=entry["display_name"],
                external_subject=entry["subject"],
                groups=list(entry["groups"]),
            )
        # Live LDAP bind would use ldap3 / python-ldap with LDAPS URL from env secrets
        raise NotImplementedError(
            "Live LDAP bind requires LDAP_URL; set LDAP_MOCK=true for local/test harness"
        )


def get_provider() -> LocalDevProvider | OidcProvider | LdapProvider:
    mode = get_settings().auth_mode
    if mode == "oidc":
        return OidcProvider()
    if mode == "ldap":
        return LdapProvider()
    return LocalDevProvider()


def upsert_user_from_identity(db: Session, identity: IdentityInfo) -> User:
    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(UserRole.role))
        .filter(User.email == identity.email.lower())
        .first()
    )
    if not user:
        user = User(
            email=identity.email.lower(),
            display_name=identity.display_name,
            external_subject=identity.external_subject,
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        user.display_name = identity.display_name
        user.external_subject = identity.external_subject

    # Apply group → role mappings
    if identity.groups:
        mappings = (
            db.query(GroupRoleMapping)
            .filter(GroupRoleMapping.directory_group.in_(identity.groups))
            .all()
        )
        role_names = {m.role for m in mappings}
        if not role_names:
            role_names = {RoleName.viewer}
        # Ensure role rows
        for rn in role_names:
            role = db.query(Role).filter(Role.name == rn).first()
            if not role:
                role = Role(name=rn)
                db.add(role)
                db.flush()
            exists = (
                db.query(UserRole)
                .filter(UserRole.user_id == user.id, UserRole.role_id == role.id)
                .first()
            )
            if not exists:
                db.add(UserRole(user_id=user.id, role_id=role.id))
    elif not user.roles:
        # Default viewer
        role = db.query(Role).filter(Role.name == RoleName.viewer).first()
        if not role:
            role = Role(name=RoleName.viewer)
            db.add(role)
            db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))

    db.commit()
    return (
        db.query(User)
        .options(joinedload(User.roles).joinedload(UserRole.role))
        .filter(User.id == user.id)
        .one()
    )


def issue_user_token(user: User) -> str:
    return create_access_token(user.id, extra={"email": user.email, "typ": "user"})
