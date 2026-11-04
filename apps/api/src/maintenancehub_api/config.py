"""Application settings with fail-closed auth guards."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AuthMode = Literal["local_dev", "oidc", "ldap"]
EnvironmentName = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: EnvironmentName = "development"
    auth_mode: AuthMode = "local_dev"
    allow_local_auth: bool = False

    database_url: str = "sqlite:///./data/maintenancehub.db"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_cors_origins: str = "http://localhost:5173,http://localhost:3000"

    jwt_secret: str = "change-me-local-dev-only"
    jwt_expire_minutes: int = 480
    jwt_algorithm: str = "HS256"

    smtp_enabled: bool = False
    bridge_enabled: bool = False
    servicenow_enabled: bool = False
    seed_demo_data: bool = True

    @field_validator("auth_mode", mode="before")
    @classmethod
    def normalize_auth_mode(cls, value: str) -> str:
        return str(value).strip().lower()

    @model_validator(mode="after")
    def fail_closed_local_auth(self) -> Settings:
        if self.auth_mode == "local_dev" and self.environment in {"staging", "production"}:
            if not self.allow_local_auth:
                raise ValueError(
                    "AUTH_MODE=local_dev is refused when ENVIRONMENT is "
                    f"{self.environment}. Set ALLOW_LOCAL_AUTH=true only as audited break-glass."
                )
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
