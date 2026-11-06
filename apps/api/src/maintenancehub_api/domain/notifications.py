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
from maintenancehub_api.domain.templates import DEFAULT_TEMPLATES, render_template
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
    for key, parts in DEFAULT_TEMPLATES.items():
        existing = db.query(NotificationTemplate).filter(NotificationTemplate.key == key).first()
        if not existing:
            db.add(
                NotificationTemplate(
                    key=key,
                    channel="smtp",
                    subject_template=parts["subject"],
                    body_template=parts["body"],
                )
            )
    db.commit()


def get_template(db: Session, key: str) -> tuple[str, str]:
    row = db.query(NotificationTemplate).filter(NotificationTemplate.key == key).first()
    if row:
        return row.subject_template, row.body_template
    defaults = DEFAULT_TEMPLATES.get(key) or DEFAULT_TEMPLATES["event.transitioned"]
    return defaults["subject"], defaults["body"]


def event_context(event: MaintenanceEvent, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = {
        "event_id": event.id,
        "title": event.title,
        "kind": event.kind.value if hasattr(event.kind, "value") else event.kind,
        "status": event.status.value if hasattr(event.status, "value") else event.status,
        "approval_state": (
            event.approval_state.value
            if hasattr(event.approval_state, "value")
            else event.approval_state
        ),
        "starts_at": event.starts_at.isoformat() if event.starts_at else "",
        "ends_at": event.ends_at.isoformat() if event.ends_at else "",
        "timezone": event.timezone,
        "expected_impact": event.expected_impact or "",
        "from_status": "",
        "previous_ends_at": "",
        "note": "",
        "offset_label": "",
    }
    if extra:
        ctx.update(extra)
    return ctx


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
) -> tuple[NotificationDelivery | None, bool]:
    """Insert delivery; on unique violation treat as already applied (ADR-011).

    Returns (delivery, created_new).
    """
    existing = (
        db.query(NotificationDelivery)
        .filter(NotificationDelivery.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        return existing, False

    delivery = NotificationDelivery(
        idempotency_key=idempotency_key,
        channel=channel,
        destination_type=destination_type,
        destination=destination,
        subject=subject,
        body=body,
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

    subject_t, body_t = get_template(db, template_key)
    ctx = event_context(event, extra_context)
    subject = render_template(subject_t, ctx)
    body = render_template(body_t, ctx)

    created = 0
    for sub in matching_subscriptions(db, event, record=record):
        if sub.destination_type == "teams_bridge_channel":
            channel = "bridge"
            dest = sub.destination
            subj = render_bridge_subject(
                channel_key=sub.bridge_channel_key or "default",
                title=event.title,
            )
        else:
            channel = "smtp"
            dest = sub.destination
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
            body=body,
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
    subject_t, body_t = get_template(db, "event.reminder")
    extra = {"offset_label": label}
    if payload.get("occurrence_starts_at"):
        extra["starts_at"] = payload["occurrence_starts_at"]
    ctx = event_context(event, extra)
    subject = render_template(subject_t, ctx)
    body = render_template(body_t, ctx)
    if sub.destination_type == "teams_bridge_channel":
        channel = "bridge"
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
        body=body,
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
            body=delivery.body or "",
            mailbox=delivery.destination if "@" in (delivery.destination or "") else None,
        )
    else:
        result = get_smtp_adapter().send(
            to=delivery.destination,
            subject=delivery.subject or "",
            body=delivery.body or "",
        )

    if result.ok:
        delivery.status = DeliveryStatus.sent
        delivery.provider_message_id = result.provider_message_id
        delivery.channel = result.channel
        delivery.last_error = None
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
