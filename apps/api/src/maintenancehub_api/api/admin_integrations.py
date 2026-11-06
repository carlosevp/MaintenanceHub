"""Admin: ServiceNow, CSV imports, role mappings, service credentials, audit (M9–M11)."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from maintenancehub_api.adapters.servicenow import get_change_adapter
from maintenancehub_api.api.experience import require_capability
from maintenancehub_api.auth.security import hash_password
from maintenancehub_api.config import get_settings
from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, require_roles
from maintenancehub_api.domain.audit import write_audit
from maintenancehub_api.domain.csv_import import commit_import, create_import_job, preview_import
from maintenancehub_api.domain.servicenow_sync import resolve_unmatched, run_poll
from maintenancehub_api.models import (
    AuditLog,
    CsvImportJob,
    GroupRoleMapping,
    Job,
    JobStatus,
    RoleName,
    ServiceCredential,
    SnUnmatchedRecord,
)

router = APIRouter(tags=["admin-integrations"])


# ----- Integration settings / tests -----


@router.get("/admin/settings/integrations")
def get_integration_settings(
    _: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> dict[str, Any]:
    s = get_settings()
    return {
        "smtp_enabled": s.smtp_enabled,
        "bridge_enabled": s.bridge_enabled,
        "servicenow_enabled": s.servicenow_enabled,
        "servicenow_use_fixture": s.servicenow_use_fixture,
        "servicenow_fixture_path": s.servicenow_fixture_path,
        "servicenow_instance_url": s.servicenow_instance_url or None,
        "auth_mode": s.auth_mode,
        "note": "Secrets are env/OpenShift Secrets only — never returned here",
    }


@router.post("/admin/settings/integrations/test")
def test_integrations(
    kind: str = Query("smtp", pattern="^(smtp|bridge|servicenow)$"),
    _: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> dict:
    if kind == "servicenow":
        return get_change_adapter().connection_test()
    if kind == "bridge":
        from maintenancehub_api.adapters.bridge import get_bridge_adapter

        return get_bridge_adapter().connection_test()
    s = get_settings()
    return {
        "smtp_enabled": s.smtp_enabled,
        "host": s.smtp_host,
        "port": s.smtp_port,
        "ok": True,
        "note": "When SMTP_ENABLED=false, deliveries use the log sink.",
    }


# ----- ServiceNow -----


class PollNowBody(BaseModel):
    dry_run: bool = False
    # Optional inline fixture for dry-run / tests (does not require SERVICENOW_ENABLED)
    fixture_records: Optional[list[dict[str, Any]]] = None


@router.post("/admin/servicenow/poll-now")
def poll_now(
    body: PollNowBody | None = None,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> dict[str, Any]:
    require_capability("servicenow")
    body = body or PollNowBody()
    settings = get_settings()

    if body.dry_run:
        # Dry-run always uses fixture/inline records — never hits live SN, no DB writes
        from pathlib import Path

        from maintenancehub_api.adapters.servicenow import FixtureChangeAdapter

        if body.fixture_records is not None:
            adapter = FixtureChangeAdapter(records=body.fixture_records)
        else:
            path = Path(settings.servicenow_fixture_path)
            if not path.is_absolute():
                path = Path.cwd() / path
            adapter = FixtureChangeAdapter(path=path)
        polled = adapter.poll()
        return {
            "dry_run": True,
            "fetched": len(polled),
            "records": [
                {
                    "sys_id": r.external_id,
                    "number": r.number,
                    "short_description": r.short_description,
                    "state": r.state,
                    "content_hash": r.content_hash(),
                }
                for r in polled
            ],
            "note": "Dry-run — no DB writes, no live ServiceNow calls",
        }

    if not settings.servicenow_enabled and not body.fixture_records:
        # Still allow poll with fixture when enabled=false if fixture_records provided;
        # otherwise enqueue no-op via null adapter
        pass

    if body.fixture_records is not None:
        stats = run_poll(db, fixture_records=body.fixture_records)
        write_audit(
            db,
            actor_id=user.id,
            action="servicenow.poll",
            entity_type="servicenow",
            summary={"stats": stats, "source": "inline_fixture"},
        )
        return {"dry_run": False, **stats}

    # Enqueue durable job for worker
    job = Job(
        job_type="sn_poll",
        payload={},
        idempotency_key=None,
        status=JobStatus.queued,
        run_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    write_audit(
        db,
        actor_id=user.id,
        action="servicenow.poll_enqueued",
        entity_type="job",
        entity_id=job.id,
        summary={},
    )
    return {"enqueued_job_id": job.id, "job_type": "sn_poll"}


@router.get("/admin/servicenow/unmatched")
def list_unmatched(
    status_filter: str | None = Query(default="open", alias="status"),
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> list[dict[str, Any]]:
    q = db.query(SnUnmatchedRecord)
    if status_filter:
        q = q.filter(SnUnmatchedRecord.status == status_filter)
    rows = q.order_by(SnUnmatchedRecord.created_at.desc()).limit(100).all()
    return [
        {
            "id": r.id,
            "external_id": r.external_id,
            "reason": r.reason,
            "status": r.status,
            "raw_payload": r.raw_payload,
            "resolved_event_id": r.resolved_event_id,
        }
        for r in rows
    ]


class ResolveBody(BaseModel):
    action: str  # link | create | ignore
    event_id: Optional[str] = None


@router.post("/admin/servicenow/unmatched/{unmatched_id}/resolve")
def resolve_unmatched_api(
    unmatched_id: str,
    body: ResolveBody,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> dict[str, Any]:
    try:
        row = resolve_unmatched(
            db, unmatched_id, action=body.action, event_id=body.event_id, actor_id=user.id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_audit(
        db,
        actor_id=user.id,
        action=f"servicenow.unmatched.{body.action}",
        entity_type="sn_unmatched_record",
        entity_id=row.id,
        summary={"external_id": row.external_id, "resolved_event_id": row.resolved_event_id},
    )
    return {"id": row.id, "status": row.status, "resolved_event_id": row.resolved_event_id}


# ----- CSV imports -----


@router.post("/admin/imports/csv")
async def upload_csv(
    kind: str = Form("cmdb_ci"),
    file: UploadFile = File(...),
    overwrite_manual_dependencies: bool = Form(False),
    column_map_json: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> dict[str, Any]:
    import json

    require_capability("csv_import")
    raw = (await file.read()).decode("utf-8-sig")
    cmap = json.loads(column_map_json) if column_map_json else None
    try:
        job = create_import_job(
            db,
            kind=kind,
            filename=file.filename or "upload.csv",
            raw_csv=raw,
            column_map=cmap,
            options={"overwrite_manual_dependencies": overwrite_manual_dependencies},
            created_by=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_audit(
        db,
        actor_id=user.id,
        action="csv.upload",
        entity_type="csv_import_job",
        entity_id=job.id,
        summary={"kind": kind, "filename": job.filename},
    )
    return {"id": job.id, "status": job.status, "kind": job.kind, "filename": job.filename}


@router.post("/admin/imports/{import_id}/preview")
def preview_csv(
    import_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> dict[str, Any]:
    job = db.get(CsvImportJob, import_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import not found")
    preview = preview_import(db, job)
    write_audit(
        db,
        actor_id=user.id,
        action="csv.preview",
        entity_type="csv_import_job",
        entity_id=job.id,
        summary={"error_count": preview.get("error_count"), "valid_rows": preview.get("valid_rows")},
    )
    return preview


@router.post("/admin/imports/{import_id}/commit")
def commit_csv(
    import_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> dict[str, Any]:
    job = db.get(CsvImportJob, import_id)
    if not job:
        raise HTTPException(status_code=404, detail="Import not found")
    try:
        summary = commit_import(db, job)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    write_audit(
        db,
        actor_id=user.id,
        action="csv.commit",
        entity_type="csv_import_job",
        entity_id=job.id,
        summary=summary,
    )
    return {"id": job.id, "status": job.status, "result": summary}


@router.get("/admin/imports")
def list_imports(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    kind: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> list[dict[str, Any]]:
    q = db.query(CsvImportJob)
    if kind:
        q = q.filter(CsvImportJob.kind == kind)
    if status:
        q = q.filter(CsvImportJob.status == status)
    rows = q.order_by(CsvImportJob.created_at.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "filename": r.filename,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "committed_at": r.committed_at.isoformat() if r.committed_at else None,
            "result_summary": r.result_summary,
            "import_mode": (r.options or {}).get("import_mode", "partial"),
        }
        for r in rows
    ]


# ----- Role mappings -----


class RoleMappingIn(BaseModel):
    directory_group: str
    role: str
    application_id: Optional[str] = None


@router.get("/admin/role-mappings")
def list_role_mappings(
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> list[dict[str, Any]]:
    rows = db.query(GroupRoleMapping).all()
    return [
        {
            "id": r.id,
            "directory_group": r.directory_group,
            "role": r.role.value,
            "application_id": r.application_id,
        }
        for r in rows
    ]


@router.post("/admin/role-mappings", status_code=201)
def create_role_mapping(
    body: RoleMappingIn,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> dict[str, Any]:
    row = GroupRoleMapping(
        directory_group=body.directory_group,
        role=RoleName(body.role),
        application_id=body.application_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit(
        db,
        actor_id=user.id,
        action="role_mapping.create",
        entity_type="group_role_mapping",
        entity_id=row.id,
        summary={"directory_group": body.directory_group, "role": body.role},
    )
    return {
        "id": row.id,
        "directory_group": row.directory_group,
        "role": row.role.value,
        "application_id": row.application_id,
    }


@router.delete("/admin/role-mappings/{mapping_id}", status_code=204)
def delete_role_mapping(
    mapping_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> None:
    row = db.get(GroupRoleMapping, mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail="Role mapping not found")
    summary = {
        "directory_group": row.directory_group,
        "role": row.role.value,
        "application_id": row.application_id,
    }
    db.delete(row)
    write_audit(
        db,
        actor_id=user.id,
        action="role_mapping.delete",
        entity_type="group_role_mapping",
        entity_id=mapping_id,
        summary=summary,
        commit=False,
    )
    db.commit()


# ----- Service credentials -----


class ServiceCredCreate(BaseModel):
    name: str
    scopes: list[str] = Field(default_factory=lambda: ["banner:read"])
    application_id: Optional[str] = None


@router.get("/admin/service-credentials")
def list_service_creds(
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> list[dict[str, Any]]:
    rows = db.query(ServiceCredential).order_by(ServiceCredential.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "client_id": r.client_id,
            "scopes": r.scopes,
            "application_id": r.application_id,
            "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
        }
        for r in rows
    ]


@router.post("/admin/service-credentials", status_code=201)
def create_service_cred(
    body: ServiceCredCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> dict[str, Any]:
    client_id = f"svc_{secrets.token_hex(8)}"
    raw_secret = secrets.token_urlsafe(32)
    row = ServiceCredential(
        name=body.name,
        client_id=client_id,
        secret_hash=hash_password(raw_secret),
        scopes=body.scopes,
        application_id=body.application_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit(
        db,
        actor_id=user.id,
        action="service_credential.create",
        entity_type="service_credential",
        entity_id=row.id,
        summary={"client_id": client_id, "scopes": body.scopes},
    )
    return {
        "id": row.id,
        "name": row.name,
        "client_id": client_id,
        "client_secret": raw_secret,  # once
        "scopes": row.scopes,
    }


@router.post("/admin/service-credentials/{cred_id}/rotate")
def rotate_service_cred(
    cred_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> dict[str, Any]:
    row = db.get(ServiceCredential, cred_id)
    if not row or row.revoked_at:
        raise HTTPException(status_code=404, detail="Credential not found")
    raw_secret = secrets.token_urlsafe(32)
    row.secret_hash = hash_password(raw_secret)
    db.commit()
    write_audit(
        db,
        actor_id=user.id,
        action="service_credential.rotate",
        entity_type="service_credential",
        entity_id=row.id,
        summary={"client_id": row.client_id},
    )
    return {"id": row.id, "client_id": row.client_id, "client_secret": raw_secret}


@router.post("/admin/service-credentials/{cred_id}/revoke", status_code=200)
def revoke_service_cred(
    cred_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> dict[str, Any]:
    row = db.get(ServiceCredential, cred_id)
    if not row:
        raise HTTPException(status_code=404, detail="Credential not found")
    if row.revoked_at:
        return {
            "id": row.id,
            "client_id": row.client_id,
            "revoked_at": row.revoked_at.isoformat(),
            "already_revoked": True,
        }
    row.revoked_at = datetime.now(timezone.utc)
    write_audit(
        db,
        actor_id=user.id,
        action="service_credential.revoke",
        entity_type="service_credential",
        entity_id=row.id,
        summary={"client_id": row.client_id},
        commit=False,
    )
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "client_id": row.client_id,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "already_revoked": False,
    }


@router.get("/admin/audit")
def list_audit(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    actor_id: str | None = None,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> list[dict[str, Any]]:
    from sqlalchemy import or_

    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if actor_id:
        query = query.filter(AuditLog.actor_id == actor_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                AuditLog.action.ilike(like),
                AuditLog.entity_type.ilike(like),
                AuditLog.entity_id.ilike(like),
            )
        )
    rows = query.order_by(AuditLog.at.desc()).offset(offset).limit(limit).all()
    return [
        {
            "id": r.id,
            "actor_id": r.actor_id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "summary": r.summary,
            "at": r.at.isoformat() if r.at else None,
        }
        for r in rows
    ]


# Banner API moved to api/banner.py (M12)
