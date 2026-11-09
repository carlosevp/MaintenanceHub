"""M15 — Enterprise administration workspace APIs (overview, users, grants, secrets)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.api.experience import require_capability
from maintenancehub_api.config import get_settings
from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, require_roles
from maintenancehub_api.domain.audit import write_audit
from maintenancehub_api.domain.authz import grant_user_on_application
from maintenancehub_api.models import (
    Application,
    ApplicationGrant,
    CsvImportJob,
    DeliveryStatus,
    Dependency,
    Environment,
    InfraComponent,
    Job,
    JobStatus,
    NotificationDelivery,
    RoleName,
    Service,
    SnUnmatchedRecord,
    User,
    UserRole,
)

def _require_admin_workspace() -> None:
    """Router-level gate — Essentials/Team fail closed (no silent Enterprise admin)."""
    require_capability("admin_workspace")


router = APIRouter(
    prefix="/admin",
    tags=["admin-workspace"],
    dependencies=[Depends(_require_admin_workspace)],
)
_ADMIN = RoleName.platform_administrator.value


@router.get("/overview")
def admin_overview(
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(_ADMIN)),
) -> dict[str, Any]:
    """Summary dashboard for the administration workspace."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    jobs_by_status = {
        st.value: db.query(Job).filter(Job.status == st).count() for st in JobStatus
    }
    return {
        "as_of": now.isoformat(),
        "catalog": {
            "applications": db.query(Application).count(),
            "infra_components": db.query(InfraComponent).count(),
            "services": db.query(Service).count(),
            "dependencies": db.query(Dependency).count(),
        },
        "integrations": {
            "smtp_enabled": s.smtp_enabled,
            "bridge_enabled": s.bridge_enabled,
            "servicenow_enabled": s.servicenow_enabled,
            "servicenow_use_fixture": s.servicenow_use_fixture,
            "auth_mode": s.auth_mode,
        },
        "servicenow": {
            "unmatched_open": db.query(SnUnmatchedRecord)
            .filter(SnUnmatchedRecord.status == "open")
            .count(),
            "last_poll_job": _last_job_summary(db, "sn_poll"),
        },
        "imports": {
            "total": db.query(CsvImportJob).count(),
            "last_committed": _last_import_summary(db),
        },
        "jobs": jobs_by_status,
        "deliveries": {
            "total": db.query(NotificationDelivery).count(),
            "failed": db.query(NotificationDelivery)
            .filter(
                NotificationDelivery.status.in_([DeliveryStatus.failed, DeliveryStatus.dead])
            )
            .count(),
        },
        "users": db.query(User).count(),
        "grants": db.query(ApplicationGrant).count(),
        "note": "Integration secrets are never included in this overview",
    }


def _last_job_summary(db: Session, job_type: str) -> dict[str, Any] | None:
    row = (
        db.query(Job)
        .filter(Job.job_type == job_type)
        .order_by(Job.created_at.desc())
        .first()
    )
    if not row:
        return None
    return {
        "id": row.id,
        "status": row.status.value,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_error": row.last_error,
    }


def _last_import_summary(db: Session) -> dict[str, Any] | None:
    row = (
        db.query(CsvImportJob)
        .filter(CsvImportJob.status == "committed")
        .order_by(CsvImportJob.committed_at.desc())
        .first()
    )
    if not row:
        return None
    return {
        "id": row.id,
        "kind": row.kind,
        "filename": row.filename,
        "committed_at": row.committed_at.isoformat() if row.committed_at else None,
    }


