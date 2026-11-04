"""Application settings with fail-closed auth guards."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
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
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "maintenancehub@example.com"
    smtp_use_tls: bool = False

    bridge_enabled: bool = False
    bridge_mailbox: str = ""
    # Subject template for Teams via email bridge. {channel_key} and {title} supported.
    bridge_subject_template: str = "[MH-ROUTE:{channel_key}] {title}"

    servicenow_enabled: bool = False
    seed_demo_data: bool = True

    # Job / notification worker
    job_lease_seconds: int = 30
    job_max_attempts: int = 5
    delivery_max_attempts: int = 5
    worker_id: str = ""

    public_base_url: str = "http://localhost:8000"

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

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()
