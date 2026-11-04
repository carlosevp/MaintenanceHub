"""FastAPI dependencies for auth and DB."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.auth.security import decode_access_token
from maintenancehub_api.db import get_db
from maintenancehub_api.models import RoleName, User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthUser:
    id: str
    email: str
    display_name: str
    roles: set[str]

    def has_role(self, *names: str) -> bool:
        return bool(self.roles.intersection(names))

    @property
    def is_admin(self) -> bool:
        return RoleName.platform_administrator.value in self.roles

    @property
    def can_publish(self) -> bool:
        return self.has_role(
            RoleName.publisher.value,
            RoleName.application_owner.value,
            RoleName.platform_administrator.value,
        )


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthUser:
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(creds.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(UserRole.role))
        .filter(User.id == user_id, User.is_active.is_(True))
        .first()
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    roles = {ur.role.name.value for ur in user.roles if ur.role}
    return AuthUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        roles=roles,
    )


def require_roles(*allowed: str):
    def _dep(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if user.is_admin:
            return user
        if not user.has_role(*allowed):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _dep
