"""Match subscriptions, enqueue idempotent deliveries, send via SMTP/bridge."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.adapters.bridge import get_bridge_adapter, render_bridge_subject
from maintenancehub_api.adapters.smtp import get_smtp_adapter
from maintenancehub_api.config import get_settings
from maintenancehub_api.domain import template_manager as tmpl_mgr
from maintenancehub_api.domain.templates import (
    DEFAULT_TEMPLATES,
    approval_label,
    render_template,
)
from maintenancehub_api.models import (
    ApprovalState,
    DeliveryStatus,
    EventStatus,
    Job,
    JobStatus,
    MaintenanceEvent,
    NotificationDelivery,
    NotificationTemplate,
    OutboxEvent,
    Subscription,
)
from maintenancehub_api.schemas.common import ensure_utc

logger = logging.getLogger("maintenancehub.notifications")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_default_templates(db: Session) -> None:
    tmpl_mgr.ensure_default_templates(db)


def get_template(db: Session, key: str) -> tuple[str, str]:
    """Legacy helper — subject + plain body."""
    rendered = render_template_parts(db, key)
    return rendered["subject_template"], rendered["body_plain_template"]


def render_template_parts(db: Session, key: str) -> dict[str, Any]:
    """Resolve active template row (or defaults) into subject/plain/html sources + metadata."""
    ensure_default_templates(db)
    row = tmpl_mgr.resolve_active_template(db, key)
    if not row:
        row = db.query(NotificationTemplate).filter(NotificationTemplate.key == key).first()
    if row:
        plain = row.body_plain_template if row.body_plain_template is not None else row.body_template
        return {
            "row": row,
            "subject_template": row.subject_template,
            "body_plain_template": plain or "",
            "body_html_template": row.body_html_template or "",
            "template_id": row.id,
            "template_version": row.version,
            "key": row.key,
        }
    defaults = DEFAULT_TEMPLATES.get(key) or DEFAULT_TEMPLATES["event.transitioned"]
    return {
        "row": None,
        "subject_template": defaults["subject"],
        "body_plain_template": defaults["body"],
        "body_html_template": defaults.get("body_html") or "",
        "template_id": None,
        "template_version": None,
        "key": key,
    }


def event_context(event: MaintenanceEvent, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    approval = (
        event.approval_state.value
        if hasattr(event.approval_state, "value")
        else str(event.approval_state)
    )
    base = get_settings().public_base_url.rstrip("/")
    ctx = {
        "event_id": event.id,
        "title": event.title,
        "kind": event.kind.value if hasattr(event.kind, "value") else event.kind,
        "status": event.status.value if hasattr(event.status, "value") else event.status,
        "approval_state": approval,
        "approval_label": approval_label(approval),
        "starts_at": event.starts_at.isoformat() if event.starts_at else "",
        "ends_at": event.ends_at.isoformat() if event.ends_at else "",
        "timezone": event.timezone,
        "expected_impact": event.expected_impact or "",
        "detail_url": f"{base}/events/{event.id}",
        "from_status": "",
        "previous_ends_at": "",
        "note": "",
        "offset_label": "",
        "teams_target_email": "",
        "bridge_channel_key": "",
    }
    if extra:
        ctx.update(extra)
    return ctx


def refresh_default_templates(db: Session, *, force: bool = False) -> int:
    """Create missing templates; optionally overwrite bodies from DEFAULT_TEMPLATES (seed)."""
    before = {r.key for r in db.query(NotificationTemplate).all()}
    ensure_default_templates(db)
    n = 0
    for key, parts in DEFAULT_TEMPLATES.items():
        existing = db.query(NotificationTemplate).filter(NotificationTemplate.key == key).first()
        if not existing:
            continue
        if key not in before:
            n += 1
        if force:
            existing.subject_template = parts["subject"]
            existing.body_template = parts["body"]
            existing.body_plain_template = parts["body"]
            existing.body_html_template = parts.get("body_html")
            existing.name = parts.get("name") or existing.name
            existing.event_type = key
            if key in before:
                n += 1
    db.commit()
    return n


def _subscription_matches_impacts(
    sub: Subscription,
    *,
    event_id: str,
    impacts: list,
) -> bool:
    """True if any target of ``sub`` matches the effective impact set.

    ``app_environment`` targets match an exact (application, environment) pair on
    the same impact row — never independent app/env ID sets.
    """
    from maintenancehub_api.domain.impacts import (
        ImpactRef,
        app_env_pairs,
        application_ids,
        environment_ids,
    )

    refs: list[ImpactRef] = list(impacts)
    apps = application_ids(refs)
    envs = environment_ids(refs)
    pairs = app_env_pairs(refs)

    for t in sub.targets:
        if t.target_type == "event" and t.target_id == event_id:
            return True
        if t.target_type == "application" and t.target_id in apps:
            return True
        if t.target_type == "environment" and t.target_id in envs:
            return True
        if t.target_type == "app_environment":
            if ":" in t.target_id:
                a, e = t.target_id.split(":", 1)
                if (a, e) in pairs:
                    return True
        # support_group targeting deferred
    return False


def matching_subscriptions(
    db: Session,
    event: MaintenanceEvent,
    *,
    record: Any | None = None,
    impacts: list | None = None,
) -> list[Subscription]:
    """Find active subscriptions intersecting effective impacts (deduped by sub id).

    Pass an occurrence ``record`` (or precomputed ``impacts`` ImpactRef list) so
    overridden occurrence impacts — including an explicit empty set — drive matching.
    """
    from maintenancehub_api.domain.impacts import effective_impacts

    if impacts is None:
        impacts = effective_impacts(event, record)

    subs = (
        db.query(Subscription)
        .options(
            joinedload(Subscription.targets),
            joinedload(Subscription.reminders),
        )
        .filter(Subscription.is_active.is_(True))
        .all()
    )
    matched: list[Subscription] = []
    seen: set[str] = set()
    for sub in subs:
        if sub.id in seen:
            continue
        if _subscription_matches_impacts(sub, event_id=event.id, impacts=impacts):
            seen.add(sub.id)
            matched.append(sub)
    return matched


def create_delivery_idempotent(
    db: Session,
    *,
    idempotency_key: str,
    channel: str,
    destination_type: str,
    destination: str,
    subject: str,
    body: str,
    event_id: str | None,
    subscription_id: str | None,
    body_html: str | None = None,
    body_plain: str | None = None,
    template_id: str | None = None,
    template_version: int | None = None,
    rendered_payload: dict[str, Any] | None = None,
) -> tuple[NotificationDelivery | None, bool]:
    """Insert delivery; on unique violation treat as already applied (ADR-011).

    Persists the fully rendered payload before send (M19). Returns (delivery, created_new).
    """
    existing = (
        db.query(NotificationDelivery)
        .filter(NotificationDelivery.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        return existing, False

    plain = body_plain if body_plain is not None else body
    payload = rendered_payload or {
        "subject": subject,
        "body_plain": plain,
        "body_html": body_html or "",
        "channel": channel,
        "destination": destination,
        "destination_type": destination_type,
        "template_id": template_id,
        "template_version": template_version,
    }
    delivery = NotificationDelivery(
        idempotency_key=idempotency_key,
        channel=channel,
        destination_type=destination_type,
        destination=destination,
        subject=subject,
        body=plain,
        body_plain=plain,
        body_html=body_html,
        template_id=template_id,
        template_version=template_version,
        rendered_payload=payload,
        event_id=event_id,
        subscription_id=subscription_id,
        status=DeliveryStatus.pending,
        next_attempt_at=_now(),
    )
    db.add(delivery)
    try:
        db.commit()
        db.refresh(delivery)
        return delivery, True
    except IntegrityError:
        db.rollback()
        logger.info("Delivery idempotency hit for key=%s", idempotency_key)
        row = (
            db.query(NotificationDelivery)
            .filter(NotificationDelivery.idempotency_key == idempotency_key)
            .first()
        )
        return row, False


def _is_pa_style_template(parts: dict[str, Any]) -> bool:
    key = parts.get("key") or ""
    subj = parts.get("subject_template") or ""
    return key.startswith("pa.") or subj.strip().startswith("[TEAMS]")


def enqueue_deliveries_for_event(
    db: Session,
    event: MaintenanceEvent,
    *,
    template_key: str,
    extra_context: dict[str, Any] | None = None,
    reason: str = "lifecycle",
    record: Any | None = None,
) -> int:
    """Create pending deliveries for matching subscriptions. Skip unconfirmed approved_window
    for broadcast lifecycle (confirmed_scheduled only), except explicit reminders of confirmed.

    When ``record`` / ``orig_key`` identify an occurrence, matching uses that occurrence's
    effective impacts (override or series defaults). Eligibility is re-checked here so
    stale outbox jobs do not notify subscribers who no longer match; sent history is kept.
    """
    if event.approval_state == ApprovalState.approved_window and reason != "force":
        logger.info("Skipping notify for approved_window event %s", event.id)
        return 0

    # Resolve occurrence record from orig_key when not provided
    if record is None and extra_context and extra_context.get("orig_key"):
        from maintenancehub_api.domain import occurrences as occurrence_service
        from maintenancehub_api.domain.recurrence import parse_occurrence_id

        orig_key = str(extra_context["orig_key"])
        if orig_key != "master":
            parsed = parse_occurrence_id(f"{event.id}@{orig_key}")
            if parsed:
                record = occurrence_service.find_record(db, event.id, parsed[1])

    parts = render_template_parts(db, template_key)

    created = 0
    for sub in matching_subscriptions(db, event, record=record):
        sub_extra = dict(extra_context or {})
        if sub.destination_type == "teams_bridge_channel":
            channel = "bridge"
            dest = sub.destination
            sub_extra.setdefault("bridge_channel_key", sub.bridge_channel_key or "default")
            # Body `To: {{teams_target_email}}` is PA routing — not the SMTP envelope.
            sub_extra.setdefault(
                "teams_target_email",
                sub_extra.get("teams_target_email")
                or f"{sub.bridge_channel_key or 'ops'}@example.com",
            )
        else:
            channel = "smtp"
            dest = sub.destination

        ctx = event_context(event, sub_extra)
        subject = render_template(parts["subject_template"], ctx, html_escape=False)
        body_plain = render_template(parts["body_plain_template"], ctx, html_escape=False)
        body_html = (
            render_template(parts["body_html_template"], ctx, html_escape=True)
            if parts["body_html_template"]
            else None
        )

        if sub.destination_type == "teams_bridge_channel" and not _is_pa_style_template(parts):
            # Legacy subject-token routing for non-PA templates.
            subj = render_bridge_subject(
                channel_key=sub.bridge_channel_key or "default",
                title=event.title,
            )
        else:
            subj = subject

        # Per-occurrence lifecycle keys include orig_key so two occurrences of the
        # same series can each notify start/complete/extend/cancel independently.
        orig_key = (extra_context or {}).get("orig_key") or "master"
        key = f"event:{event.id}:{template_key}:{reason}:orig:{orig_key}:sub:{sub.id}"
        row, is_new = create_delivery_idempotent(
            db,
            idempotency_key=key,
            channel=channel,
            destination_type=sub.destination_type,
            destination=dest,
            subject=subj,
            body=body_plain,
            body_plain=body_plain,
            body_html=body_html,
            template_id=parts.get("template_id"),
            template_version=parts.get("template_version"),
            rendered_payload={
                "subject": subj,
                "body_plain": body_plain,
                "body_html": body_html or "",
                "teams_target_email": ctx.get("teams_target_email") or "",
                "bridge_channel_key": ctx.get("bridge_channel_key") or "",
                "template_key": parts.get("key"),
                "template_id": parts.get("template_id"),
                "template_version": parts.get("template_version"),
                "channel": channel,
                "destination": dest,
                "destination_type": sub.destination_type,
                "pa_routing_note": (
                    "Body To: line is Power Automate routing; SMTP To is the bridge mailbox."
                    if _is_pa_style_template(parts)
                    else None
                ),
            },
            event_id=event.id,
            subscription_id=sub.id,
        )
        if is_new and row:
            created += 1
            _enqueue_send_job(db, delivery_id=row.id, idempotency_key=f"send:{row.id}")
    return created


def _enqueue_send_job(db: Session, *, delivery_id: str, idempotency_key: str) -> None:
    existing = (
        db.query(Job).filter(Job.idempotency_key == idempotency_key).first()
    )
    if existing:
        return
    db.add(
        Job(
            job_type="notify_send",
            payload={"delivery_id": delivery_id},
            idempotency_key=idempotency_key,
            status=JobStatus.queued,
            run_at=_now(),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def _reminder_job_key(event_id: str, original_starts_at: datetime, sub_id: str, offset: int) -> str:
    orig_key = ensure_utc(original_starts_at).strftime("%Y%m%dT%H%M%SZ")
    return f"reminder:event:{event_id}:orig:{orig_key}:sub:{sub_id}:offset:{offset}"


def cancel_reminder_jobs_for_occurrence(
    db: Session,
    *,
    event_id: str,
    original_starts_at: datetime,
) -> int:
    """Mark queued reminder jobs for a cancelled occurrence as dead (idempotent)."""
    orig_key = ensure_utc(original_starts_at).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"reminder:event:{event_id}:orig:{orig_key}:"
    rows = (
        db.query(Job)
        .filter(
            Job.job_type == "notify_reminder",
            Job.status == JobStatus.queued,
            Job.idempotency_key.isnot(None),
            Job.idempotency_key.like(f"{prefix}%"),
        )
        .all()
    )
    n = 0
    for job in rows:
        job.status = JobStatus.dead
        job.last_error = "occurrence_cancelled"
        n += 1
    if n:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return n


def schedule_reminders_for_event(db: Session, event: MaintenanceEvent) -> int:
    """Enqueue reminder jobs per occurrence (bounded horizon) with stable idempotency keys.

    Key includes original occurrence start so edits/reschedules update run_at without
    duplicating deliveries. Already-sent / succeeded / dead jobs are never recreated.
    Cancelled occurrences skip enqueue and dead-letter any still-queued jobs.
    """
    if event.approval_state != ApprovalState.confirmed_scheduled:
        return 0
    if event.status in {EventStatus.cancelled, EventStatus.completed}:
        return 0

    from maintenancehub_api.domain import recurrence as recurrence_service
    from maintenancehub_api.models import RecurrenceRule

    # Ensure recurrence + exceptions loaded
    if event.is_recurring and event.recurrence_rule is None:
        event = (
            db.query(MaintenanceEvent)
            .options(
                joinedload(MaintenanceEvent.impacts),
                joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions),
            )
            .filter(MaintenanceEvent.id == event.id)
            .first()
        ) or event

    now = _now()
    horizon = now + timedelta(days=recurrence_service.REMINDER_HORIZON_DAYS)
    # Include cancelled so we can dead-letter queued jobs for skipped dates
    occs = recurrence_service.expand_event_occurrences(
        event,
        range_start=now - timedelta(hours=1),
        range_end=horizon,
        include_cancelled=True,
    )
    if not occs:
        occs = recurrence_service.expand_event_occurrences(
            event,
            range_start=ensure_utc(event.starts_at) - timedelta(seconds=1),
            range_end=ensure_utc(event.starts_at) + timedelta(days=1),
            include_cancelled=True,
        )

    from maintenancehub_api.domain import occurrences as occurrence_service
    from maintenancehub_api.domain.impacts import effective_impacts

    # Load all active subs once; filter per occurrence by effective impacts
    all_subs = (
        db.query(Subscription)
        .options(
            joinedload(Subscription.targets),
            joinedload(Subscription.reminders),
        )
        .filter(Subscription.is_active.is_(True))
        .all()
    )

    count = 0
    for occ in occs:
        occ_rec = occurrence_service.find_record(db, event.id, occ.original_starts_at)
        occ_status = occurrence_service.effective_status(
            event,
            original_starts_at=occ.original_starts_at,
            record=occ_rec,
            cancelled_exception=occ.cancelled,
        )
        if occ.cancelled or occ_status in {
            EventStatus.cancelled,
            EventStatus.completed,
        }:
            cancel_reminder_jobs_for_occurrence(
                db, event_id=event.id, original_starts_at=occ.original_starts_at
            )
            continue

        eff_impacts = effective_impacts(event, occ_rec)
        matched_subs = [
            s
            for s in all_subs
            if _subscription_matches_impacts(s, event_id=event.id, impacts=eff_impacts)
        ]
        # Dead-letter queued reminders for subscribers who no longer match this occ
        reconcile_queued_reminders_for_occurrence(
            db,
            event_id=event.id,
            original_starts_at=occ.original_starts_at,
            eligible_subscription_ids={s.id for s in matched_subs},
        )

        eff_starts, _eff_ends = occurrence_service.effective_times(occ, occ_rec)
        for sub in matched_subs:
            for rem in sub.reminders:
                key = _reminder_job_key(
                    event.id, occ.original_starts_at, sub.id, rem.offset_minutes
                )
                run_at = eff_starts + timedelta(minutes=rem.offset_minutes)
                # Skip enqueue if reminder time already passed significantly
                if run_at < now - timedelta(minutes=5):
                    continue
                existing = db.query(Job).filter(Job.idempotency_key == key).first()
                if existing:
                    if existing.status == JobStatus.queued and existing.run_at != run_at:
                        existing.run_at = run_at
                        existing.payload = {
                            **(existing.payload or {}),
                            "occurrence_starts_at": eff_starts.isoformat(),
                            "original_starts_at": occ.original_starts_at.isoformat(),
                        }
                        count += 1
                    continue
                delivery_key = (
                    f"event:{event.id}:event.reminder:orig:"
                    f"{occ.original_starts_at.strftime('%Y%m%dT%H%M%SZ')}:"
                    f"offset:{rem.offset_minutes}:sub:{sub.id}"
                )
                prior = (
                    db.query(NotificationDelivery)
                    .filter(NotificationDelivery.idempotency_key == delivery_key)
                    .first()
                )
                if prior and prior.status in {
                    DeliveryStatus.sent,
                    DeliveryStatus.pending,
                    DeliveryStatus.sending,
                }:
                    continue
                try:
                    with db.begin_nested():
                        db.add(
                            Job(
                                job_type="notify_reminder",
                                payload={
                                    "event_id": event.id,
                                    "subscription_id": sub.id,
                                    "offset_minutes": rem.offset_minutes,
                                    "occurrence_starts_at": eff_starts.isoformat(),
                                    "original_starts_at": occ.original_starts_at.isoformat(),
                                },
                                idempotency_key=key,
                                status=JobStatus.queued,
                                run_at=run_at,
                            )
                        )
                        db.flush()
                    count += 1
                except IntegrityError:
                    continue
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return count


def reconcile_queued_reminders_for_occurrence(
    db: Session,
    *,
    event_id: str,
    original_starts_at: datetime,
    eligible_subscription_ids: set[str],
) -> int:
    """Dead-letter queued reminders whose subscription no longer matches this occurrence.

    Sent / succeeded deliveries are never deleted or rewritten.
    """
    orig_key = ensure_utc(original_starts_at).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"reminder:event:{event_id}:orig:{orig_key}:"
    rows = (
        db.query(Job)
        .filter(
            Job.job_type == "notify_reminder",
            Job.status == JobStatus.queued,
            Job.idempotency_key.isnot(None),
            Job.idempotency_key.like(f"{prefix}%"),
        )
        .all()
    )
    n = 0
    for job in rows:
        sub_id = (job.payload or {}).get("subscription_id")
        if sub_id and sub_id not in eligible_subscription_ids:
            job.status = JobStatus.dead
            job.last_error = "occurrence_impacts_no_longer_match"
            n += 1
    return n


def process_notify_dispatch(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Handler for notify_dispatch jobs created on event outbox."""
    event_id = payload.get("event_id")
    if not event_id:
        raise ValueError("notify_dispatch missing event_id")
    event = (
        db.query(MaintenanceEvent)
        .options(joinedload(MaintenanceEvent.impacts))
        .filter(MaintenanceEvent.id == event_id)
        .first()
    )
    if not event:
        raise ValueError(f"event {event_id} not found")

    # Infer template from outbox-ish payload
    event_type = payload.get("event_type") or "event.transitioned"
    if "from" in payload and "to" in payload:
        event_type = "event.transitioned"
        extra = {
            "from_status": payload.get("from", ""),
            "status": payload.get("to", event.status.value),
            "note": payload.get("note", ""),
            "orig_key": payload.get("orig_key") or "master",
            "starts_at": payload.get("starts_at", ""),
            "ends_at": payload.get("ends_at", ""),
        }
    elif "new_ends_at" in payload:
        event_type = "event.extended"
        extra = {
            "previous_ends_at": payload.get("previous_ends_at", ""),
            "ends_at": payload.get("new_ends_at", event.ends_at.isoformat()),
            "note": payload.get("note", ""),
            "orig_key": payload.get("orig_key") or "master",
        }
    elif payload.get("action") == "created" or event_type == "event.created":
        event_type = "event.created"
        extra = {"orig_key": payload.get("orig_key") or "master"}
    else:
        extra = {
            "note": payload.get("note", ""),
            "orig_key": payload.get("orig_key") or "master",
        }

    # Normalize known outbox event_type names
    mapping = {
        "event.created": "event.created",
        "event.confirmed": "event.created",  # reuse created template when approval confirmed
        "event.transitioned": "event.transitioned",
        "event.extended": "event.extended",
        "event.rescheduled": "event.rescheduled",
        # Impact set changed on an already-published event — reuse created template;
        # delivery idempotency prevents resending unchanged recipient/reason pairs.
        "event.impacts_changed": "event.created",
    }
    template_key = mapping.get(event_type, event_type)
    if template_key not in DEFAULT_TEMPLATES:
        template_key = "event.transitioned"

    n = enqueue_deliveries_for_event(
        db, event, template_key=template_key, extra_context=extra, reason=template_key
    )
    # On create / schedule / impact change, reconcile advance reminders to effective impacts
    if event_type in {
        "event.created",
        "event.confirmed",
        "event.rescheduled",
        "event.impacts_changed",
    } or template_key in {
        "event.created",
        "event.rescheduled",
    }:
        schedule_reminders_for_event(db, event)
    return {"deliveries_enqueued": n}


