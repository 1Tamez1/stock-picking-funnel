"""shadow endpoint snapshots

Revision ID: 20260420_000002
Revises: 20260420_000001
Create Date: 2026-04-20 18:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260420_000002"
down_revision = "20260420_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "endpoint_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("request_key", sa.String(length=512), nullable=False, unique=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("endpoint_snapshots")
