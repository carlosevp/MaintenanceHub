"""m19 notification template manager — versions, HTML/plain, delivery payload

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-11-06 18:40:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _insp():
    return inspect(op.get_bind())


def _cols(table: str) -> set[str]:
    insp = _insp()
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _has_table(name: str) -> bool:
    return _insp().has_table(name)


def _has_index(table: str, name: str) -> bool:
    insp = _insp()
    if not insp.has_table(table):
        return False
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def upgrade() -> None:
    # SQLite cannot ADD COLUMN … NOT NULL with a non-constant default (CURRENT_TIMESTAMP).
    # Add columns idempotently so a partial previous attempt can finish.
    existing = _cols("notification_templates")
    adds: list[tuple[str, sa.Column]] = [
        ("name", sa.Column("name", sa.String(length=200), nullable=True)),
        ("description", sa.Column("description", sa.Text(), nullable=True)),
        ("event_type", sa.Column("event_type", sa.String(length=100), nullable=True)),
        ("status", sa.Column("status", sa.String(length=32), server_default="active", nullable=False)),
        ("body_html_template", sa.Column("body_html_template", sa.Text(), nullable=True)),
        ("body_plain_template", sa.Column("body_plain_template", sa.Text(), nullable=True)),
        ("version", sa.Column("version", sa.Integer(), server_default="1", nullable=False)),
        (
            "is_system",
            sa.Column("is_system", sa.Boolean(), server_default=sa.false(), nullable=False),
        ),
        ("created_by", sa.Column("created_by", sa.String(length=36), nullable=True)),
        ("updated_by", sa.Column("updated_by", sa.String(length=36), nullable=True)),
        # nullable + backfill — avoids SQLite "non-constant default" error
        ("created_at", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)),
    ]
    for name, col in adds:
        if name not in existing:
            op.add_column("notification_templates", col)

    if not _has_index("notification_templates", "ix_notification_templates_event_type"):
        op.create_index(
            "ix_notification_templates_event_type", "notification_templates", ["event_type"]
        )
    if not _has_index("notification_templates", "ix_notification_templates_status"):
        op.create_index("ix_notification_templates_status", "notification_templates", ["status"])

    # Dialect-safe backfill (SQLite quotes "key"; Postgres uses quoted identifier too).
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    true_lit = "TRUE" if is_pg else "1"
    key_ident = '"key"'  # reserved-ish on both engines when quoted
    op.execute(
        sa.text(
            f"""
            UPDATE notification_templates
            SET body_plain_template = COALESCE(body_plain_template, body_template),
                name = COALESCE(name, {key_ident}),
                event_type = COALESCE(event_type, {key_ident}),
                is_system = {true_lit},
                created_at = COALESCE(created_at, CURRENT_TIMESTAMP)
            """
        )
    )

    if not _has_table("notification_template_versions"):
        op.create_table(
            "notification_template_versions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "template_id",
                sa.String(length=36),
                sa.ForeignKey("notification_templates.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=True),
            sa.Column("event_type", sa.String(length=100), nullable=True),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("subject_template", sa.Text(), nullable=False),
            sa.Column("body_template", sa.Text(), nullable=False),
            sa.Column("body_html_template", sa.Text(), nullable=True),
            sa.Column("body_plain_template", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("change_note", sa.String(length=500), nullable=True),
            sa.Column("changed_by", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("template_id", "version", name="uq_template_version"),
        )
    if not _has_index(
        "notification_template_versions", "ix_notification_template_versions_template"
    ):
        op.create_index(
            "ix_notification_template_versions_template",
            "notification_template_versions",
            ["template_id", "version"],
        )

    d_existing = _cols("notification_deliveries")
    for name, col in [
        ("body_html", sa.Column("body_html", sa.Text(), nullable=True)),
        ("body_plain", sa.Column("body_plain", sa.Text(), nullable=True)),
        ("template_id", sa.Column("template_id", sa.String(length=36), nullable=True)),
        ("template_version", sa.Column("template_version", sa.Integer(), nullable=True)),
        ("rendered_payload", sa.Column("rendered_payload", sa.JSON(), nullable=True)),
    ]:
        if name not in d_existing:
            op.add_column("notification_deliveries", col)


def downgrade() -> None:
    d_existing = _cols("notification_deliveries")
    for name in ("rendered_payload", "template_version", "template_id", "body_plain", "body_html"):
        if name in d_existing:
            op.drop_column("notification_deliveries", name)
    if _has_index(
        "notification_template_versions", "ix_notification_template_versions_template"
    ):
        op.drop_index(
            "ix_notification_template_versions_template",
            table_name="notification_template_versions",
        )
    if _has_table("notification_template_versions"):
        op.drop_table("notification_template_versions")
    if _has_index("notification_templates", "ix_notification_templates_status"):
        op.drop_index("ix_notification_templates_status", table_name="notification_templates")
    if _has_index("notification_templates", "ix_notification_templates_event_type"):
        op.drop_index("ix_notification_templates_event_type", table_name="notification_templates")
    existing = _cols("notification_templates")
    for name in (
        "created_at",
        "updated_by",
        "created_by",
        "is_system",
        "version",
        "body_plain_template",
        "body_html_template",
        "status",
        "event_type",
        "description",
        "name",
    ):
        if name in existing:
            op.drop_column("notification_templates", name)