def process_notify_reminder(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    event = db.get(MaintenanceEvent, payload["event_id"])
    sub = (
        db.query(Subscription)
        .options(
            joinedload(Subscription.targets),
            joinedload(Subscription.reminders),
        )
        .filter(Subscription.id == payload["subscription_id"])
        .first()
    )
    if not event or not sub or not sub.is_active:
        return {"skipped": True}
    # Never notify for approved-only windows or terminal series
    if event.approval_state != ApprovalState.confirmed_scheduled:
        return {"skipped": True, "reason": "not_confirmed"}
    if event.status in {EventStatus.cancelled, EventStatus.completed}:
        return {"skipped": True, "reason": "terminal_status"}

    # Skip if this occurrence was cancelled after the job was queued
    orig = payload.get("original_starts_at")
    occ_rec = None
    if orig and event.is_recurring:
        from maintenancehub_api.domain import recurrence as recurrence_service
        from maintenancehub_api.models import RecurrenceRule

        event = (
            db.query(MaintenanceEvent)
            .options(
                joinedload(MaintenanceEvent.impacts),
                joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions),
            )
            .filter(MaintenanceEvent.id == event.id)
            .first()
        ) or event
        orig_dt = ensure_utc(datetime.fromisoformat(str(orig).replace("Z", "+00:00")))
        occs = recurrence_service.expand_event_occurrences(
            event,
            range_start=orig_dt - timedelta(minutes=1),
            range_end=orig_dt + timedelta(minutes=1),
            include_cancelled=True,
        )
        from maintenancehub_api.domain import occurrences as occurrence_service
        from maintenancehub_api.domain.impacts import effective_impacts

        occ_rec = occurrence_service.find_record(db, event.id, orig_dt)
        if any(o.cancelled for o in occs) or (
            occ_rec
            and occ_rec.status in {EventStatus.cancelled, EventStatus.completed}
        ):
            cancel_reminder_jobs_for_occurrence(
                db, event_id=event.id, original_starts_at=orig_dt
            )
            return {"skipped": True, "reason": "occurrence_cancelled"}
        # Eligibility: impacts may have changed since the job was queued
        if not _subscription_matches_impacts(
            sub, event_id=event.id, impacts=effective_impacts(event, occ_rec)
        ):
            return {"skipped": True, "reason": "impacts_no_longer_match"}
        # Prefer effective (possibly rescheduled) start for template context
        live = next((o for o in occs if not o.cancelled), None)
        if live:
            eff_starts, _ = occurrence_service.effective_times(live, occ_rec)
            payload = {
                **payload,
                "occurrence_starts_at": eff_starts.isoformat(),
            }
    elif not event.is_recurring:
        from maintenancehub_api.domain.impacts import effective_impacts

        if not _subscription_matches_impacts(
            sub, event_id=event.id, impacts=effective_impacts(event, None)
        ):
            return {"skipped": True, "reason": "impacts_no_longer_match"}

    offset = int(payload["offset_minutes"])
    label = f"{abs(offset)}m before start" if offset < 0 else f"{offset}m after start"
    parts = render_template_parts(db, "event.reminder")
    extra: dict[str, Any] = {"offset_label": label}
    if payload.get("occurrence_starts_at"):
        extra["starts_at"] = payload["occurrence_starts_at"]
    if sub.destination_type == "teams_bridge_channel":
        extra["bridge_channel_key"] = sub.bridge_channel_key or "default"
        extra.setdefault(
            "teams_target_email", f"{sub.bridge_channel_key or 'ops'}@example.com"
        )
    ctx = event_context(event, extra)
    subject = render_template(parts["subject_template"], ctx, html_escape=False)
    body_plain = render_template(parts["body_plain_template"], ctx, html_escape=False)
    body_html = (
        render_template(parts["body_html_template"], ctx, html_escape=True)
        if parts["body_html_template"]
        else None
    )
    if sub.destination_type == "teams_bridge_channel":
        channel = "bridge"
        if _is_pa_style_template(parts):
            subj = subject
        else:
            subj = render_bridge_subject(
                channel_key=sub.bridge_channel_key or "default", title=event.title
            )
    else:
        channel = "smtp"
        subj = subject
    if orig:
        orig_dt = ensure_utc(datetime.fromisoformat(str(orig).replace("Z", "+00:00")))
        orig_key = orig_dt.strftime("%Y%m%dT%H%M%SZ")
    else:
        orig_key = "master"
    key = f"event:{event.id}:event.reminder:orig:{orig_key}:offset:{offset}:sub:{sub.id}"
    row, is_new = create_delivery_idempotent(
        db,
        idempotency_key=key,
        channel=channel,
        destination_type=sub.destination_type,
        destination=sub.destination,
        subject=subj,
        body=body_plain,
        body_plain=body_plain,
        body_html=body_html,
        template_id=parts.get("template_id"),
        template_version=parts.get("template_version"),
        rendered_payload={
            "subject": subj,
            "body_plain": body_plain,
            "body_html": body_html or "",
            "template_key": parts.get("key"),
            "template_id": parts.get("template_id"),
            "template_version": parts.get("template_version"),
            "channel": channel,
            "destination": sub.destination,
            "destination_type": sub.destination_type,
        },
        event_id=event.id,
        subscription_id=sub.id,
    )
    if is_new and row:
        _enqueue_send_job(db, delivery_id=row.id, idempotency_key=f"send:{row.id}")
    return {"delivery_id": row.id if row else None, "created": is_new}


