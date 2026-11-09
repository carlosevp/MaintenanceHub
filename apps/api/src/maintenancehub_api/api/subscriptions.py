from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user
from maintenancehub_api.domain.subscription_display import (
    enrich_subscription,
    normalize_notify_events,
)
from maintenancehub_api.models import ReminderOffset, Subscription, SubscriptionTarget
from maintenancehub_api.schemas.subscriptions import (
    ReminderIn,
    SubscriptionCreate,
    SubscriptionOut,
    SubscriptionUpdate,
    TargetIn,
)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def _load(db: Session, sub_id: str, user_id: str) -> Subscription | None:
    return (
        db.query(Subscription)
        .options(joinedload(Subscription.targets), joinedload(Subscription.reminders))
        .filter(Subscription.id == sub_id, Subscription.user_id == user_id)
        .first()
    )


def _out(db: Session, sub: Subscription) -> SubscriptionOut:
    return SubscriptionOut.model_validate(enrich_subscription(db, sub))


def _replace_targets(db: Session, sub_id: str, targets: list[TargetIn]) -> None:
    db.query(SubscriptionTarget).filter(SubscriptionTarget.subscription_id == sub_id).delete()
    for t in targets:
        db.add(
            SubscriptionTarget(
                subscription_id=sub_id, target_type=t.target_type, target_id=t.target_id
            )
        )


def _replace_reminders(db: Session, sub_id: str, reminders: list[ReminderIn]) -> None:
    db.query(ReminderOffset).filter(ReminderOffset.subscription_id == sub_id).delete()
    for r in reminders:
        db.add(ReminderOffset(subscription_id=sub_id, offset_minutes=r.offset_minutes))


@router.get("", response_model=list[SubscriptionOut])
def list_subscriptions(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> list[SubscriptionOut]:
    rows = (
        db.query(Subscription)
        .options(joinedload(Subscription.targets), joinedload(Subscription.reminders))
        .filter(Subscription.user_id == user.id)
        .order_by(Subscription.created_at.desc())
        .all()
    )
    return [_out(db, s) for s in rows]


@router.post("", response_model=SubscriptionOut, status_code=201)
def create_subscription(
    body: SubscriptionCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> SubscriptionOut:
    if body.destination_type == "teams_bridge_channel" and not body.bridge_channel_key:
        raise HTTPException(
            status_code=400,
            detail="bridge_channel_key required for Teams via email bridge destinations",
        )
    if not body.targets:
        raise HTTPException(status_code=400, detail="Select at least one target")
    if not body.reminders:
        raise HTTPException(status_code=400, detail="Add at least one reminder offset")
    sub = Subscription(
        user_id=user.id,
        destination_type=body.destination_type,
        destination=body.destination,
        bridge_channel_key=body.bridge_channel_key,
        digest_mode=body.digest_mode,
        notify_events=normalize_notify_events(body.notify_events),
    )
    db.add(sub)
    db.flush()
    _replace_targets(db, sub.id, body.targets)
    _replace_reminders(db, sub.id, body.reminders)
    db.commit()
    return _out(db, _load(db, sub.id, user.id))  # type: ignore[arg-type]


@router.get("/{sub_id}", response_model=SubscriptionOut)
def get_subscription(
    sub_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> SubscriptionOut:
    sub = _load(db, sub_id, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return _out(db, sub)


@router.patch("/{sub_id}", response_model=SubscriptionOut)
def patch_subscription(
    sub_id: str,
    body: SubscriptionUpdate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> SubscriptionOut:
    sub = _load(db, sub_id, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    data = body.model_dump(exclude_unset=True)
    targets = data.pop("targets", None)
    reminders = data.pop("reminders", None)
    if "notify_events" in data:
        data["notify_events"] = normalize_notify_events(data["notify_events"])
    for k, v in data.items():
        setattr(sub, k, v)
    if targets is not None:
        if not targets:
            raise HTTPException(status_code=400, detail="Select at least one target")
        _replace_targets(db, sub_id, [TargetIn.model_validate(t) for t in targets])
    if reminders is not None:
        if not reminders:
            raise HTTPException(status_code=400, detail="Add at least one reminder offset")
        _replace_reminders(db, sub_id, [ReminderIn.model_validate(r) for r in reminders])
    db.commit()
    return _out(db, _load(db, sub_id, user.id))  # type: ignore[arg-type]


@router.delete("/{sub_id}", status_code=204)
def delete_subscription(
    sub_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> None:
    sub = _load(db, sub_id, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    db.delete(sub)
    db.commit()


@router.put("/{sub_id}/targets", response_model=SubscriptionOut)
def put_targets(
    sub_id: str,
    body: list[TargetIn],
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> SubscriptionOut:
    sub = _load(db, sub_id, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if not body:
        raise HTTPException(status_code=400, detail="Select at least one target")
    _replace_targets(db, sub_id, body)
    db.commit()
    return _out(db, _load(db, sub_id, user.id))  # type: ignore[arg-type]


@router.put("/{sub_id}/reminders", response_model=SubscriptionOut)
def put_reminders(
    sub_id: str,
    body: list[ReminderIn],
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> SubscriptionOut:
    sub = _load(db, sub_id, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if not body:
        raise HTTPException(status_code=400, detail="Add at least one reminder offset")
    _replace_reminders(db, sub_id, body)
    db.commit()
    return _out(db, _load(db, sub_id, user.id))  # type: ignore[arg-type]