@router.get("/secrets-status")
def secrets_status(
    _: AuthUser = Depends(require_roles(_ADMIN)),
) -> dict[str, Any]:
    """Configuration status — secrets never returned; OpenShift/env only."""
    s = get_settings()
    return {
        "deployment_note": (
            "Secrets and enterprise credentials are configured via environment variables "
            "or OpenShift Secrets. This API never returns raw secret values and does not "
            "provide an arbitrary secret editor."
        ),
        "runtime_editable": [
            "notification templates (subject/body)",
            "application grants and group role mappings",
            "manual dependencies and infra components",
            "CSV import jobs",
            "ServiceNow unmatched resolve / poll-now enqueue",
            "service credentials (generate/rotate/revoke; secret shown once)",
            "job retry for failed/dead jobs",
        ],
        "deployment_only": [
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USER",
            "SMTP_PASSWORD",
            "SMTP_FROM",
            "SMTP_ENABLED",
            "BRIDGE_ENABLED",
            "BRIDGE_MAILBOX",
            "BRIDGE_SUBJECT_TEMPLATE",
            "SERVICENOW_ENABLED",
            "SERVICENOW_INSTANCE_URL",
            "SERVICENOW_USERNAME",
            "SERVICENOW_PASSWORD",
            "SERVICENOW_QUERY",
            "SERVICENOW_POLL_INTERVAL_SECONDS",
            "AUTH_MODE",
            "OIDC_*",
            "LDAP_*",
            "JWT_SECRET",
        ],
        "openshift_only": [
            "SMTP_PASSWORD",
            "SERVICENOW_PASSWORD",
            "OIDC_CLIENT_SECRET",
            "LDAP_BIND_PASSWORD",
            "JWT_SECRET",
        ],
        "smtp": {
            "enabled": s.smtp_enabled,
            "host": s.smtp_host,
            "port": s.smtp_port,
            "from_address": s.smtp_from,
            "user_configured": bool(s.smtp_user),
            "password_configured": bool(s.smtp_password),
            "ui_editable": False,
        },
        "bridge": {
            "enabled": s.bridge_enabled,
            "mailbox": s.bridge_mailbox or None,
            "subject_template": s.bridge_subject_template,
            "ui_editable": False,
            "note": (
                "Teams destinations use the Power Automate email bridge only — "
                "no Graph/Teams APIs. SMTP acceptance ≠ confirmed Teams delivery."
            ),
        },
        "servicenow": {
            "enabled": s.servicenow_enabled,
            "instance_url": s.servicenow_instance_url or None,
            "username_configured": bool(s.servicenow_username),
            "password_configured": bool(s.servicenow_password),
            "use_fixture": s.servicenow_use_fixture,
            "fixture_path": s.servicenow_fixture_path,
            "query": s.servicenow_query,
            "poll_interval_seconds": s.servicenow_poll_interval_seconds,
            "ui_editable": False,
        },
        "auth": {
            "mode": s.auth_mode,
            "oidc_issuer": s.oidc_issuer or None,
            "oidc_client_id": s.oidc_client_id or None,
            "oidc_client_secret_configured": bool(s.oidc_client_secret),
            "ldap_url": s.ldap_url or None,
            "ldap_bind_configured": bool(s.ldap_bind_dn),
            "ldap_bind_password_configured": bool(s.ldap_bind_password),
            "jwt_secret_is_default": s.jwt_secret == "change-me-local-dev-only",
            "ui_editable": False,
            "note": (
                "Live AD/OIDC requires deployment-time IdP configuration — "
                "no fake production AD login"
            ),
        },
    }


@router.get("/users")
def list_users(
    q: str | None = None,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(_ADMIN)),
) -> list[dict[str, Any]]:
    query = db.query(User).options(joinedload(User.roles).joinedload(UserRole.role))
    if q:
        like = f"%{q}%"
        query = query.filter((User.email.ilike(like)) | (User.display_name.ilike(like)))
    rows = query.order_by(User.email).limit(200).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "display_name": u.display_name,
            "is_active": u.is_active,
            "roles": sorted({ur.role.name.value for ur in u.roles if ur.role}),
        }
        for u in rows
    ]


class GrantIn(BaseModel):
    user_id: str
    application_id: str
    role: str = Field(default="publisher", pattern="^(publisher|application_owner)$")


@router.get("/grants")
def list_grants(
    application_id: str | None = None,
    user_id: str | None = None,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(_ADMIN)),
) -> list[dict[str, Any]]:
    q = db.query(ApplicationGrant)
    if application_id:
        q = q.filter(ApplicationGrant.application_id == application_id)
    if user_id:
        q = q.filter(ApplicationGrant.user_id == user_id)
    rows = q.order_by(ApplicationGrant.application_id).limit(500).all()
    return [
        {
            "id": g.id,
            "user_id": g.user_id,
            "directory_group": g.directory_group,
            "application_id": g.application_id,
            "role": g.role,
        }
        for g in rows
    ]


@router.post("/grants", status_code=201)
def create_grant(
    body: GrantIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(_ADMIN)),
) -> dict[str, Any]:
    if not db.get(User, body.user_id):
        raise HTTPException(status_code=404, detail="User not found")
    if not db.get(Application, body.application_id):
        raise HTTPException(status_code=404, detail="Application not found")
    row = grant_user_on_application(
        db, user_id=body.user_id, application_id=body.application_id, role=body.role
    )
    db.commit()
    db.refresh(row)
    write_audit(
        db,
        actor_id=user.id,
        action="grant.create",
        entity_type="application_grant",
        entity_id=row.id,
        summary={
            "user_id": body.user_id,
            "application_id": body.application_id,
            "role": body.role,
        },
    )
    return {
        "id": row.id,
        "user_id": row.user_id,
        "application_id": row.application_id,
        "role": row.role,
    }


