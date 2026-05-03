"""section modules and agent run ledger

Revision ID: 20260503_000005
Revises: 20260420_000004
Create Date: 2026-05-03 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260503_000005"
down_revision = "20260420_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("owner_api_tokens", sa.Column("scopes_json", sa.JSON(), nullable=True))

    op.create_table(
        "template_section_modules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("templates.id"), nullable=False),
        sa.Column("stage_key", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("section_id", sa.String(length=255), nullable=False),
        sa.Column("section_title", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("section_path", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("section_ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("module_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("template_id", "section_id", name="uq_template_section_modules_template_section"),
    )
    op.create_index("ix_template_section_modules_template", "template_section_modules", ["template_id", "section_ordinal"])

    op.create_table(
        "report_section_modules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("templates.id"), nullable=False),
        sa.Column("stage_key", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("section_id", sa.String(length=255), nullable=False),
        sa.Column("section_title", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("section_path", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("section_ordinal", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("module_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("report_id", "section_id", name="uq_report_section_modules_report_section"),
    )
    op.create_index("ix_report_section_modules_report", "report_section_modules", ["report_id", "section_ordinal"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id")),
        sa.Column("section_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("run_kind", sa.String(length=128), nullable=False, server_default="report_completion"),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="created"),
        sa.Column("orchestrator", sa.String(length=128), nullable=False, server_default="langgraph"),
        sa.Column("mcp_session_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("prompt_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.String(length=255), nullable=False, server_default=""),
    )
    op.create_index("ix_agent_runs_report", "agent_runs", ["report_id", "status", "id"])

    op.create_table(
        "agent_run_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("step_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="created"),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_run_steps_run", "agent_run_steps", ["run_id", "id"])

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("agent_runs.id")),
        sa.Column("step_id", sa.Integer(), sa.ForeignKey("agent_run_steps.id")),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="created"),
        sa.Column("request_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_tool_calls_run", "agent_tool_calls", ["run_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_agent_tool_calls_run", table_name="agent_tool_calls")
    op.drop_table("agent_tool_calls")
    op.drop_index("ix_agent_run_steps_run", table_name="agent_run_steps")
    op.drop_table("agent_run_steps")
    op.drop_index("ix_agent_runs_report", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_report_section_modules_report", table_name="report_section_modules")
    op.drop_table("report_section_modules")
    op.drop_index("ix_template_section_modules_template", table_name="template_section_modules")
    op.drop_table("template_section_modules")
    op.drop_column("owner_api_tokens", "scopes_json")
