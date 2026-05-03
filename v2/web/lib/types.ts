export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];

export interface JsonObject {
  [key: string]: JsonValue;
}

export interface StageRecord {
  id: number;
  name: string;
  key?: string;
  description?: string;
  sequence?: number;
  count?: number;
  completed_reports?: number;
}

export interface TemplateField {
  help: string;
  id: string;
  kind: string;
  label: string;
  max: number | null;
  options: string[];
  section_id: string;
  section_title: string;
  path: string;
  ordinal: number;
  notes_required: boolean;
  note_category: string;
  note_placeholder: string;
}

export interface TemplateSection {
  body_markdown: string;
  fields: TemplateField[];
  field_ids: string[];
  id: string;
  level: number;
  path: string;
  title: string;
}

export interface TemplateSchema {
  field_count: number;
  field_lookup: Record<string, TemplateField>;
  fields: TemplateField[];
  schema_version: string;
  section_count: number;
  section_lookup: Record<string, TemplateSection>;
  sections: TemplateSection[];
}

export interface TemplateRecord {
  id: number;
  stage_id: number;
  name: string;
  version: number;
  description: string;
  is_active: number | boolean;
  created_at: string;
  updated_at: string;
  stage_name: string;
  stage_key: string;
  markdown: string;
  schema: TemplateSchema;
}

export interface DocumentRecord {
  id: number;
  company_id: number;
  report_id: number | null;
  original_name: string;
  stored_name: string;
  storage_path: string;
  mime_type: string;
  size_bytes: number;
  notes: string;
  uploaded_at: string;
  normalized_text_path: string;
  normalized_status: string;
  normalized_format: string;
  normalized_method: string;
  normalized_notes: string;
  normalized_preview: string;
  normalized_updated_at: string;
  normalized_available: boolean;
  resource_uri: string;
  download_url: string;
  status_url: string;
  normalized_url: string;
  normalized_resource_uri: string;
}

export interface SourceRecord {
  id: number;
  title: string;
  source_type: string;
  evidence_grade: string;
  confidence: string;
  url: string;
  canonical_url: string;
  citation: string;
  tags: string[];
  notes: string;
  capture_kind: string;
  capture_state: string;
  capture_error: string;
  link_only_reason: string;
  snapshot_guidance_acknowledged: boolean;
  resource_uri: string;
  report_id: number | null;
  report_title?: string;
  report_result?: string;
  report_url?: string;
  stage_key?: string;
  stage_name?: string;
  stage_sequence?: number;
  document_id: number | null;
  document_name: string;
  document_mime_type: string;
  document_resource_uri: string;
  document_download_url: string;
  document_status_url: string;
  document_normalized_url: string;
  document_normalized_resource_uri: string;
  normalized_status: string;
  normalized_format: string;
  normalized_method: string;
  normalized_notes: string;
  normalized_preview: string;
  normalized_text_path: string;
  normalized_available: boolean;
  reusability_status: string;
  reusability_reason: string;
  created_at: string;
  updated_at: string;
  suggestion_reason?: string;
}

export interface MonitoringRuleRecord {
  id: number;
  company_id: number;
  report_id: number | null;
  metric_name: string;
  comparator: string;
  threshold_value: number | null;
  unit: string;
  current_value: number | null;
  source: string;
  triggered: number | boolean;
  notes: string;
  last_checked_at: string;
  created_at: string;
  updated_at: string;
  report_rule_key: string;
  ticker: string;
  company_name: string;
}

export interface ReportSummaryRecord {
  id: number;
  company_id: number;
  title: string;
  report_month: string;
  result: string;
  summary: string;
  next_action: string;
  review_date: string;
  stage_id: number;
  stage_key: string;
  stage_name: string;
  stage_sequence: number;
  updated_at: string;
  created_at: string;
  ticker?: string;
  company_name?: string;
  completed_at?: string;
}

export interface CompanySummaryRecord {
  id: number;
  ticker: string;
  name: string;
  bucket: string;
  current_stage_id: number | null;
  notes: string;
  created_at: string;
  updated_at: string;
  current_stage_name?: string | null;
  current_stage_key?: string | null;
  latest_result?: string;
  latest_summary?: string;
  review_date?: string;
  next_action?: string;
  watchlist_conditions?: string;
  archive_red_flags?: string;
  monitoring_rules?: MonitoringRuleRecord[];
}