def send_delivery(db: Session, delivery_id: str) -> NotificationDelivery:
    settings = get_settings()
    delivery = db.get(NotificationDelivery, delivery_id)
    if not delivery:
        raise ValueError(f"delivery {delivery_id} not found")
    if delivery.status == DeliveryStatus.sent:
        return delivery

    delivery.status = DeliveryStatus.sending
    delivery.attempt_count += 1
    db.commit()

    plain = delivery.body_plain or delivery.body or ""
    html_body = delivery.body_html
    # Prefer persisted rendered payload when present (M19).
    if delivery.rendered_payload and isinstance(delivery.rendered_payload, dict):
        plain = delivery.rendered_payload.get("body_plain") or plain
        html_body = delivery.rendered_payload.get("body_html") or html_body

    if delivery.destination_type == "teams_bridge_channel" or delivery.channel == "bridge":
        # Extract channel key from subject or subscription
        channel_key = "default"
        if delivery.subscription_id:
            sub = db.get(Subscription, delivery.subscription_id)
            if sub and sub.bridge_channel_key:
                channel_key = sub.bridge_channel_key
        result = get_bridge_adapter().send(
            channel_key=channel_key,
            title=delivery.subject or "MaintenanceHub",
            subject=delivery.subject,
            body=plain,
            body_html=html_body,
            mailbox=delivery.destination if "@" in (delivery.destination or "") else None,
        )
    else:
        result = get_smtp_adapter().send(
            to=delivery.destination,
            subject=delivery.subject or "",
            body=plain,
            body_html=html_body,
        )

    if result.ok:
        # SMTP acceptance is recorded as sent. Uncertain hand-off (accepted but
        # confirmation lost) still counts as sent so admin retry cannot duplicate.
        delivery.status = DeliveryStatus.sent
        delivery.provider_message_id = result.provider_message_id
        delivery.channel = result.channel
        delivery.last_error = result.error if getattr(result, "uncertain", False) else None
    else:
        if delivery.attempt_count >= settings.delivery_max_attempts:
            delivery.status = DeliveryStatus.dead
        else:
            delivery.status = DeliveryStatus.failed
            delivery.next_attempt_at = _now() + timedelta(seconds=min(3600, 2**delivery.attempt_count))
            # Re-queue send
            _enqueue_send_job(
                db,
                delivery_id=delivery.id,
                idempotency_key=f"send:{delivery.id}:retry:{delivery.attempt_count}",
            )
        delivery.last_error = result.error
    db.commit()
    db.refresh(delivery)
    return delivery


def process_outbox(db: Session, limit: int = 50) -> int:
    """Mark outbox processed and ensure notify_dispatch jobs exist."""
    rows = (
        db.query(OutboxEvent)
        .filter(OutboxEvent.processed_at.is_(None))
        .order_by(OutboxEvent.created_at.asc())
        .limit(limit)
        .all()
    )
    n = 0
    for row in rows:
        payload = dict(row.payload or {})
        payload.setdefault("event_id", row.aggregate_id)
        payload["event_type"] = row.event_type
        key = f"outbox:{row.id}:notify_dispatch"
        existing = db.query(Job).filter(Job.idempotency_key == key).first()
        if not existing:
            db.add(
                Job(
                    job_type="notify_dispatch",
                    payload=payload,
                    idempotency_key=key,
                    status=JobStatus.queued,
                    run_at=_now(),
                )
            )
        row.processed_at = _now()
        n += 1
    db.commit()
    return n
