"""Application settings with fail-closed auth guards."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AuthMode = Literal["local_dev", "oidc", "ldap"]
EnvironmentName = Literal["development", "staging", "production"]
ExperienceProfile = Literal["essentials", "team", "enterprise"]


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
    api_cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

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
    bridge_subject_template: str = "[MH-ROUTE:{channel_key}] {title}"

    # ServiceNow (disabled by default — null/fixture adapter in local_dev)
    servicenow_enabled: bool = False
    servicenow_instance_url: str = ""
    servicenow_username: str = ""
    servicenow_password: str = ""  # prefer OpenShift Secret / env, never commit
    servicenow_api_path: str = "/api/now/table/change_request"
    servicenow_query: str = "active=true"
    servicenow_use_fixture: bool = True  # local_dev: load fixture JSON instead of HTTP
    servicenow_fixture_path: str = "fixtures/servicenow_changes.json"
    servicenow_poll_interval_seconds: int = 300
    # cancel | unmatched — what to do when SN state is cancelled and no mapped event policy
    servicenow_cancel_policy: str = "cancel_event"

    # OIDC (M11) — secrets via env
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = "http://localhost:8000/api/v1/auth/oidc/callback"
    oidc_scopes: str = "openid profile email"
    # When true, OIDC uses in-memory mock IdP (tests / local without real IdP)
    oidc_mock: bool = False

    # LDAP/LDAPS
    ldap_url: str = ""  # e.g. ldaps://ldap.example.com:636
    ldap_bind_dn: str = ""
    ldap_bind_password: str = ""
    ldap_user_base: str = ""
    ldap_user_filter: str = "(uid={username})"
    ldap_group_attr: str = "memberOf"
    ldap_mock: bool = False

    seed_demo_data: bool = True

    # M17 — Essentials | Team | Enterprise (centralized capability registry).
    # Default Essentials: never silently Enterprise. Unknown values fail closed.
    experience_profile: ExperienceProfile = "essentials"

    job_lease_seconds: int = 30
    job_max_attempts: int = 5
    delivery_max_attempts: int = 5
    worker_id: str = ""

    public_base_url: str = "http://localhost:8000"

    # M18 — public / internal banner embeds
    banner_advance_hours: float = 24.0
    banner_cache_max_age_seconds: int = 30
    banner_rate_limit_per_minute: int = 60

    @field_validator("auth_mode", mode="before")
    @classmethod
    def normalize_auth_mode(cls, value: str) -> str:
        return str(value).strip().lower()

    @field_validator("experience_profile", mode="before")
    @classmethod
    def normalize_experience_profile(cls, value: object) -> str:
        from maintenancehub_api.domain.experience import normalize_profile

        return normalize_profile(None if value is None else str(value))

    @model_validator(mode="after")
    def fail_closed_local_auth(self) -> Settings:
        if self.auth_mode == "local_dev" and self.environment in {"staging", "production"}:
            if not self.allow_local_auth:
                raise ValueError(
                    "AUTH_MODE=local_dev is refused when ENVIRONMENT is "
                    f"{self.environment}. Set ALLOW_LOCAL_AUTH=true only as audited break-glass."
                )
        weak_secrets = {
            "change-me-local-dev-only",
            "change-me",
            "local-compose-secret",
            "test-secret",
        }
        if self.environment in {"staging", "production"} and self.jwt_secret in weak_secrets:
            raise ValueError(
                "JWT_SECRET must be set to a strong unique value when "
                f"ENVIRONMENT={self.environment}."
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
