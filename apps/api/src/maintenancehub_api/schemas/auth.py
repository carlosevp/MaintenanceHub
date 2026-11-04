from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from maintenancehub_api.schemas.common import ORMModel


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(ORMModel):
    id: str
    email: EmailStr
    display_name: str
    roles: list[str]
