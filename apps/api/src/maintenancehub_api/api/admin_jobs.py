from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, require_roles
from maintenancehub_api.models import Job, JobStatus, RoleName
from maintenancehub_api.schemas.subscriptions import JobOut

router = APIRouter(prefix="/admin/jobs", tags=["admin-jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> list[Job]:
    q = db.query(Job)
    if status:
        q = q.filter(Job.status == JobStatus(status))
    return q.order_by(Job.created_at.desc()).limit(limit).all()


@router.post("/{job_id}/retry", response_model=JobOut)
def retry_job(
    job_id: str,
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {JobStatus.failed, JobStatus.dead}:
        raise HTTPException(status_code=409, detail=f"Cannot retry job in status {job.status.value}")
    job.status = JobStatus.queued
    job.leased_by = None
    job.lease_expires_at = None
    job.run_at = datetime.now(timezone.utc)
    job.last_error = None
    db.commit()
    db.refresh(job)
    return job