export interface FieldContextRecord {
  source_ids: number[];
  citation: string;
}

export interface CompletionFieldLink {
  field_id?: string;
  label: string;
  section_title: string;
  [key: string]: unknown;
}

export interface SectionProgressRecord {
  title: string;
  field_count: number;
  covered_field_count: number;
  [key: string]: unknown;
}

export interface CompletionRecord {
  answered_field_count: number;
  blocked_source_field_ids: string[];
  blocked_source_links: CompletionFieldLink[];
  coverage_pct: number;
  covered_field_count: number;
  decision_requirements: string[];
  exception_missing_note_ids: string[];
  exception_missing_notes: CompletionFieldLink[];
  exempt_field_count: number;
  exempt_field_ids: string[];
  field_count: number;
  final_decision: string;
  legacy_incomplete_finalized: boolean;
  missing_field_ids: string[];
  missing_fields: CompletionFieldLink[];
  missing_required_note_ids: string[];
  missing_required_notes: CompletionFieldLink[];
  missing_source_field_ids: string[];
  missing_source_links: CompletionFieldLink[];
  normalized_ready_source_count: number;
  noted_field_count: number;
  notes_coverage_pct: number;
  required_note_field_count: number;
  required_noted_field_count: number;
  section_progress: SectionProgressRecord[];
  source_count: number;
  source_coverage_pct: number;
  source_required_field_count: number;
  sourced_field_count: number;
  status: string;
  template_field_count: number;
  warnings: string[];
}

export interface UpstreamReportReference {
  id?: number;
  title?: string;
  result?: string;
  summary?: string;
  completed_at?: string;
  stage_name?: string;
  [key: string]: unknown;
}

export interface WorkflowRecord {
  current_stage: JsonObject;
  latest_previous_reports: UpstreamReportReference[];
  latest_upstream_report: UpstreamReportReference | null;
  next_stage: JsonObject | null;
  previous_reports: UpstreamReportReference[];
}

export interface AgentContractRecord {
  completion: CompletionRecord;
  decision_mapping: JsonObject;
  field_exception_statuses: string[];
  fillable_sections: JsonValue[];
  goal: string;
  guidance: string[];
  inherited_fields: string[];
  operations: JsonObject;
  readonly_field_ids: string[];
  report_kind: string;
  resources: JsonValue[];
  suggested_sources: JsonValue[];
  version: number;
  workflow: JsonObject;
}

export interface WatchlistObjectiveRule {
  rule_key: string;
  metric_name: string;
  comparator: string;
  threshold_value: number | string | null;
  unit?: string;
  source?: string;
  current_value?: number | string | null;
  notes?: string;
}

export interface ReportRecord {
  id: number;
  company_id: number;
  company_name: string;
  ticker: string;
  title: string;
  report_month: string;
  result: string;
  summary: string;
  next_action: string;
  review_date: string;
  stage_id: number;
  stage_key: string;
  stage_name: string;
  stage_sequence: number;
  template_id: number;
  template_name: string;
  template: TemplateRecord;
  responses: Record<string, string>;
  metrics: Record<string, string>;
  section_ratings: Record<string, number>;
  data_quality: Record<string, number>;
  field_sources: Record<string, FieldContextRecord>;
  field_notes: Record<string, string>;
  field_exceptions: Record<string, string>;
  watchlist_objective_rules: WatchlistObjectiveRule[];
  watchlist_subjective_rules: string;
  watchlist_conditions: string;
  archive_red_flags: string;
  documents: DocumentRecord[];
  sources: SourceRecord[];
  company_sources: SourceRecord[];
  suggested_sources: SourceRecord[];
  completion: CompletionRecord;
  workflow: WorkflowRecord;
  agent_contract: AgentContractRecord;
  revision: number;
  completed_at: string;
  created_at: string;
  updated_at: string;
  resource_uri: string;
  api_url: string;
  auto_inherited_fields: string[];
  section_modules?: ReportSectionSummaryRecord[];
  inherited_screening?: UpstreamReportReference | null;
  inherited_business_underwriting?: UpstreamReportReference | null;
  inherited_management_underwriting?: UpstreamReportReference | null;
  inherited_financial_underwriting?: UpstreamReportReference | null;
  inherited_valuation_position_size?: UpstreamReportReference | null;
}

