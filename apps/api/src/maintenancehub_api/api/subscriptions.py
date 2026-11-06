from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from maintenancehub_api.db import get_db
from maintenancehub_api.deps import AuthUser, get_current_user
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


@router.get("", response_model=list[SubscriptionOut])
def list_subscriptions(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> list[Subscription]:
    return (
        db.query(Subscription)
        .options(joinedload(Subscription.targets), joinedload(Subscription.reminders))
        .filter(Subscription.user_id == user.id)
        .order_by(Subscription.created_at.desc())
        .all()
    )


@router.post("", response_model=SubscriptionOut, status_code=201)
def create_subscription(
    body: SubscriptionCreate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> Subscription:
    if body.destination_type == "teams_bridge_channel" and not body.bridge_channel_key:
        raise HTTPException(
            status_code=400,
            detail="bridge_channel_key required for Teams via email bridge destinations",
        )
    sub = Subscription(
        user_id=user.id,
        destination_type=body.destination_type,
        destination=body.destination,
        bridge_channel_key=body.bridge_channel_key,
        digest_mode=body.digest_mode,
    )
    db.add(sub)
    db.flush()
    for t in body.targets:
        db.add(
            SubscriptionTarget(
                subscription_id=sub.id, target_type=t.target_type, target_id=t.target_id
            )
        )
    for r in body.reminders:
        db.add(ReminderOffset(subscription_id=sub.id, offset_minutes=r.offset_minutes))
    db.commit()
    return _load(db, sub.id, user.id)  # type: ignore[return-value]


@router.get("/{sub_id}", response_model=SubscriptionOut)
def get_subscription(
    sub_id: str,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> Subscription:
    sub = _load(db, sub_id, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return sub


@router.patch("/{sub_id}", response_model=SubscriptionOut)
def patch_subscription(
    sub_id: str,
    body: SubscriptionUpdate,
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> Subscription:
    sub = _load(db, sub_id, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(sub, k, v)
    db.commit()
    return _load(db, sub_id, user.id)  # type: ignore[return-value]


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
) -> Subscription:
    sub = _load(db, sub_id, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    db.query(SubscriptionTarget).filter(SubscriptionTarget.subscription_id == sub_id).delete()
    for t in body:
        db.add(
            SubscriptionTarget(
                subscription_id=sub_id, target_type=t.target_type, target_id=t.target_id
            )
        )
    db.commit()
    return _load(db, sub_id, user.id)  # type: ignore[return-value]


@router.put("/{sub_id}/reminders", response_model=SubscriptionOut)
def put_reminders(
    sub_id: str,
    body: list[ReminderIn],
    db: Session = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> Subscription:
    sub = _load(db, sub_id, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    db.query(ReminderOffset).filter(ReminderOffset.subscription_id == sub_id).delete()
    for r in body:
        db.add(ReminderOffset(subscription_id=sub_id, offset_minutes=r.offset_minutes))
    db.commit()
    return _load(db, sub_id, user.id)  # type: ignore[return-value]