@router.delete("/grants/{grant_id}", status_code=204)
def delete_grant(
    grant_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(_ADMIN)),
) -> None:
    row = db.get(ApplicationGrant, grant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Grant not found")
    summary = {
        "user_id": row.user_id,
        "application_id": row.application_id,
        "role": row.role,
    }
    db.delete(row)
    write_audit(
        db,
        actor_id=user.id,
        action="grant.delete",
        entity_type="application_grant",
        entity_id=grant_id,
        summary=summary,
        commit=False,
    )
    db.commit()


def _subject_label(db: Session, subject_type: str, subject_id: str) -> str:
    if subject_type == "application":
        app = db.get(Application, subject_id)
        return app.name if app else "Unknown application"
    if subject_type == "infra_component":
        infra = db.get(InfraComponent, subject_id)
        return infra.name if infra else "Unknown infrastructure"
    if subject_type == "service":
        svc = db.get(Service, subject_id)
        return svc.name if svc else "Unknown service"
    return subject_type


def _env_label(db: Session, env_id: str | None) -> tuple[str | None, str | None]:
    if not env_id:
        return None, None
    env = db.get(Environment, env_id)
    if not env:
        return "Unknown environment", None
    return env.name, env.key


def _dependency_summary(
    db: Session,
    *,
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    from_environment_id: str | None,
    to_environment_id: str | None,
) -> dict[str, Any]:
    consumer = _subject_label(db, from_type, from_id)
    provider = _subject_label(db, to_type, to_id)
    from_env_name, from_env_key = _env_label(db, from_environment_id)
    to_env_name, to_env_key = _env_label(db, to_environment_id)
    consumer_side = consumer
    if from_env_key:
        consumer_side = f"{consumer} {from_env_key}"
    provider_side = provider
    if to_env_key:
        provider_side = f"{provider} {to_env_key}"
    summary = f"{consumer_side} → depends on → {provider_side}"
    return {
        "consumer_label": consumer,
        "provider_label": provider,
        "from_environment_name": from_env_name,
        "from_environment_key": from_env_key,
        "to_environment_name": to_env_name,
        "to_environment_key": to_env_key,
        "summary": summary,
        "description": (
            "If the provider is affected by maintenance, the consumer may also be impacted. "
            + summary
        ),
        "cross_environment": bool(
            from_environment_id
            and to_environment_id
            and from_environment_id != to_environment_id
        ),
    }


@router.get("/dependencies")
def list_all_dependencies(
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(_ADMIN)),
    q: str | None = None,
    limit: int = Query(200, ge=1, le=500),
) -> list[dict[str, Any]]:
    rows = db.query(Dependency).order_by(Dependency.updated_at.desc()).limit(limit).all()
    out: list[dict[str, Any]] = []
    for d in rows:
        meta = _dependency_summary(
            db,
            from_type=d.from_type,
            from_id=d.from_id,
            to_type=d.to_type,
            to_id=d.to_id,
            from_environment_id=d.from_environment_id,
            to_environment_id=d.to_environment_id,
        )
        blob = (
            f"{meta['summary']}:{d.from_type}:{d.from_id}:{d.to_type}:{d.to_id}:"
            f"{d.origin}:{d.dependency_kind}"
        )
        if q and q.lower() not in blob.lower():
            continue
        out.append(
            {
                "id": d.id,
                "from_type": d.from_type,
                "from_id": d.from_id,
                "to_type": d.to_type,
                "to_id": d.to_id,
                "from_environment_id": d.from_environment_id,
                "to_environment_id": d.to_environment_id,
                "dependency_kind": d.dependency_kind,
                "origin": d.origin,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                **meta,
            }
        )
    return out


class AdminDependencyCreate(BaseModel):
    from_type: str = Field(min_length=1, max_length=64)
    from_id: str
    to_type: str = Field(min_length=1, max_length=64)
    to_id: str
    dependency_kind: str = "depends_on"
    from_environment_id: Optional[str] = None
    to_environment_id: Optional[str] = None


