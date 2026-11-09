"""m20 environment catalog fields + subscription notify_events

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-09 21:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _insp():
    return inspect(op.get_bind())


def _cols(table: str) -> set[str]:
    insp = _insp()
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    env_cols = _cols("environments")
    if "description" not in env_cols:
        with op.batch_alter_table("environments") as batch_op:
            batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
    env_cols = _cols("environments")
    if "is_active" not in env_cols:
        with op.batch_alter_table("environments") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "is_active",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("1"),
                )
            )

    sub_cols = _cols("subscriptions")
    if "notify_events" not in sub_cols:
        with op.batch_alter_table("subscriptions") as batch_op:
            batch_op.add_column(sa.Column("notify_events", sa.JSON(), nullable=True))

    # Idempotent seed of illustrative environment definitions (stable keys).
    # Does not overwrite existing rows; only inserts missing codes.
    bind = op.get_bind()
    defaults = [
        ("DEV", "Development", "Day-to-day development", 10),
        ("INT", "Integration", "Integrated non-production", 20),
        ("QA", "QA", "Quality assurance", 30),
        ("UAT", "UAT", "User acceptance", 40),
        ("PROD", "Production", "Production", 50),
        ("PERF", "Performance", "Performance / load testing", 60),
        ("DR", "Disaster Recovery", "Disaster recovery", 70),
        ("NON-PROD", "Non-Production shared", "Shared non-production infrastructure", 15),
    ]
    existing = {
        row[0]
        for row in bind.execute(sa.text("SELECT key FROM environments")).fetchall()
    }
    import uuid

    for key, name, description, sort_order in defaults:
        if key in existing:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO environments (id, key, name, description, sort_order, is_active) "
                "VALUES (:id, :key, :name, :description, :sort_order, :is_active)"
            ),
            {
                "id": str(uuid.uuid4()),
                "key": key,
                "name": name,
                "description": description,
                "sort_order": sort_order,
                "is_active": True,
            },
        )


def downgrade() -> None:
    sub_cols = _cols("subscriptions")
    if "notify_events" in sub_cols:
        with op.batch_alter_table("subscriptions") as batch_op:
            batch_op.drop_column("notify_events")
    env_cols = _cols("environments")
    if "is_active" in env_cols:
        with op.batch_alter_table("environments") as batch_op:
            batch_op.drop_column("is_active")
    env_cols = _cols("environments")
    if "description" in env_cols:
        with op.batch_alter_table("environments") as batch_op:
            batch_op.drop_column("description")
