from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, require_roles
from maintenancehub_api.domain.audit import write_audit
from maintenancehub_api.models import DeliveryStatus, Job, JobStatus, NotificationDelivery, RoleName
from maintenancehub_api.schemas.subscriptions import JobOut

router = APIRouter(prefix="/admin/jobs", tags=["admin-jobs"])


@router.get("")
def list_jobs(
    status: str | None = None,
    job_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> list[dict]:
    q = db.query(Job)
    if status:
        q = q.filter(Job.status == JobStatus(status))
    if job_type:
        q = q.filter(Job.job_type == job_type)
    rows = q.order_by(Job.created_at.desc()).limit(limit).all()
    return [
        {
            "id": j.id,
            "job_type": j.job_type,
            "status": j.status.value,
            "attempt_count": j.attempt_count,
            "last_error": j.last_error,
            "leased_by": j.leased_by,
            "idempotency_key": j.idempotency_key,
            "run_at": j.run_at.isoformat() if j.run_at else None,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }
        for j in rows
    ]


@router.post("/{job_id}/retry", response_model=JobOut)
def retry_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_roles(RoleName.platform_administrator.value)),
) -> Job:
    """Safe retry: only failed/dead jobs; notify sends skip already-sent deliveries."""
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {JobStatus.failed, JobStatus.dead}:
        raise HTTPException(
            status_code=409, detail=f"Cannot retry job in status {job.status.value}"
        )

    # Idempotent notify path: if the linked delivery already succeeded, refuse requeue
    # so unrestricted retries cannot duplicate outbound mail.
    if job.job_type in {"notify_send", "notify_reminder"} and isinstance(job.payload, dict):
        delivery_id = job.payload.get("delivery_id")
        if delivery_id:
            delivery = db.get(NotificationDelivery, delivery_id)
            if delivery and delivery.status == DeliveryStatus.sent:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Delivery already sent — refusing retry to prevent duplicate "
                        "notification (idempotency)"
                    ),
                )
            if delivery and delivery.status in {DeliveryStatus.failed, DeliveryStatus.dead}:
                delivery.status = DeliveryStatus.pending
                delivery.next_attempt_at = datetime.now(timezone.utc)

    job.status = JobStatus.queued
    job.leased_by = None
    job.lease_expires_at = None
    job.run_at = datetime.now(timezone.utc)
    job.last_error = None
    write_audit(
        db,
        actor_id=user.id,
        action="job.retry",
        entity_type="job",
        entity_id=job.id,
        summary={"job_type": job.job_type, "idempotency_key": job.idempotency_key},
        commit=False,
    )
    db.commit()
    db.refresh(job)
    return job
