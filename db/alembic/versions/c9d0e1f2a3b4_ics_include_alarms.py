"""calendar_tokens.include_alarms for ICS VALARM

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-13 19:55:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _cols(table: str) -> set[str]:
    insp = inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _cols("calendar_tokens")
    if "include_alarms" not in cols:
        with op.batch_alter_table("calendar_tokens") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "include_alarms",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("0"),
                )
            )


def downgrade() -> None:
    cols = _cols("calendar_tokens")
    if "include_alarms" in cols:
        with op.batch_alter_table("calendar_tokens") as batch_op:
            batch_op.drop_column("include_alarms")
