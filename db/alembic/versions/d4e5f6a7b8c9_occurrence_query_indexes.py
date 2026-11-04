"""occurrence_query_indexes

Revision ID: d4e5f6a7b8c9
Revises: c3f8a1b2d4e5
Create Date: 2026-11-04 12:50:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3f8a1b2d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Identity lookups already covered by uq_occurrence_identity; add supporting
    # indexes for status filters and impact-target matching used by notify/authz.
    with op.batch_alter_table("occurrence_records", schema=None) as batch_op:
        batch_op.create_index(
            "ix_occurrence_records_original_starts_at",
            ["original_starts_at"],
            unique=False,
        )
    with op.batch_alter_table("occurrence_impacts", schema=None) as batch_op:
        batch_op.create_index(
            "ix_occurrence_impacts_target",
            ["target_type", "target_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("occurrence_impacts", schema=None) as batch_op:
        batch_op.drop_index("ix_occurrence_impacts_target")
    with op.batch_alter_table("occurrence_records", schema=None) as batch_op:
        batch_op.drop_index("ix_occurrence_records_original_starts_at")
