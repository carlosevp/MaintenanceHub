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
    """Global environment definition (catalog).

    Distinct from ``AppEnvironment`` (an application's deployment instance of a
    definition, e.g. Claims/INT). Prefer ``is_active=False`` over delete when
    historical impacts/subscriptions still reference the row.
    """

    __tablename__ = "environments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


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
    """Edge: ``from`` depends on ``to`` (consumer → provider).

    Impact traversal walks reverse edges: maintenance on a provider finds consumers.
    Optional environment endpoints support cross-env edges (e.g. Claims INT → Oracle NON-PROD).
    """

    __tablename__ = "dependencies"
    __table_args__ = (
        UniqueConstraint(
            "from_type",
            "from_id",
            "to_type",
            "to_id",
            "dependency_kind",
            "from_environment_id",
            "to_environment_id",
            name="uq_dependency",
        ),
        Index("ix_dependency_provider", "to_type", "to_id"),
        Index("ix_dependency_consumer", "from_type", "from_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    from_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_id: Mapped[str] = mapped_column(String(36), nullable=False)
    to_type: Mapped[str] = mapped_column(String(64), nullable=False)
    to_id: Mapped[str] = mapped_column(String(36), nullable=False)
    dependency_kind: Mapped[str] = mapped_column(String(64), default="depends_on", nullable=False)
    origin: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    from_environment_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("environments.id", ondelete="SET NULL"), nullable=True
    )
    to_environment_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("environments.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


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
    # Optimistic concurrency for impact-analysis confirm (M14)
    impact_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    impacts: Mapped[list[EventImpact]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    impact_decisions: Mapped[list["ImpactDecision"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    timeline: Mapped[list[EventTimelineEntry]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="EventTimelineEntry.at"
    )
    recurrence_rule: Mapped[Optional[RecurrenceRule]] = relationship(
        back_populates="event", uselist=False, cascade="all, delete-orphan"
    )
    occurrence_records: Mapped[list["OccurrenceRecord"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
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
    """RFC5545 RRULE stored on the master event; occurrences expanded at query time (M3b)."""

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


class OccurrenceRecord(Base):
    """Sparse per-occurrence state/overrides — only persisted when needed (lifecycle / audit).

    Logical identity is (event_id, original_starts_at) = `{event}@{original}` and is stable
    across reschedule. Series defaults apply when override columns are null.
    """

    __tablename__ = "occurrence_records"
    __table_args__ = (
        UniqueConstraint("event_id", "original_starts_at", name="uq_occurrence_identity"),
        Index("ix_occurrence_event_status", "event_id", "status"),
        Index("ix_occurrence_records_original_starts_at", "original_starts_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("maintenance_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Stable series slot — never rewritten on reschedule
    original_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, name="event_status", create_constraint=False),
        default=EventStatus.scheduled,
        nullable=False,
    )
    # Optional overrides (null = inherit series defaults / expanded times)
    expected_starts_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expected_ends_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actual_starts_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actual_ends_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expected_impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # When True, occurrence_impacts replace series EventImpact for this occurrence
    impacts_overridden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    event: Mapped[MaintenanceEvent] = relationship(back_populates="occurrence_records")
    impacts: Mapped[list[OccurrenceImpact]] = relationship(
        back_populates="occurrence", cascade="all, delete-orphan"
    )


class OccurrenceImpact(Base):
    __tablename__ = "occurrence_impacts"
    __table_args__ = (
        UniqueConstraint(
            "occurrence_id",
            "target_type",
            "target_id",
            "environment_id",
            name="uq_occurrence_impact",
        ),
        Index("ix_occurrence_impacts_target", "target_type", "target_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    occurrence_id: Mapped[str] = mapped_column(
        ForeignKey("occurrence_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[ImpactTargetType] = mapped_column(
        Enum(ImpactTargetType, name="impact_target_type", create_constraint=False),
        nullable=False,
    )
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    environment_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("environments.id", ondelete="SET NULL"), nullable=True
    )

    occurrence: Mapped[OccurrenceRecord] = relationship(back_populates="impacts")


class ImpactDecision(Base):
    """Audit of publisher impact confirmations (include / exclude / manual)."""

    __tablename__ = "impact_decisions"
    __table_args__ = (
        Index("ix_impact_decisions_event", "event_id", "original_starts_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("maintenance_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Null = series-level confirmation; else occurrence original start
    original_starts_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    environment_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # included | excluded | manual
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    # direct | downstream | manual
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    path_json: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    revision_token: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    event: Mapped[MaintenanceEvent] = relationship(back_populates="impact_decisions")


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


DEFAULT_NOTIFY_EVENTS = ("start", "extension", "cancellation", "completion")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    digest_mode: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    # email_address | teams_bridge_channel
    destination_type: Mapped[str] = mapped_column(String(64), default="email_address", nullable=False)
    destination: Mapped[str] = mapped_column(String(320), nullable=False)
    # For teams_bridge_channel: routing key embedded in subject
    bridge_channel_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # Lifecycle interests: start | extension | cancellation | completion (JSON list).
    # Empty/null means all (backward compatible).
    notify_events: Mapped[Any] = mapped_column(JSON, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    targets: Mapped[list[SubscriptionTarget]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )
    reminders: Mapped[list[ReminderOffset]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )


class SubscriptionTarget(Base):
    __tablename__ = "subscription_targets"
    __table_args__ = (
        UniqueConstraint("subscription_id", "target_type", "target_id", name="uq_sub_target"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # application | environment | support_group | event | app_environment
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)

    subscription: Mapped[Subscription] = relationship(back_populates="targets")


class ReminderOffset(Base):
    __tablename__ = "reminder_offsets"
    __table_args__ = (
        UniqueConstraint("subscription_id", "offset_minutes", name="uq_reminder_offset"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Negative = before start (e.g. -1440 = 24h before)
    offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    subscription: Mapped[Subscription] = relationship(back_populates="reminders")


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"
    __table_args__ = (
        Index("ix_notification_templates_event_type", "event_type"),
        Index("ix_notification_templates_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Lifecycle event this template is selected for (e.g. event.created).
    event_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # active | inactive | archived
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    channel: Mapped[str] = mapped_column(String(32), default="smtp", nullable=False)
    subject_template: Mapped[str] = mapped_column(Text, nullable=False)
    # Legacy single body (kept in sync with body_plain_template for older callers).
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_html_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_plain_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    versions: Mapped[list["NotificationTemplateVersion"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="NotificationTemplateVersion.version.desc()",
    )


class NotificationTemplateVersion(Base):
    """Immutable snapshot of a template after each save (M19)."""

    __tablename__ = "notification_template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_template_version"),
        Index("ix_notification_template_versions_template", "template_id", "version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("notification_templates.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    event_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_html_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_plain_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    change_note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    changed_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    template: Mapped["NotificationTemplate"] = relationship(back_populates="versions")


class CalendarToken(Base):
    __tablename__ = "calendar_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    # scopes: favorites | subscriptions | all (JSON list)
    scopes: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_job_idempotency"),
        Index("ix_jobs_run_status", "run_at", "status"),
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_type_created", "job_type", "created_at"),
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
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_delivery_idempotency"),
        Index("ix_notification_deliveries_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    idempotency_key: Mapped[str] = mapped_column(String(400), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)  # smtp | bridge | log
    destination_type: Mapped[str] = mapped_column(
        String(64), default="email_address", nullable=False
    )
    destination: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_plain: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    template_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    template_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Full rendered snapshot persisted before send (subject/html/plain/routing).
    rendered_payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    subscription_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
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
    __table_args__ = (
        Index("ix_audit_log_at", "at"),
        Index("ix_audit_log_action_at", "action", "at"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    summary: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# Integrations — ServiceNow / CSV (M9–M10)
# ---------------------------------------------------------------------------


class IntegrationSetting(Base):
    __tablename__ = "integration_settings"
    __table_args__ = (UniqueConstraint("namespace", "key", name="uq_integration_setting"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)  # servicenow | smtp | bridge
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    # Non-secret config as JSON; secrets referenced by env var name in value
    value: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SnChangeSnapshot(Base):
    __tablename__ = "sn_change_snapshots"
    __table_args__ = (
        UniqueConstraint("source_system", "external_id", name="uq_sn_snapshot_external"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_system: Mapped[str] = mapped_column(String(64), default="servicenow", nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)  # sys_id
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    sys_updated_on: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    raw_payload: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    maintenance_event_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("maintenance_events.id", ondelete="SET NULL"), nullable=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SnUnmatchedRecord(Base):
    __tablename__ = "sn_unmatched_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_system: Mapped[str] = mapped_column(String(64), default="servicenow", nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_payload: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(32), default="open", nullable=False
    )  # open | linked | created | ignored
    resolved_event_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CsvImportJob(Base):
    __tablename__ = "csv_import_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # cmdb_ci | ci_relationships
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="uploaded", nullable=False
    )  # uploaded | previewed | committed | failed
    column_map: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    # overwrite_manual_dependencies when true allows replacing origin=manual edges
    options: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    raw_csv: Mapped[str] = mapped_column(Text, nullable=False)
    preview: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    result_summary: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    committed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
