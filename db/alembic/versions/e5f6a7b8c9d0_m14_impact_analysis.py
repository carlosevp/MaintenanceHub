"""m14_impact_analysis

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-04 13:20:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("maintenance_events", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("impact_revision", sa.Integer(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("dependencies", schema=None) as batch_op:
        batch_op.add_column(sa.Column("from_environment_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("to_environment_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            )
        )
        batch_op.create_foreign_key(
            "fk_dep_from_env", "environments", ["from_environment_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            "fk_dep_to_env", "environments", ["to_environment_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.drop_constraint("uq_dependency", type_="unique")
        batch_op.create_unique_constraint(
            "uq_dependency",
            [
                "from_type",
                "from_id",
                "to_type",
                "to_id",
                "dependency_kind",
                "from_environment_id",
                "to_environment_id",
            ],
        )
        batch_op.create_index("ix_dependency_provider", ["to_type", "to_id"], unique=False)
        batch_op.create_index("ix_dependency_consumer", ["from_type", "from_id"], unique=False)

    with op.batch_alter_table("external_ci_links", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            )
        )

    op.create_table(
        "impact_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("original_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("environment_id", sa.String(length=36), nullable=True),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("path_json", sa.JSON(), nullable=True),
        sa.Column("revision_token", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["event_id"], ["maintenance_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("impact_decisions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_impact_decisions_event_id"), ["event_id"], unique=False
        )
        batch_op.create_index(
            "ix_impact_decisions_event", ["event_id", "original_starts_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("impact_decisions", schema=None) as batch_op:
        batch_op.drop_index("ix_impact_decisions_event")
        batch_op.drop_index(batch_op.f("ix_impact_decisions_event_id"))
    op.drop_table("impact_decisions")

    with op.batch_alter_table("external_ci_links", schema=None) as batch_op:
        batch_op.drop_column("updated_at")

    with op.batch_alter_table("dependencies", schema=None) as batch_op:
        batch_op.drop_index("ix_dependency_consumer")
        batch_op.drop_index("ix_dependency_provider")
        batch_op.drop_constraint("uq_dependency", type_="unique")
        batch_op.create_unique_constraint(
            "uq_dependency",
            ["from_type", "from_id", "to_type", "to_id", "dependency_kind"],
        )
        batch_op.drop_constraint("fk_dep_to_env", type_="foreignkey")
        batch_op.drop_constraint("fk_dep_from_env", type_="foreignkey")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("to_environment_id")
        batch_op.drop_column("from_environment_id")

    with op.batch_alter_table("maintenance_events", schema=None) as batch_op:
        batch_op.drop_column("impact_revision")
