"""initial v2 schema

Revision ID: 20260420_000001
Revises:
Create Date: 2026-04-20 15:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260420_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "stages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("ticker", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("bucket", sa.String(length=64), nullable=False, server_default="pool"),
        sa.Column("current_stage_id", sa.Integer(), sa.ForeignKey("stages.id")),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "ticker", name="uq_companies_workspace_ticker"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_companies_workspace_slug"),
    )
    op.create_index("ix_companies_bucket", "companies", ["bucket"])
    op.create_index("ix_companies_stage", "companies", ["current_stage_id"])

    op.create_table(
        "templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("stage_id", sa.Integer(), sa.ForeignKey("stages.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("schema_json", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("stage_id", sa.Integer(), sa.ForeignKey("stages.id"), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("templates.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("report_month", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("responses_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("section_ratings_json", sa.JSON(), nullable=False),
        sa.Column("data_quality_json", sa.JSON(), nullable=False),
        sa.Column("field_sources_json", sa.JSON(), nullable=False),
        sa.Column("field_notes_json", sa.JSON(), nullable=False),
        sa.Column("field_exceptions_json", sa.JSON(), nullable=False),
        sa.Column("result", sa.String(length=128), nullable=False, server_default="Draft"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("watchlist_conditions", sa.Text(), nullable=False, server_default=""),
        sa.Column("watchlist_objective_rules_json", sa.JSON(), nullable=False),
        sa.Column("watchlist_subjective_rules", sa.Text(), nullable=False, server_default=""),
        sa.Column("archive_red_flags", sa.Text(), nullable=False, server_default=""),
        sa.Column("next_action", sa.Text(), nullable=False, server_default=""),
        sa.Column("review_date", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("completed_at", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reports_company", "reports", ["company_id"])
    op.create_index("ix_reports_completed", "reports", ["completed_at", "id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id")),
        sa.Column("original_name", sa.String(length=1024), nullable=False),
        sa.Column("stored_name", sa.String(length=1024), nullable=False),
        sa.Column("storage_key", sa.String(length=2048), nullable=False),
        sa.Column("legacy_storage_path", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("mime_type", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("normalized_storage_key", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("normalized_text_path", sa.String(length=2048), nullable=False, server_default=""),
        sa.Column("normalized_status", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("normalized_format", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("normalized_method", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("normalized_notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("normalized_preview", sa.Text(), nullable=False, server_default=""),
        sa.Column("normalized_updated_at", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("uploaded_at", sa.String(length=255), nullable=False),
    )
    op.create_index("ix_documents_company", "documents", ["company_id"])

    op.create_table(
        "report_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id")),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("capture_kind", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("evidence_grade", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("confidence", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("canonical_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("link_only_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("snapshot_guidance_acknowledged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("capture_state", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("capture_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("citation", sa.Text(), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_report_sources_report", "report_sources", ["report_id"])
    op.create_index("ix_report_sources_document", "report_sources", ["document_id"])

    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("kind", sa.String(length=128), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id")),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("leased_by", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("leased_at", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("available_at", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("completed_at", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_background_jobs_status", "background_jobs", ["status", "available_at", "id"])

    op.create_table(
        "monitoring_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id")),
        sa.Column("report_rule_key", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("metric_name", sa.String(length=255), nullable=False),
        sa.Column("comparator", sa.String(length=8), nullable=False),
        sa.Column("threshold_value", sa.Float()),
        sa.Column("unit", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("current_value", sa.Float()),
        sa.Column("source", sa.Text(), nullable=False, server_default=""),
        sa.Column("triggered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_checked_at", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_monitoring_company", "monitoring_rules", ["company_id"])
    op.create_index("ix_monitoring_report_rule", "monitoring_rules", ["report_id", "report_rule_key"])


def downgrade() -> None:
    op.drop_index("ix_monitoring_report_rule", table_name="monitoring_rules")
    op.drop_index("ix_monitoring_company", table_name="monitoring_rules")
    op.drop_table("monitoring_rules")
    op.drop_index("ix_background_jobs_status", table_name="background_jobs")
    op.drop_table("background_jobs")
    op.drop_index("ix_report_sources_document", table_name="report_sources")
    op.drop_index("ix_report_sources_report", table_name="report_sources")
    op.drop_table("report_sources")
    op.drop_index("ix_documents_company", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_reports_completed", table_name="reports")
    op.drop_index("ix_reports_company", table_name="reports")
    op.drop_table("reports")
    op.drop_table("templates")
    op.drop_index("ix_companies_stage", table_name="companies")
    op.drop_index("ix_companies_bucket", table_name="companies")
    op.drop_table("companies")
    op.drop_table("stages")
    op.drop_table("workspaces")

