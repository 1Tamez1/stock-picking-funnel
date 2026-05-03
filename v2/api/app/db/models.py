from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import JSON
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from app.db.base import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OwnerUser(Base):
    __tablename__ = "owner_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(Integer, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="Owner")
    password_salt: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("owner_users.id"), nullable=False)
    session_token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(String(1024), nullable=False, default="")


class OwnerApiToken(Base):
    __tablename__ = "owner_api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("owner_users.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="Agent Token")
    token_prefix: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    scopes_json: Mapped[Optional[list[str]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Stage(Base):
    __tablename__ = "stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    ticker: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    bucket: Mapped[str] = mapped_column(String(64), nullable=False, default="pool")
    current_stage_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stages.id"))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    schema_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TemplateSectionModule(Base):
    __tablename__ = "template_section_modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"), nullable=False)
    stage_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    section_id: Mapped[str] = mapped_column(String(255), nullable=False)
    section_title: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    section_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    section_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    module_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id"), nullable=False)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    report_month: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    responses_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    section_ratings_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    data_quality_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    field_sources_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    field_notes_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    field_exceptions_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[str] = mapped_column(String(128), nullable=False, default="Draft")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    watchlist_conditions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    watchlist_objective_rules_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    watchlist_subjective_rules: Mapped[str] = mapped_column(Text, nullable=False, default="")
    archive_red_flags: Mapped[str] = mapped_column(Text, nullable=False, default="")
    next_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_date: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    completed_at: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReportSectionModule(Base):
    __tablename__ = "report_section_modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), nullable=False)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"), nullable=False)
    stage_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    section_id: Mapped[str] = mapped_column(String(255), nullable=False)
    section_title: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    section_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    section_ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    module_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    report_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reports.id"))
    original_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    legacy_storage_path: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_storage_key: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    normalized_text_path: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    normalized_status: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    normalized_format: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    normalized_method: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    normalized_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_preview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_updated_at: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    uploaded_at: Mapped[str] = mapped_column(String(255), nullable=False)


class ReportSource(Base):
    __tablename__ = "report_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), nullable=False)
    document_id: Mapped[Optional[int]] = mapped_column(ForeignKey("documents.id"))
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    capture_kind: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    evidence_grade: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    confidence: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    tags_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    link_only_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    snapshot_guidance_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capture_state: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    capture_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    citation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(128), nullable=False)
    document_id: Mapped[Optional[int]] = mapped_column(ForeignKey("documents.id"))
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    leased_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    leased_at: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    available_at: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    completed_at: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MonitoringRule(Base):
    __tablename__ = "monitoring_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    report_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reports.id"))
    report_rule_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    comparator: Mapped[str] = mapped_column(String(8), nullable=False)
    threshold_value: Mapped[Optional[float]] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    current_value: Mapped[Optional[float]] = mapped_column(Float)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_checked_at: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EndpointSnapshot(Base):
    __tablename__ = "endpoint_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    request_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    report_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reports.id"))
    section_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    run_kind: Mapped[str] = mapped_column(String(128), nullable=False, default="report_completion")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="created")
    orchestrator: Mapped[str] = mapped_column(String(128), nullable=False, default="langgraph")
    mcp_session_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    prompt_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class AgentRunStep(Base):
    __tablename__ = "agent_run_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), nullable=False)
    step_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="created")
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agent_runs.id"))
    step_id: Mapped[Optional[int]] = mapped_column(ForeignKey("agent_run_steps.id"))
    tool_name: Mapped[str] = mapped_column(String(255), nullable=False)
    arguments_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="created")
    request_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
