"""SQLAlchemy models for MaintenanceHub core schema (M1)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from maintenancehub_api.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class RoleName(str, enum.Enum):
    viewer = "viewer"
    publisher = "publisher"
    application_owner = "application_owner"
    platform_administrator = "platform_administrator"


class CatalogStatus(str, enum.Enum):
    active = "active"
    retired = "retired"


class EventKind(str, enum.Enum):
    planned_maintenance = "planned_maintenance"
    manual_outage = "manual_outage"


class EventStatus(str, enum.Enum):
    scheduled = "scheduled"
    in_progress = "in_progress"
    extended = "extended"
    verifying = "verifying"
    completed = "completed"
    cancelled = "cancelled"


class ApprovalState(str, enum.Enum):
    approved_window = "approved_window"
    confirmed_scheduled = "confirmed_scheduled"


class OwnerType(str, enum.Enum):
    user = "user"
    support_group = "support_group"


class SubjectType(str, enum.Enum):
    application = "application"
    service = "service"
    infra_component = "infra_component"


class ImpactTargetType(str, enum.Enum):
    application = "application"
    service = "service"
    infra_component = "infra_component"


class TimelineEntryType(str, enum.Enum):
    status_change = "status_change"
    extension = "extension"
    note = "note"
    reschedule = "reschedule"
    system = "system"


class DependencyOrigin(str, enum.Enum):
    manual = "manual"
    import_ = "import"


class JobStatus(str, enum.Enum):
    queued = "queued"
    leased = "leased"
    succeeded = "succeeded"
    failed = "failed"
    dead = "dead"


class DeliveryStatus(str, enum.Enum):
    pending = "pending"
    sending = "sending"
    sent = "sent"
    failed = "failed"
    dead = "dead"


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    external_subject: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    roles: Mapped[list[UserRole]] = relationship(back_populates="user", cascade="all, delete-orphan")
    favorites: Mapped[list[Favorite]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[RoleName] = mapped_column(Enum(RoleName, name="role_name"), unique=True)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)

    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship()


class GroupRoleMapping(Base):
    __tablename__ = "group_role_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    directory_group: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[RoleName] = mapped_column(Enum(RoleName, name="group_role_name"), nullable=False)
    application_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=True
    )


class ApplicationGrant(Base):
    __tablename__ = "application_grants"
    __table_args__ = (
        UniqueConstraint("user_id", "application_id", "role", name="uq_app_grant_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    directory_group: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)  # publisher | application_owner


class ServiceCredential(Base):
    __tablename__ = "service_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    client_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    application_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[CatalogStatus] = mapped_column(
        Enum(CatalogStatus, name="catalog_status"), default=CatalogStatus.active, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    environments: Mapped[list[AppEnvironment]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class Service(Base):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    application_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InfraComponent(Base):
    __tablename__ = "infra_components"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    application_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Environment(Base):
    __tablename__ = "environments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AppEnvironment(Base):
    __tablename__ = "app_environments"
    __table_args__ = (
        UniqueConstraint("application_id", "environment_id", name="uq_app_environment"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    environment_id: Mapped[str] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)

    application: Mapped[Application] = relationship(back_populates="environments")
    environment: Mapped[Environment] = relationship()


class SupportGroup(Base):
    __tablename__ = "support_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    directory_group: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)


class Ownership(Base):
    __tablename__ = "ownerships"
    __table_args__ = (
        UniqueConstraint(
            "subject_type",
            "subject_id",
            "owner_type",
            "owner_id",
            name="uq_ownership",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject_type: Mapped[SubjectType] = mapped_column(
        Enum(SubjectType, name="ownership_subject_type"), nullable=False
    )
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    owner_type: Mapped[OwnerType] = mapped_column(
        Enum(OwnerType, name="owner_type"), nullable=False
    )
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Tagging(Base):
    __tablename__ = "taggings"
    __table_args__ = (
        UniqueConstraint("tag_id", "subject_type", "subject_id", name="uq_tagging"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)


class Dependency(Base):
    __tablename__ = "dependencies"
    __table_args__ = (
        UniqueConstraint(
            "from_type",
            "from_id",
            "to_type",
            "to_id",
            "dependency_kind",
            name="uq_dependency",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    from_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_id: Mapped[str] = mapped_column(String(36), nullable=False)
    to_type: Mapped[str] = mapped_column(String(64), nullable=False)
    to_id: Mapped[str] = mapped_column(String(36), nullable=False)
    dependency_kind: Mapped[str] = mapped_column(String(64), default="depends_on", nullable=False)
    origin: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)


class ExternalCiLink(Base):
    __tablename__ = "external_ci_links"
    __table_args__ = (
        UniqueConstraint("source_system", "external_id", name="uq_external_ci_source"),
        UniqueConstraint(
            "subject_type", "subject_id", "source_system", name="uq_external_ci_subject"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subject_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    raw_payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class MaintenanceEvent(Base):
    __tablename__ = "maintenance_events"
    __table_args__ = (
        UniqueConstraint("source_system", "external_id", name="uq_event_source_external"),
        Index("ix_events_starts_ends", "starts_at", "ends_at"),
        Index("ix_events_status_kind", "status", "kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[EventKind] = mapped_column(Enum(EventKind, name="event_kind"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expected_impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, name="event_status"), default=EventStatus.scheduled, nullable=False
    )
    approval_state: Mapped[ApprovalState] = mapped_column(
        Enum(ApprovalState, name="approval_state"),
        default=ApprovalState.confirmed_scheduled,
        nullable=False,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_system: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    impacts: Mapped[list[EventImpact]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    timeline: Mapped[list[EventTimelineEntry]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="EventTimelineEntry.at"
    )
    recurrence_rule: Mapped[Optional[RecurrenceRule]] = relationship(
        back_populates="event", uselist=False, cascade="all, delete-orphan"
    )


class EventImpact(Base):
    __tablename__ = "event_impacts"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "target_type",
            "target_id",
            "environment_id",
            name="uq_event_impact",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("maintenance_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[ImpactTargetType] = mapped_column(
        Enum(ImpactTargetType, name="impact_target_type"), nullable=False
    )
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    environment_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("environments.id", ondelete="SET NULL"), nullable=True
    )

    event: Mapped[MaintenanceEvent] = relationship(back_populates="impacts")


class EventTimelineEntry(Base):
    __tablename__ = "event_timeline_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("maintenance_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    entry_type: Mapped[TimelineEntryType] = mapped_column(
        Enum(TimelineEntryType, name="timeline_entry_type"), nullable=False
    )
    payload: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)

    event: Mapped[MaintenanceEvent] = relationship(back_populates="timeline")


class RecurrenceRule(Base):
    """Stub for M3b — schema present; expansion incomplete."""

    __tablename__ = "recurrence_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("maintenance_events.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    rrule: Mapped[str] = mapped_column(Text, nullable=False)
    until_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    event: Mapped[MaintenanceEvent] = relationship(back_populates="recurrence_rule")
    exceptions: Mapped[list[RecurrenceException]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )


class RecurrenceException(Base):
    __tablename__ = "recurrence_exceptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rule_id: Mapped[str] = mapped_column(
        ForeignKey("recurrence_rules.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("maintenance_events.id", ondelete="CASCADE"), nullable=False
    )
    original_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # cancel | reschedule
    new_starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    new_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    rule: Mapped[RecurrenceRule] = relationship(back_populates="exceptions")


# ---------------------------------------------------------------------------
# Favorites / subscriptions stubs / jobs
# ---------------------------------------------------------------------------


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "application_id", name="uq_favorite_app"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="favorites")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_job_idempotency"),
        Index("ix_jobs_run_status", "run_at", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), default=JobStatus.queued, nullable=False
    )
    leased_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_delivery_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(400), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    destination: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status"),
        default=DeliveryStatus.pending,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    summary: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
