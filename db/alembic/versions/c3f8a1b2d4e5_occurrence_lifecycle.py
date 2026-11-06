"""occurrence_lifecycle sparse records

Revision ID: c3f8a1b2d4e5
Revises: 944d2ea0d00b
Create Date: 2026-11-04 11:40:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f8a1b2d4e5"
down_revision: Union[str, None] = "944d2ea0d00b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Reuse existing Postgres enum types; SQLite stores these as VARCHAR.
    event_status = sa.Enum(
        "scheduled",
        "in_progress",
        "extended",
        "verifying",
        "completed",
        "cancelled",
        name="event_status",
        create_constraint=False,
    )
    event_status.create(op.get_bind(), checkfirst=True)
    impact_target_type = sa.Enum(
        "application",
        "service",
        "infra_component",
        name="impact_target_type",
        create_constraint=False,
    )
    impact_target_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "occurrence_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("original_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", event_status, nullable=False),
        sa.Column("expected_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_impact", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "impacts_overridden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["event_id"], ["maintenance_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "original_starts_at", name="uq_occurrence_identity"),
    )
    with op.batch_alter_table("occurrence_records", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_occurrence_records_event_id"), ["event_id"], unique=False
        )
        batch_op.create_index(
            "ix_occurrence_event_status", ["event_id", "status"], unique=False
        )

    op.create_table(
        "occurrence_impacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("occurrence_id", sa.String(length=36), nullable=False),
        sa.Column("target_type", impact_target_type, nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["environment_id"], ["environments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["occurrence_id"], ["occurrence_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "occurrence_id",
            "target_type",
            "target_id",
            "environment_id",
            name="uq_occurrence_impact",
        ),
    )
    with op.batch_alter_table("occurrence_impacts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_occurrence_impacts_occurrence_id"),
            ["occurrence_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("occurrence_impacts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_occurrence_impacts_occurrence_id"))
    op.drop_table("occurrence_impacts")
    with op.batch_alter_table("occurrence_records", schema=None) as batch_op:
        batch_op.drop_index("ix_occurrence_event_status")
        batch_op.drop_index(batch_op.f("ix_occurrence_records_event_id"))
    op.drop_table("occurrence_records")