@router.post("/dependencies", status_code=201)
def create_admin_dependency(
    body: AdminDependencyCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(_ADMIN)),
) -> dict[str, Any]:
    if body.from_type == body.to_type and body.from_id == body.to_id:
        raise HTTPException(
            status_code=400,
            detail="Self-reference rejected: a subject cannot depend on itself",
        )
    existing = (
        db.query(Dependency)
        .filter(
            Dependency.from_type == body.from_type,
            Dependency.from_id == body.from_id,
            Dependency.to_type == body.to_type,
            Dependency.to_id == body.to_id,
            Dependency.dependency_kind == body.dependency_kind,
            Dependency.from_environment_id == body.from_environment_id,
            Dependency.to_environment_id == body.to_environment_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Duplicate dependency relationship")

    # Soft cycle warning: direct reverse edge already exists
    reverse = (
        db.query(Dependency)
        .filter(
            Dependency.from_type == body.to_type,
            Dependency.from_id == body.to_id,
            Dependency.to_type == body.from_type,
            Dependency.to_id == body.from_id,
        )
        .first()
    )
    row = Dependency(
        from_type=body.from_type,
        from_id=body.from_id,
        to_type=body.to_type,
        to_id=body.to_id,
        dependency_kind=body.dependency_kind,
        origin="manual",
        from_environment_id=body.from_environment_id,
        to_environment_id=body.to_environment_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit(
        db,
        actor_id=user.id,
        action="dependency.create",
        entity_type="dependency",
        entity_id=row.id,
        summary={
            "from_type": body.from_type,
            "from_id": body.from_id,
            "to_type": body.to_type,
            "to_id": body.to_id,
            "cycle_warning": bool(reverse),
        },
    )
    meta = _dependency_summary(
        db,
        from_type=row.from_type,
        from_id=row.from_id,
        to_type=row.to_type,
        to_id=row.to_id,
        from_environment_id=row.from_environment_id,
        to_environment_id=row.to_environment_id,
    )
    return {
        "id": row.id,
        "from_type": row.from_type,
        "from_id": row.from_id,
        "to_type": row.to_type,
        "to_id": row.to_id,
        "from_environment_id": row.from_environment_id,
        "to_environment_id": row.to_environment_id,
        "dependency_kind": row.dependency_kind,
        "origin": row.origin,
        "cycle_warning": bool(reverse),
        **meta,
    }


@router.delete("/dependencies/{dependency_id}", status_code=204)
def delete_dependency(
    dependency_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(_ADMIN)),
) -> None:
    row = db.get(Dependency, dependency_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dependency not found")
    summary = {
        "from_type": row.from_type,
        "from_id": row.from_id,
        "to_type": row.to_type,
        "to_id": row.to_id,
        "origin": row.origin,
    }
    db.delete(row)
    write_audit(
        db,
        actor_id=user.id,
        action="dependency.delete",
        entity_type="dependency",
        entity_id=dependency_id,
        summary=summary,
        commit=False,
    )
    db.commit()


class InfraCreate(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    kind: Optional[str] = None
    description: Optional[str] = None


@router.post("/infra-components", status_code=201)
def create_infra(
    body: InfraCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(_ADMIN)),
) -> dict[str, Any]:
    if db.query(InfraComponent).filter(InfraComponent.key == body.key).first():
        raise HTTPException(status_code=409, detail="Infra key already exists")
    row = InfraComponent(
        key=body.key, name=body.name, kind=body.kind, description=body.description
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit(
        db,
        actor_id=user.id,
        action="infra.create",
        entity_type="infra_component",
        entity_id=row.id,
        summary={"key": body.key},
    )
    return {
        "id": row.id,
        "key": row.key,
        "name": row.name,
        "kind": row.kind,
        "description": row.description,
    }


@router.get("/deliveries")
def list_deliveries_admin(
    status: str | None = None,
    destination: str | None = None,
    event_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(_ADMIN)),
) -> list[dict[str, Any]]:
    q = db.query(NotificationDelivery)
    if status:
        q = q.filter(NotificationDelivery.status == DeliveryStatus(status))
    if destination:
        q = q.filter(NotificationDelivery.destination.ilike(f"%{destination}%"))
    if event_id:
        q = q.filter(NotificationDelivery.event_id == event_id)
    rows = (
        q.order_by(NotificationDelivery.created_at.desc()).offset(offset).limit(limit).all()
    )
    return [
        {
            "id": r.id,
            "idempotency_key": r.idempotency_key,
            "channel": r.channel,
            "destination_type": r.destination_type,
            "destination": r.destination,
            "subject": r.subject,
            "status": r.status.value if hasattr(r.status, "value") else r.status,
            "event_id": r.event_id,
            "attempt_count": r.attempt_count,
            "last_error": r.last_error,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