export interface SectionEntryRecord {
  field_id: string;
  question: string;
  description: string;
  kind: string;
  options: string[];
  max: number | null;
  origin: string;
  path: string;
  ordinal: number;
  value: JsonValue;
  notes: {
    value?: string;
    required: boolean;
    category: string;
    placeholder: string;
  };
  sources: FieldContextRecord & {
    required: boolean;
  };
  exception_status: string;
  read_only: boolean;
  annotations_allowed: boolean;
}

export interface ReportSectionSummaryRecord {
  schema_version: number;
  report_id: number;
  report_revision: number;
  section_revision: number;
  stage_key: string;
  template_id: number;
  section_id: string;
  section_title: string;
  section_path: string;
  section_ordinal: number;
  description: string;
  entry_count: number;
  completion: CompletionRecord;
  resource_uri: string;
  api_url: string;
}

export interface ReportSectionRecord extends Omit<ReportSectionSummaryRecord, "entry_count"> {
  section_notes: string;
  section_sources: FieldContextRecord;
  entries: SectionEntryRecord[];
}

export interface CompanyRecord extends CompanySummaryRecord {
  reports: ReportSummaryRecord[];
  documents: DocumentRecord[];
  company_sources: SourceRecord[];
  monitoring_rules: MonitoringRuleRecord[];
}

export interface BootstrapPayload {
  dashboard: {
    buckets: Array<{ key: string; name: string; count: number }>;
    stages: Array<{ id: number; name: string; description: string; count: number; completed_reports: number }>;
    alerts: MonitoringRuleRecord[];
  };
  settings_summary: {
    reports_created_total?: number;
    sources_uploaded_total?: number;
    companies_outside_pool_total?: number;
  };
  report_actions?: string[];
}

export interface SessionPayload {
  required: boolean;
  authenticated: boolean;
  user?: {
    id: number | null;
    email: string;
    display_name: string;
  };
  expires_at?: string;
}

export interface CompaniesPayload {
  companies: CompanySummaryRecord[];
  total: number;
  page: number;
  per_page: number;
}

export interface ReportsPayload {
  reports: ReportSummaryRecord[];
  total: number;
  page: number;
  per_page: number;
}

export interface TemplatesPayload {
  templates: TemplateRecord[];
}

export interface MonitoringPayload {
  rules: MonitoringRuleRecord[];
}

export interface StagesPayload {
  stages: StageRecord[];
}

export interface CompanyPayload {
  company: CompanyRecord;
}

export interface ReportPayload {
  report: ReportRecord;
}

export interface ReportSectionsPayload {
  report_id: number;
  report_revision: number;
  sections: ReportSectionSummaryRecord[];
}

export interface ReportSectionPayload {
  section: ReportSectionRecord;
  report?: ReportRecord;
  completion?: CompletionRecord;
  report_completion?: CompletionRecord;
  preview?: JsonObject;
}

export interface TemplatePayload {
  template: TemplateRecord;
}

export interface MonitoringRulePayload {
  rule: MonitoringRuleRecord;
}

export interface DocumentsPayload {
  documents: DocumentRecord[];
}

export interface SourcePayload {
  source: SourceRecord;
}

export interface PreviewPayload {
  completion: CompletionRecord;
}

export interface SaveReportPayload {
  expected_revision: number;
  finalize: boolean;
  title: string;
  report_month: string;
  result: string;
  summary: string;
  watchlist_conditions: string;
  watchlist_subjective_rules: string;
  archive_red_flags: string;
  next_action: string;
  review_date: string;
  responses: Record<string, string>;
  metrics: Record<string, string>;
  section_ratings: Record<string, number>;
  data_quality: Record<string, number>;
  field_sources: Record<string, FieldContextRecord>;
  field_notes: Record<string, string>;
  field_exceptions: Record<string, string>;
  watchlist_objective_rules: WatchlistObjectiveRule[];
}
