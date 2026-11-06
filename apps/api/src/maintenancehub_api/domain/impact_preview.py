"""Read-only impact analysis preview + confirmation publish (M14)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.domain import dependency_analysis as dep_analysis
from maintenancehub_api.domain import recurrence as recurrence_service
from maintenancehub_api.domain.impacts import ImpactRef, impacts_from_dicts
from maintenancehub_api.domain.notifications import matching_subscriptions
from maintenancehub_api.models import (
    ApprovalState,
    EventImpact,
    EventStatus,
    EventTimelineEntry,
    ImpactDecision,
    ImpactTargetType,
    MaintenanceEvent,
    OccurrenceImpact,
    RecurrenceRule,
    TimelineEntryType,
)
from maintenancehub_api.schemas.common import ensure_utc


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _norm_selection_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows or []:
        out.append(
            {
                "t": r.get("target_type"),
                "i": r.get("target_id"),
                "e": r.get("environment_id"),
                "reason": r.get("reason"),
            }
        )
    out.sort(key=lambda x: (x["t"] or "", x["i"] or "", x["e"] or "", x.get("reason") or ""))
    return out


def build_revision_token(
    *,
    seeds: list[ImpactRef],
    starts_at: datetime | None,
    ends_at: datetime | None,
    event_id: str | None,
    impact_revision: int,
    dependency_fingerprint: str,
    max_depth: int,
    original_starts_at: datetime | None = None,
    exclusions: list[dict[str, Any]] | None = None,
    manual_additions: list[dict[str, Any]] | None = None,
    proposed: list[ImpactRef] | None = None,
) -> str:
    """Hash reviewed selections + event/occ identity + dependency fingerprint.

    Changing exclusions/manuals/proposed set without re-preview yields a different
    token and blocks confirm.
    """
    payload = {
        "seeds": [
            {"t": s.target_type, "i": s.target_id, "e": s.environment_id} for s in seeds
        ],
        "starts_at": starts_at.isoformat() if starts_at else None,
        "ends_at": ends_at.isoformat() if ends_at else None,
        "original_starts_at": (
            ensure_utc(original_starts_at).isoformat() if original_starts_at else None
        ),
        "event_id": event_id,
        "impact_revision": impact_revision,
        "deps": dependency_fingerprint,
        "max_depth": max_depth,
        "exclusions": _norm_selection_rows(exclusions),
        "manuals": _norm_selection_rows(manual_additions),
        "proposed": sorted(
            [
                {"t": p.target_type, "i": p.target_id, "e": p.environment_id}
                for p in (proposed or [])
            ],
            key=lambda x: (x["t"] or "", x["i"] or "", x["e"] or ""),
        ),
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def dependency_fingerprint(db: Session) -> str:
    from maintenancehub_api.models import Dependency

    rows = (
        db.query(Dependency.id, Dependency.updated_at)
        .order_by(Dependency.id)
        .all()
    )
    blob = "|".join(
        f"{r.id}:{ensure_utc(r.updated_at).isoformat() if r.updated_at else ''}"
        for r in rows
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def preview_notification_audience(
    db: Session,
    *,
    event: MaintenanceEvent | None,
    selected_impacts: list[ImpactRef],
    include_destinations: bool = True,
) -> dict[str, Any]:
    """Estimate unique recipients for a candidate impact set (no sends).

    When ``include_destinations`` is False, return counts only (privacy harden).
    """
    from types import SimpleNamespace

    # Build an ephemeral event-like object for matching when draft
    if event is None:
        fake_impacts = [
            SimpleNamespace(
                target_type=ImpactTargetType(i.target_type)
                if i.target_type in {e.value for e in ImpactTargetType}
                else ImpactTargetType.application,
                target_id=i.target_id,
                environment_id=i.environment_id,
            )
            for i in selected_impacts
            if i.is_application
        ]
        fake = SimpleNamespace(id="preview-draft", impacts=fake_impacts)
        matched = matching_subscriptions(db, fake, impacts=selected_impacts)  # type: ignore[arg-type]
    else:
        matched = matching_subscriptions(db, event, impacts=selected_impacts)

    emails: list[str] = []
    teams: list[str] = []
    seen_dest: set[tuple[str, str]] = set()
    multi_sub_users: dict[str, int] = {}
    for sub in matched:
        multi_sub_users[sub.user_id] = multi_sub_users.get(sub.user_id, 0) + 1
        dest_key = (sub.destination_type, sub.destination)
        if dest_key in seen_dest:
            continue
        seen_dest.add(dest_key)
        if sub.destination_type == "teams_bridge_channel":
            teams.append(sub.bridge_channel_key or sub.destination)
        else:
            emails.append(sub.destination)

    multi = sum(1 for _, n in multi_sub_users.items() if n > 1)
    return {
        "unique_recipients": len(seen_dest),
        "email_destinations": emails if include_destinations else [],
        "teams_bridge_channels": teams if include_destinations else [],
        "subscription_count": len(matched),
        "users_with_multiple_subscriptions": multi,
        "destinations_redacted": not include_destinations,
        "note": (
            "Estimated unique destinations for confirmed impacts — "
            "not a count of outbound delivery rows"
            + ("; destination addresses redacted" if not include_destinations else "")
        ),
    }


def find_scheduling_conflicts(
    db: Session,
    *,
    starts_at: datetime,
    ends_at: datetime,
    selected: list[ImpactRef],
    exclude_event_id: str | None = None,
) -> list[dict[str, Any]]:
    """Advisory overlaps — direct vs dependency-related."""
    starts_at = ensure_utc(starts_at)
    ends_at = ensure_utc(ends_at)
    selected_apps = {(i.target_id, i.environment_id) for i in selected if i.is_application}
    selected_infra = {i.target_id for i in selected if i.target_type == "infra_component"}
    selected_services = {i.target_id for i in selected if i.target_type == "service"}

    # Also expand one hop of shared infra for classification
    from maintenancehub_api.models import Dependency

    related_apps: set[tuple[str, str | None]] = set()
    for dep in db.query(Dependency).all():
        if dep.to_type == "infra_component" and dep.to_id in selected_infra:
            if dep.from_type == "application":
                related_apps.add((dep.from_id, dep.from_environment_id))
        if dep.to_type == "application" and (dep.to_id, dep.to_environment_id) in selected_apps:
            if dep.from_type == "application":
                related_apps.add((dep.from_id, dep.from_environment_id))

    masters = (
        db.query(MaintenanceEvent)
        .options(
            joinedload(MaintenanceEvent.impacts),
            joinedload(MaintenanceEvent.recurrence_rule).joinedload(RecurrenceRule.exceptions),
        )
        .filter(MaintenanceEvent.status != EventStatus.cancelled)
        .all()
    )
    conflicts: list[dict[str, Any]] = []
    for e in masters:
        if exclude_event_id and e.id == exclude_event_id:
            continue
        if not recurrence_service.master_may_intersect_window(
            e, range_start=starts_at, range_end=ends_at
        ):
            continue
        occs = recurrence_service.expand_event_occurrences(
            e, range_start=starts_at, range_end=ends_at, include_cancelled=False
        )
        for occ in occs:
            # Overlay occurrence impacts
            from maintenancehub_api.domain import occurrences as occurrence_service
            from maintenancehub_api.domain.impacts import effective_impacts

            rec = occurrence_service.find_record(db, e.id, occ.original_starts_at)
            if rec and rec.status == EventStatus.cancelled:
                continue
            eff = effective_impacts(e, rec)
            other_apps = {(i.target_id, i.environment_id) for i in eff if i.is_application}
            other_infra = {i.target_id for i in eff if i.target_type == "infra_component"}
            other_svc = {i.target_id for i in eff if i.target_type == "service"}

            direct_hit = bool(selected_apps & other_apps) or bool(
                selected_infra & other_infra
            ) or bool(selected_services & other_svc)
            dep_hit = bool(related_apps & other_apps) and not direct_hit
            if not direct_hit and not dep_hit:
                continue
            conflicts.append(
                {
                    "event_id": e.id,
                    "title": e.title,
                    "occurrence_id": recurrence_service.occurrence_id_for(
                        e.id, occ.original_starts_at
                    ),
                    "starts_at": occ.starts_at.isoformat(),
                    "ends_at": occ.ends_at.isoformat(),
                    "classification": "direct_overlap" if direct_hit else "dependency_overlap",
                    "explanation": (
                        "Same application/environment or shared service/infra window"
                        if direct_hit
                        else "Overlaps a known dependent or shared-infrastructure consumer"
                    ),
                    "status": (
                        rec.status.value if rec else e.status.value
                    ),
                }
            )
    return conflicts


def build_preview(
    db: Session,
    *,
    seeds: list[dict[str, Any]],
    starts_at: datetime,
    ends_at: datetime,
    event_id: str | None = None,
    original_starts_at: datetime | None = None,
    exclusions: list[dict[str, Any]] | None = None,
    manual_additions: list[dict[str, Any]] | None = None,
    max_depth: int = dep_analysis.DEFAULT_MAX_DEPTH,
    include_destinations: bool = True,
) -> dict[str, Any]:
    """Assemble full read-only preview — never mutates deliveries/jobs/published state."""
    seed_refs = impacts_from_dicts(seeds)
    analysis = dep_analysis.analyze_downstream_impacts(
        db, seeds=seed_refs, max_depth=max_depth
    )

    exclude_keys = {
        (x["target_type"], x["target_id"], x.get("environment_id"))
        for x in (exclusions or [])
    }
    exclude_reasons = {
        (x["target_type"], x["target_id"], x.get("environment_id")): x.get("reason")
        for x in (exclusions or [])
    }

    existing_decisions: list[dict[str, Any]] = []
    event = None
    impact_revision = 0
    if event_id:
        event = (
            db.query(MaintenanceEvent)
            .options(
                joinedload(MaintenanceEvent.impacts),
                joinedload(MaintenanceEvent.impact_decisions),
            )
            .filter(MaintenanceEvent.id == event_id)
            .first()
        )
        if event:
            impact_revision = event.impact_revision or 0
            for d in event.impact_decisions or []:
                if original_starts_at and d.original_starts_at:
                    if abs(
                        (ensure_utc(d.original_starts_at) - ensure_utc(original_starts_at)).total_seconds()
                    ) > 1:
                        continue
                elif original_starts_at and d.original_starts_at is None:
                    # series-level decisions apply as defaults for occurrence preview
                    pass
                existing_decisions.append(
                    {
                        "target_type": d.target_type,
                        "target_id": d.target_id,
                        "environment_id": d.environment_id,
                        "decision": d.decision,
                        "source": d.source,
                        "reason": d.reason,
                        "actor_id": d.actor_id,
                        "at": d.at.isoformat() if d.at else None,
                    }
                )

    suggested = []
    for sug in analysis.downstream:
        key = sug.key
        item = dep_analysis.suggested_to_dict(sug, db)
        if key in exclude_keys:
            item["selection"] = "excluded"
            item["exclude_reason"] = exclude_reasons.get(key)
        else:
            item["selection"] = "suggested"
        suggested.append(item)

    direct = [dep_analysis.suggested_to_dict(s, db) for s in analysis.direct]
    for d in direct:
        d["selection"] = "direct"

    manuals = []
    for m in manual_additions or []:
        ref = impacts_from_dicts([m])[0]
        manuals.append(
            {
                "target_type": ref.target_type,
                "target_id": ref.target_id,
                "environment_id": ref.environment_id,
                "display_name": dep_analysis._label(db, ref.target_type, ref.target_id),
                "classification": "manually_confirmed",
                "selection": "manual",
                "paths": [],
                "origins": ["manual"],
                "warnings": [],
            }
        )

    # Proposed effective set = directs + accepted suggestions + manuals − exclusions
    effective: list[ImpactRef] = list(seed_refs)
    for sug in analysis.downstream:
        if sug.key in exclude_keys:
            continue
        effective.append(
            ImpactRef(sug.target_type, sug.target_id, sug.environment_id)
        )
    for m in manual_additions or []:
        effective.extend(impacts_from_dicts([m]))
    # Dedupe
    seen: set[tuple[str, str, str | None]] = set()
    deduped: list[ImpactRef] = []
    for i in effective:
        k = (i.target_type, i.target_id, i.environment_id)
        if k in seen or k in exclude_keys:
            continue
        seen.add(k)
        deduped.append(i)

    audience = preview_notification_audience(
        db,
        event=event,
        selected_impacts=deduped,
        include_destinations=include_destinations,
    )
    conflicts = find_scheduling_conflicts(
        db,
        starts_at=starts_at,
        ends_at=ends_at,
        selected=deduped,
        exclude_event_id=event_id,
    )
    fp = dependency_fingerprint(db)
    token = build_revision_token(
        seeds=seed_refs,
        starts_at=starts_at,
        ends_at=ends_at,
        event_id=event_id,
        impact_revision=impact_revision,
        dependency_fingerprint=fp,
        max_depth=max_depth,
        original_starts_at=original_starts_at,
        exclusions=exclusions,
        manual_additions=manual_additions,
        proposed=deduped,
    )

    return {
        "revision_token": token,
        "impact_revision": impact_revision,
        "dependency_fingerprint": fp,
        "analyzed_at": analysis.analyzed_at.isoformat(),
        "max_depth": analysis.max_depth,
        "direct_targets": direct,
        "suggested_downstream": suggested,
        "manual_additions": manuals,
        "exclusions": [
            {
                "target_type": t,
                "target_id": i,
                "environment_id": e,
                "reason": exclude_reasons.get((t, i, e)),
            }
            for (t, i, e) in exclude_keys
        ],
        "proposed_effective_impacts": [
            {
                "target_type": i.target_type,
                "target_id": i.target_id,
                "environment_id": i.environment_id,
                "display_name": dep_analysis._label(db, i.target_type, i.target_id),
            }
            for i in deduped
        ],
        "existing_decisions": existing_decisions,
        "warnings": [
            {
                "code": w.code,
                "message": w.message,
                "subject_type": w.subject_type,
                "subject_id": w.subject_id,
            }
            for w in analysis.warnings
        ],
        "audience": audience,
        "conflicts": conflicts,
        "read_only": True,
        "notifications_sent": False,
    }


def confirm_impact_analysis(
    db: Session,
    event: MaintenanceEvent,
    *,
    revision_token: str,
    seeds: list[dict[str, Any]],
    starts_at: datetime,
    ends_at: datetime,
    exclusions: list[dict[str, Any]] | None,
    manual_additions: list[dict[str, Any]] | None,
    include_downstream: list[dict[str, Any]] | None,
    original_starts_at: datetime | None,
    actor_id: str | None,
    max_depth: int = dep_analysis.DEFAULT_MAX_DEPTH,
    publish: bool = True,
) -> MaintenanceEvent:
    """Validate revision, persist decisions + effective impacts, optionally confirm+outbox.

    Never deletes delivery/audit history. Confirmed occurrence selections are not
    silently overwritten on later series reanalysis. Concurrent confirms serialize
    via row lock so only one publish outbox is written per transition.
    """
    from maintenancehub_api.domain import impact_validation as impact_val
    from maintenancehub_api.domain.events import _enqueue_outbox, get_event
    from maintenancehub_api.domain.notifications import schedule_reminders_for_event

    # Serialize concurrent publishers on the same event (Postgres FOR UPDATE).
    locked = (
        db.query(MaintenanceEvent)
        .filter(MaintenanceEvent.id == event.id)
        .with_for_update()
        .first()
    )
    if not locked:
        raise ValueError("Event not found")
    db.refresh(locked)
    event = locked
    baseline_revision = event.impact_revision or 0

    seed_refs = impacts_from_dicts(seeds)
    for s in seed_refs:
        impact_val.ensure_catalog_target_exists(db, s)

    excl = {
        (x["target_type"], x["target_id"], x.get("environment_id"))
        for x in (exclusions or [])
    }
    # Catalog existence checked here; grant checks for manuals happen in the API layer.
    manual_refs = impacts_from_dicts(manual_additions or [])
    for m in manual_refs:
        impact_val.ensure_catalog_target_exists(db, m)

    if include_downstream is not None:
        down_refs = impact_val.validate_include_downstream(
            db,
            seeds=seed_refs,
            include_downstream=include_downstream,
            max_depth=max_depth,
        )
        final_refs = list(seed_refs) + list(down_refs) + list(manual_refs)
        seen: set[tuple[str, str, str | None]] = set()
        final: list[ImpactRef] = []
        for r in final_refs:
            k = (r.target_type, r.target_id, r.environment_id)
            if k in excl or k in seen:
                continue
            seen.add(k)
            final.append(r)
        fp = dependency_fingerprint(db)
        expected = build_revision_token(
            seeds=seed_refs,
            starts_at=starts_at,
            ends_at=ends_at,
            event_id=event.id,
            impact_revision=baseline_revision,
            dependency_fingerprint=fp,
            max_depth=max_depth,
            original_starts_at=original_starts_at,
            exclusions=exclusions,
            manual_additions=manual_additions,
            proposed=final,
        )
        if expected != revision_token:
            raise ValueError(
                "Stale or unreviewed selection — dependency graph, event revision, "
                "or reviewed impacts changed; re-run preview"
            )
    else:
        preview = build_preview(
            db,
            seeds=seeds,
            starts_at=starts_at,
            ends_at=ends_at,
            event_id=event.id,
            original_starts_at=original_starts_at,
            exclusions=exclusions,
            manual_additions=manual_additions,
            max_depth=max_depth,
            include_destinations=False,
        )
        if preview["revision_token"] != revision_token:
            raise ValueError(
                "Stale impact preview — dependency graph or event revision changed; re-run preview"
            )
        final = impacts_from_dicts(
            [
                {
                    "target_type": x["target_type"],
                    "target_id": x["target_id"],
                    "environment_id": x.get("environment_id"),
                }
                for x in preview["proposed_effective_impacts"]
            ]
        )

    # Another publisher may have committed between our lock wait and refresh.
    if (event.impact_revision or 0) != baseline_revision:
        raise ValueError(
            "Stale impact preview — concurrent publisher updated this event; re-run preview"
        )

    now = _now()
    was_confirmed = event.approval_state == ApprovalState.confirmed_scheduled
    prior_rows = (
        db.query(EventImpact).filter(EventImpact.event_id == event.id).all()
    )
    prior_impact_keys = {
        (
            i.target_type.value if hasattr(i.target_type, "value") else str(i.target_type),
            i.target_id,
            i.environment_id,
        )
        for i in prior_rows
    }

    decisions: list[ImpactDecision] = []

    def _add_decision(
        *,
        ref: ImpactRef,
        decision: str,
        source: str,
        reason: str | None = None,
        path: Any = None,
    ) -> None:
        decisions.append(
            ImpactDecision(
                event_id=event.id,
                original_starts_at=ensure_utc(original_starts_at)
                if original_starts_at
                else None,
                target_type=ref.target_type,
                target_id=ref.target_id,
                environment_id=ref.environment_id,
                decision=decision,
                source=source,
                reason=reason,
                path_json=path,
                revision_token=revision_token,
                actor_id=actor_id,
                at=now,
            )
        )

    seed_keys = {(s.target_type, s.target_id, s.environment_id) for s in seed_refs}
    manual_keys = {(m.target_type, m.target_id, m.environment_id) for m in manual_refs}
    for r in final:
        k = (r.target_type, r.target_id, r.environment_id)
        if k in manual_keys:
            src = "manual"
            dec = "manual"
        elif k in seed_keys:
            src = "direct"
            dec = "included"
        else:
            src = "downstream"
            dec = "included"
        _add_decision(ref=r, decision=dec, source=src)

    for x in exclusions or []:
        _add_decision(
            ref=ImpactRef(x["target_type"], x["target_id"], x.get("environment_id")),
            decision="excluded",
            source="downstream",
            reason=x.get("reason"),
        )

    for d in decisions:
        db.add(d)

    if original_starts_at is not None:
        from maintenancehub_api.domain import occurrences as occurrence_service

        occ, record = occurrence_service.resolve_occurrence(
            db, event, original_starts_at=original_starts_at
        )
        record = record or occurrence_service.get_or_create_record(
            db, event, original_starts_at=occ.original_starts_at, actor_id=actor_id
        )
        record.impacts_overridden = True
        for row in list(record.impacts or []):
            db.delete(row)
        db.flush()
        for r in final:
            try:
                tt = ImpactTargetType(r.target_type)
            except ValueError:
                continue
            db.add(
                OccurrenceImpact(
                    occurrence_id=record.id,
                    target_type=tt,
                    target_id=r.target_id,
                    environment_id=r.environment_id,
                )
            )
    else:
        # SQL delete avoids stale identity-map collections under concurrency
        db.query(EventImpact).filter(EventImpact.event_id == event.id).delete(
            synchronize_session=False
        )
        db.flush()
        for r in final:
            try:
                tt = ImpactTargetType(r.target_type)
            except ValueError:
                continue
            db.add(
                EventImpact(
                    event_id=event.id,
                    target_type=tt,
                    target_id=r.target_id,
                    environment_id=r.environment_id,
                )
            )

    event.impact_revision = baseline_revision + 1
    event.updated_by = actor_id

    new_keys = {(r.target_type, r.target_id, r.environment_id) for r in final}
    impacts_changed = new_keys != prior_impact_keys

    db.add(
        EventTimelineEntry(
            event_id=event.id,
            at=now,
            actor_id=actor_id,
            entry_type=TimelineEntryType.system,
            payload={
                "action": "impact_analysis_confirmed",
                "revision_token": revision_token,
                "impact_revision": event.impact_revision,
                "occurrence_original_starts_at": (
                    ensure_utc(original_starts_at).isoformat() if original_starts_at else None
                ),
                "included": len(final),
                "excluded": len(exclusions or []),
                "publish": publish,
                "impacts_changed": impacts_changed,
            },
        )
    )

    if publish and event.approval_state != ApprovalState.confirmed_scheduled:
        previous = event.approval_state
        event.approval_state = ApprovalState.confirmed_scheduled
        db.add(
            EventTimelineEntry(
                event_id=event.id,
                at=now,
                actor_id=actor_id,
                entry_type=TimelineEntryType.system,
                payload={
                    "action": "approval_state_change",
                    "from_approval": previous.value,
                    "to_approval": event.approval_state.value,
                    "via": "impact_analysis_confirm",
                },
            )
        )
        _enqueue_outbox(
            db,
            event=event,
            event_type="event.confirmed",
            payload={
                "from_approval": previous.value,
                "to_approval": event.approval_state.value,
                "via": "impact_analysis_confirm",
            },
        )
    elif was_confirmed and impacts_changed:
        # Recalculate audience path via outbox; do not re-send unchanged deliveries
        # (idempotency keys + reminder reconcile). Never notify excluded-only apps.
        _enqueue_outbox(
            db,
            event=event,
            event_type="event.impacts_changed",
            payload={
                "via": "impact_analysis_confirm",
                "impact_revision": event.impact_revision,
            },
        )

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        # Concurrent insert races (should be rare after FOR UPDATE) → stale
        from sqlalchemy.exc import IntegrityError

        if isinstance(exc, IntegrityError):
            raise ValueError(
                "Stale impact preview — concurrent publisher updated this event; re-run preview"
            ) from exc
        raise
    refreshed = get_event(db, event.id)
    if refreshed and refreshed.approval_state == ApprovalState.confirmed_scheduled:
        # Reconcile pending reminders to new effective impacts; keep sent history.
        schedule_reminders_for_event(db, refreshed)
        refreshed = get_event(db, event.id)
    return refreshed  # type: ignore[return-value]
