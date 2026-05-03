"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { renderReportStageSurface } from "./report-stage-registry";
import {
  ApiError,
  createReportSource,
  deleteReport,
  deleteReportSource,
  getReport,
  previewReport,
  updateReport,
  updateReportSource,
  uploadDocuments,
} from "../lib/api";
import { companyHref, reportHref } from "../lib/routes";
import {
  documentStatusLabel,
  documentStatusTone,
  sourceDurabilityLabel,
  sourceDurabilityReason,
  sourceDurabilityStatus,
  sourceDurabilityTone,
  sourceStageContext,
} from "../lib/source-durability";
import type {
  CompletionFieldLink,
  CompletionRecord,
  DocumentRecord,
  FieldContextRecord,
  JsonObject,
  ReportRecord,
  SaveReportPayload,
  SourceRecord,
  TemplateField,
  TemplateSection,
  WatchlistObjectiveRule,
} from "../lib/types";

const FIELD_EXCEPTION_OPTIONS = [
  ["", "No exception"],
  ["unknown", "Unknown after investigation"],
  ["not_disclosed", "Not disclosed by source"],
  ["not_applicable", "Not applicable for this company"],
] as const;

const SOURCE_TYPES = [
  "Annual report",
  "Quarterly report",
  "Investor presentation",
  "Investor day",
  "Proxy / compensation filing",
  "Earnings call",
  "Competitor filing",
  "Industry source",
  "News / secondary source",
  "Dataset",
  "Other",
];

const EVIDENCE_GRADE_OPTIONS = ["", "F", "O", "M", "I", "V"];
const CONFIDENCE_OPTIONS = ["", "High", "Medium", "Low"];
const COMPARATOR_OPTIONS = ["<=", "<", ">=", ">", "="];
const DEFAULT_FINAL_DECISIONS = [
  ["Pass", "Proceed to Next Step"],
  ["Watchlist", "Watchlist"],
  ["Archive", "Archive"],
] as const;
const REPORT_SECTION_SUMMARY_LABELS = [
  "decision",
  "final decision",
  "fast kill result",
  "evidence result",
  "interaction read",
  "business category result",
  "business quality result",
  "business type result",
  "failure-mode result",
  "management category result",
  "capital allocation result",
  "culture read",
  "governance result",
  "financial snapshot result",
  "valuation read",
  "fragility read",
  "execution pattern result",
  "munger check result",
  "result",
];

type SourceEditorState = {
  id: string;
  document_id: string;
  title: string;
  source_type: string;
  evidence_grade: string;
  confidence: string;
  url: string;
  citation: string;
  tags: string;
  notes: string;
  link_only_reason: string;
  snapshot_guidance_acknowledged: boolean;
  file: File | null;
};

type PreviewState = {
  title: string;
  meta: string;
  preview: string;
  notes: string;
  normalizedAvailable: boolean;
  normalizedUrl?: string;
  downloadUrl?: string;
};

type FieldPopoverTab = "sources" | "notes";

type FieldPopoverState = {
  fieldId: string;
  label: string;
  activeTab: FieldPopoverTab;
  sourceIds: string[];
  citation: string;
  note: string;
  exception: string;
  noteLabel: string;
  notePlaceholder: string;
  noteHelp: string;
  allowNotes: boolean;
};

type PendingSourceDeleteState = {
  id: number;
  title: string;
};

type ReportFormState = {
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
  field_sources: Record<string, FieldContextRecord>;
  field_notes: Record<string, string>;
  field_exceptions: Record<string, string>;
  watchlist_objective_rules: WatchlistObjectiveRule[];
  section_ratings_json: string;
  data_quality_json: string;
};

function formatDate(value: string): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return date.toLocaleString();
}

function previewFromDocument(document: DocumentRecord): PreviewState {
  return {
    title: document.original_name,
    meta: [document.mime_type, document.normalized_status, document.normalized_format, document.normalized_method]
      .filter(Boolean)
      .join(" · "),
    preview: document.normalized_preview || "",
    notes: document.normalized_notes || document.notes || "",
    normalizedAvailable: document.normalized_available,
    normalizedUrl: document.normalized_url,
    downloadUrl: document.download_url,
  };
}

function previewFromSource(source: SourceRecord): PreviewState {
  return {
    title: source.title || source.document_name || `Source ${source.id}`,
    meta: [source.capture_state, source.normalized_format, source.normalized_method].filter(Boolean).join(" · "),
    preview: source.normalized_preview || "",
    notes: source.normalized_notes || source.notes || "",
    normalizedAvailable: source.normalized_available,
    normalizedUrl: source.document_normalized_url,
    downloadUrl: source.document_download_url,
  };
}

function blankSourceEditor(): SourceEditorState {
  return {
    id: "",
    document_id: "",
    title: "",
    source_type: SOURCE_TYPES[0],
    evidence_grade: "",
    confidence: "",
    url: "",
    citation: "",
    tags: "",
    notes: "",
    link_only_reason: "",
    snapshot_guidance_acknowledged: false,
    file: null,
  };
}

function sourceEditorFromRecord(source: SourceRecord): SourceEditorState {
  return {
    id: String(source.id),
    document_id: source.document_id == null ? "" : String(source.document_id),
    title: source.title || "",
    source_type: source.source_type || SOURCE_TYPES[0],
    evidence_grade: source.evidence_grade || "",
    confidence: source.confidence || "",
    url: source.url || "",
    citation: source.citation || "",
    tags: (source.tags || []).join(", "),
    notes: source.notes || "",
    link_only_reason: source.link_only_reason || "",
    snapshot_guidance_acknowledged: Boolean(source.snapshot_guidance_acknowledged),
    file: null,
  };
}

function formStateFromReport(report: ReportRecord): ReportFormState {
  return {
    title: report.title,
    report_month: report.report_month || "",
    result: report.result || "",
    summary: report.summary || "",
    watchlist_conditions: report.watchlist_conditions || "",
    watchlist_subjective_rules: report.watchlist_subjective_rules || "",
    archive_red_flags: report.archive_red_flags || "",
    next_action: report.next_action || "",
    review_date: report.review_date || "",
    responses: { ...(report.responses || {}) },
    metrics: { ...(report.metrics || {}) },
    field_sources: { ...(report.field_sources || {}) },
    field_notes: { ...(report.field_notes || {}) },
    field_exceptions: { ...(report.field_exceptions || {}) },
    watchlist_objective_rules: [...(report.watchlist_objective_rules || [])],
    section_ratings_json: JSON.stringify(report.section_ratings || {}, null, 2),
    data_quality_json: JSON.stringify(report.data_quality || {}, null, 2),
  };
}

function parseNumericRecord(value: string, label: string): Record<string, number> {
  if (!value.trim()) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object keyed by live ids.`);
  }
  const entries = Object.entries(parsed as JsonObject).map(([key, entry]) => [key, Number(entry)]);
  if (entries.some(([, entry]) => !Number.isFinite(entry))) {
    throw new Error(`${label} values must be numeric.`);
  }
  return Object.fromEntries(entries);
}

function sourceLibrary(report: ReportRecord): SourceRecord[] {
  const seen = new Set<number>();
  const combined = [...report.sources, ...report.suggested_sources, ...report.company_sources];
  return combined.filter((source) => {
    if (seen.has(source.id)) return false;
    seen.add(source.id);
    return true;
  });
}

function fieldInputValue(state: ReportFormState, field: TemplateField): string {
  if (field.kind === "metric") return state.metrics[field.id] ?? "";
  return state.responses[field.id] ?? "";
}

function sectionContext(state: ReportFormState, section: TemplateSection): FieldContextRecord {
  return state.field_sources[`section:${section.id}`] || { source_ids: [], citation: "" };
}

function pendingNormalizationCount(report: ReportRecord): number {
  const documents = report.documents.filter((document) => document.normalized_status === "pending").length;
  const sources = [...report.sources, ...report.company_sources, ...report.suggested_sources].filter(
    (source) => source.capture_state === "pending",
  ).length;
  return documents + sources;
}

function failedProcessingCount(report: ReportRecord): number {
  const documents = report.documents.filter((document) => document.normalized_status === "failed").length;
  const sources = [...report.sources, ...report.company_sources, ...report.suggested_sources].filter(
    (source) => sourceDurabilityStatus(source) === "failed",
  ).length;
  return documents + sources;
}

function omitReadonlyEntries<T>(entries: Record<string, T>, readonlyFieldIds: Set<string>): Record<string, T> {
  return Object.fromEntries(Object.entries(entries).filter(([fieldId]) => !readonlyFieldIds.has(fieldId)));
}

function sectionSummaryField(section: TemplateSection): TemplateField | null {
  for (const label of REPORT_SECTION_SUMMARY_LABELS) {
    const match = section.fields.find((field) => String(field.label || "").trim().toLowerCase() === label);
    if (match) return match;
  }
  const resultFields = section.fields.filter((field) => String(field.label || "").trim().toLowerCase().includes("result"));
  if (resultFields.length === 1) return resultFields[0];
  return null;
}

function isResultField(field: TemplateField): boolean {
  const normalized = String(field.label || "").trim().toLowerCase();
  return REPORT_SECTION_SUMMARY_LABELS.includes(normalized) || normalized.includes("result");
}

function fieldDisplayValue(state: ReportFormState, field: TemplateField): string {
  if (field.kind === "checkbox") return state.responses[field.id] === "true" ? "Yes" : "";
  return fieldInputValue(state, field);
}

function summaryTone(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return "neutral";
  if (
    normalized.includes("proceed")
    || normalized.includes("pass")
    || normalized.includes("advance")
    || normalized.includes("complete")
  ) {
    return "pass";
  }
  if (normalized.includes("watchlist") || normalized.includes("return to")) return "watchlist";
  if (normalized.includes("archive") || normalized.includes("fail")) return "archive";
  return "neutral";
}

function displayFieldLabel(label: string): string {
  return String(label || "")
    .replace(/\s+or\s+Redirect/gi, "")
    .replace(/Redirect\s+or\s+/gi, "")
    .trim();
}

function fieldNotesRequired(field: TemplateField | null | undefined): boolean {
  return Boolean(field?.notes_required);
}

function fieldNoteButtonLabel(field: TemplateField | null | undefined): string {
  return fieldNotesRequired(field) ? "Notes*" : "Notes";
}

function fieldNotePlaceholder(field: TemplateField | null | undefined): string {
  return field?.note_placeholder || "Optional: capture caveats, uncertainty, assumptions, or audit-trail context for this response.";
}

function fieldNoteRequirementHelp(field: TemplateField | null | undefined): string {
  if (fieldNotesRequired(field)) {
    return "Required for this field. Capture the basis, derivation, or decision logic behind the answer.";
  }
  return "Optional for narrative fields. Use notes for caveats, uncertainty, or audit trail when they add value.";
}

function fieldContextHasSourcesOrCitation(context: FieldContextRecord | undefined): boolean {
  return Boolean((context?.source_ids || []).length || String(context?.citation || "").trim());
}

function fieldSourceCountLabel(context: FieldContextRecord | undefined): string {
  const count = (context?.source_ids || []).length;
  return count ? `(${count})` : "";
}

function filteredOptions(options: string[]): string[] {
  return options.filter((option) => String(option || "").trim());
}

function finalDecisionField(report: ReportRecord): TemplateField | null {
  const section = report.template.schema.sections.find((item) => item.title === "Final Decision");
  return section?.fields.find((field) => field.label === "Decision") || null;
}

function normalizeFinalDecision(value: string): string {
  const text = String(value || "").toLowerCase();
  if (text.includes("return to business underwriting")) return "Return to Business Underwriting";
  if (text.includes("return to management underwriting")) return "Return to Management Underwriting";
  if (text.includes("return to financial underwriting")) return "Return to Financial Underwriting";
  if (text.includes("return to valuation and position size")) return "Return to Valuation and Position Size";
  if (text.includes("return to underwriting")) return "Return To Underwriting";
  if (text.includes("execute starter now")) return "Execute Starter Now";
  if (text.includes("enter staged orders")) return "Enter Staged Orders";
  if (text.includes("hold existing")) return "Hold Existing";
  if (text === "trim" || text.startsWith("trim ")) return "Trim";
  if (text === "exit" || text.startsWith("exit ")) return "Exit";
  if (text.includes("approve")) return "Approve For Execution";
  if (text.includes("pass") || text.includes("proceed")) return "Pass";
  if (text.includes("watchlist")) return "Watchlist";
  if (text.includes("archive")) return "Archive";
  return "";
}

function resultValueForDecisionOption(option: string): string {
  const decision = normalizeFinalDecision(option) || String(option || "");
  if (["Execute Starter Now", "Enter Staged Orders", "Hold Existing", "Trim", "Exit", "Approve For Execution", "Pass"].includes(decision)) {
    return "Proceed to Next Step";
  }
  if (decision === "Watchlist") return "Watchlist";
  if (decision === "Archive") return "Archive";
  if (decision === "Return to Business Underwriting") return "Return to Business Underwriting";
  if (decision === "Return to Management Underwriting") return "Return to Management Underwriting";
  if (decision === "Return to Financial Underwriting") return "Return to Financial Underwriting";
  if (decision === "Return to Valuation and Position Size") return "Return to Valuation and Position Size";
  return "";
}

export function NativeReportClient({ initialReport }: { initialReport: ReportRecord }) {
  const [report, setReport] = useState(initialReport);
  const [formState, setFormState] = useState(formStateFromReport(initialReport));
  const [savedSnapshot, setSavedSnapshot] = useState(() => JSON.stringify(formStateFromReport(initialReport)));
  const [previewCompletionState, setPreviewCompletionState] = useState<CompletionRecord | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [sourceEditor, setSourceEditor] = useState<SourceEditorState>(blankSourceEditor());
  const [sourceEditorOpen, setSourceEditorOpen] = useState(false);
  const [fieldPopover, setFieldPopover] = useState<FieldPopoverState | null>(null);
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({});
  const [pendingSourceDelete, setPendingSourceDelete] = useState<PendingSourceDeleteState | null>(null);

  const latestUpstreamReport = report.workflow.latest_upstream_report;
  const explicitReadonlyFieldIds = report.agent_contract.readonly_field_ids || [];
  const readonlyFieldIds = useMemo(
    () => new Set([...explicitReadonlyFieldIds, ...(report.auto_inherited_fields || [])]),
    [explicitReadonlyFieldIds, report.auto_inherited_fields],
  );
  const completion = previewCompletionState || report.completion;
  const allSources = useMemo(() => sourceLibrary(report), [report]);
  const currentSnapshot = useMemo(() => JSON.stringify(formState), [formState]);
  const hasUnsavedChanges = currentSnapshot !== savedSnapshot;
  const failedProcessing = useMemo(() => failedProcessingCount(report), [report]);
  const allSectionIds = useMemo(() => report.template.schema.sections.map((section) => section.id), [report.template.schema.sections]);
  const reportSources = useMemo(() => report.sources, [report.sources]);
  const suggestedSources = useMemo(() => report.suggested_sources, [report.suggested_sources]);
  const remainingCompanySources = useMemo(() => {
    const excluded = new Set<number>([...report.sources, ...report.suggested_sources].map((source) => source.id));
    return report.company_sources.filter((source) => !excluded.has(source.id));
  }, [report.company_sources, report.sources, report.suggested_sources]);
  const finalDecision = useMemo(() => finalDecisionField(report), [report]);

  function toggleSection(sectionId: string) {
    setOpenSections((current) => ({
      ...current,
      [sectionId]: !current[sectionId],
    }));
  }

  function setAllSections(open: boolean) {
    setOpenSections(Object.fromEntries(allSectionIds.map((sectionId) => [sectionId, open])));
  }

  function openSourceEditor(editor: SourceEditorState) {
    setSourceEditor(editor);
    setSourceEditorOpen(true);
  }

  function closeSourceEditor() {
    setSourceEditor(blankSourceEditor());
    setSourceEditorOpen(false);
  }

  function openFieldPopover(field: TemplateField | null | undefined, fieldId: string, label: string, activeTab: FieldPopoverTab) {
    const context = formState.field_sources[fieldId] || { source_ids: [], citation: "" };
    setFieldPopover({
      fieldId,
      label,
      activeTab,
      sourceIds: context.source_ids.map(String),
      citation: context.citation || "",
      note: formState.field_notes[fieldId] || "",
      exception: formState.field_exceptions[fieldId] || "",
      noteLabel: fieldNoteButtonLabel(field),
      notePlaceholder: fieldNotePlaceholder(field),
      noteHelp: fieldNoteRequirementHelp(field),
      allowNotes: Boolean(field),
    });
  }

  function closeFieldPopover() {
    setFieldPopover(null);
  }

  async function refreshReport(showStatus = false, preserveForm = false) {
    const result = await getReport(report.id);
    setReport(result.report);
    if (!preserveForm) {
      const nextState = formStateFromReport(result.report);
      setFormState(nextState);
      setSavedSnapshot(JSON.stringify(nextState));
      closeSourceEditor();
      closeFieldPopover();
      setPendingSourceDelete(null);
      setPreviewCompletionState(null);
    }
    if (showStatus) setStatus(`Refreshed ${result.report.title}.`);
  }

  useEffect(() => {
    if (!pendingNormalizationCount(report)) return undefined;
    const timer = window.setInterval(() => {
      void refreshReport(false, true);
    }, 8000);
    return () => window.clearInterval(timer);
  }, [report]);

  useEffect(() => {
    if (!hasUnsavedChanges) return undefined;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [hasUnsavedChanges]);

  function updateField(field: TemplateField, value: string | boolean) {
    setFormState((current) => {
      if (field.kind === "checkbox") {
        return {
          ...current,
          responses: {
            ...current.responses,
            [field.id]: value ? "true" : "",
          },
        };
      }
      if (field.kind === "metric") {
        return {
          ...current,
          metrics: {
            ...current.metrics,
            [field.id]: String(value),
          },
        };
      }
      const next = {
        ...current,
        responses: {
          ...current.responses,
          [field.id]: String(value),
        },
      };
      if (finalDecision?.id === field.id) {
        next.result = resultValueForDecisionOption(String(value)) || "Draft";
      }
      return next;
    });
    setPreviewCompletionState(null);
  }

  function updateFieldContext(fieldId: string, next: FieldContextRecord) {
    setFormState((current) => ({
      ...current,
      field_sources: {
        ...current.field_sources,
        [fieldId]: next,
      },
    }));
    setPreviewCompletionState(null);
  }

  function updateFieldNote(fieldId: string, note: string) {
    setFormState((current) => {
      const nextNotes = { ...current.field_notes };
      if (note.trim()) nextNotes[fieldId] = note;
      else delete nextNotes[fieldId];
      return {
        ...current,
        field_notes: nextNotes,
      };
    });
    setPreviewCompletionState(null);
  }

  function updateFieldException(fieldId: string, value: string) {
    setFormState((current) => {
      const nextExceptions = { ...current.field_exceptions };
      if (value.trim()) nextExceptions[fieldId] = value;
      else delete nextExceptions[fieldId];
      return {
        ...current,
        field_exceptions: nextExceptions,
      };
    });
    setPreviewCompletionState(null);
  }

  function saveFieldPopover() {
    if (!fieldPopover) return;
    const nextContext = {
      source_ids: fieldPopover.sourceIds.map(Number),
      citation: fieldPopover.citation,
    };
    updateFieldContext(fieldPopover.fieldId, nextContext);
    if (fieldPopover.allowNotes) {
      updateFieldNote(fieldPopover.fieldId, fieldPopover.note);
      updateFieldException(fieldPopover.fieldId, fieldPopover.exception);
    }
    closeFieldPopover();
  }

  function applySectionSourcesToFields(section: TemplateSection) {
    const sectionKey = `section:${section.id}`;
    const context = formState.field_sources[sectionKey] || { source_ids: [], citation: "" };
    const editableFieldIds = section.fields.filter((field) => !readonlyFieldIds.has(field.id)).map((field) => field.id);
    if (!editableFieldIds.length) {
      setStatus("This section only contains inherited read-only fields.");
      return;
    }
    setFormState((current) => ({
      ...current,
      field_sources: {
        ...current.field_sources,
        ...Object.fromEntries(
          editableFieldIds.map((fieldId) => [
            fieldId,
            {
              source_ids: [...context.source_ids],
              citation: context.citation,
            },
          ]),
        ),
      },
    }));
    setPreviewCompletionState(null);
    setStatus(`Applied section sources to ${editableFieldIds.length} editable answers.`);
  }

  function buildPayload(finalize: boolean): SaveReportPayload {
    return {
      expected_revision: report.revision,
      finalize,
      title: formState.title,
      report_month: formState.report_month,
      result: formState.result,
      summary: formState.summary,
      watchlist_conditions: formState.watchlist_conditions,
      watchlist_subjective_rules: formState.watchlist_subjective_rules,
      archive_red_flags: formState.archive_red_flags,
      next_action: formState.next_action,
      review_date: formState.review_date,
      responses: omitReadonlyEntries(formState.responses, readonlyFieldIds),
      metrics: omitReadonlyEntries(formState.metrics, readonlyFieldIds),
      section_ratings: parseNumericRecord(formState.section_ratings_json, "Section ratings"),
      data_quality: parseNumericRecord(formState.data_quality_json, "Data quality"),
      field_sources: formState.field_sources,
      field_notes: formState.field_notes,
      field_exceptions: omitReadonlyEntries(formState.field_exceptions, readonlyFieldIds),
      watchlist_objective_rules: formState.watchlist_objective_rules.filter((rule) => String(rule.metric_name || "").trim()),
    };
  }

  async function runPreview() {
    setBusy("preview");
    setStatus("");
    setError("");
    try {
      const result = await previewReport(report.id, buildPayload(false));
      setPreviewCompletionState(result.completion);
      setStatus("Completion preview refreshed.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to preview completion.");
    } finally {
      setBusy("");
    }
  }

  async function persistReport(finalize: boolean) {
    if (finalize && (!formState.result || formState.result === "Draft")) {
      setError("Choose a final decision before finalizing.");
      setStatus("");
      return;
    }
    setBusy(finalize ? "finalize" : "save");
    setStatus("");
    setError("");
    try {
      const result = await updateReport(report.id, buildPayload(finalize));
      setReport(result.report);
      const nextState = formStateFromReport(result.report);
      setFormState(nextState);
      setSavedSnapshot(JSON.stringify(nextState));
      setPreviewCompletionState(null);
      setStatus(finalize ? "Report finalized and workflow position updated." : "Draft saved.");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        const reload = window.confirm(
          `This report changed elsewhere after you opened it.${typeof caught.payload === "object" && caught.payload && "updated_at" in caught.payload && typeof caught.payload.updated_at === "string" ? ` Latest save: ${formatDate(caught.payload.updated_at)}.` : ""}\n\nPress OK to reload the latest version and discard unsaved edits, or Cancel to keep the current form open.`,
        );
        if (reload) {
          await refreshReport(true, false);
          return;
        }
      }
      if (caught instanceof ApiError && caught.status === 422) {
        setError(caught.message);
        const payload = caught.payload as { completion?: CompletionRecord } | null;
        if (payload?.completion) setPreviewCompletionState(payload.completion);
      } else {
        setError(caught instanceof ApiError ? caught.message : "Failed to save report.");
      }
    } finally {
      setBusy("");
    }
  }

  async function removeReport() {
    if (!window.confirm(`Delete ${report.title}? This removes it from the company timeline and discards this report revision chain.`)) return;
    setBusy("delete-report");
    setStatus("");
    setError("");
    try {
      const result = await deleteReport(report.id);
      window.location.href = companyHref(result.company);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to delete report.");
    } finally {
      setBusy("");
    }
  }

  async function persistSource() {
    const urlOnly = sourceEditor.url.trim() && !sourceEditor.file && !sourceEditor.document_id;
    if (urlOnly && !sourceEditor.snapshot_guidance_acknowledged) {
      setError("Read the snapshot guidance and acknowledge it before saving a URL-only source.");
      return;
    }
    if (urlOnly && !sourceEditor.link_only_reason.trim()) {
      setError("Explain why this source is still link-only before saving it.");
      return;
    }
    setBusy("source-save");
    setStatus("");
    setError("");
    const formData = new FormData();
    formData.append("report_id", String(report.id));
    formData.append("id", sourceEditor.id);
    formData.append("document_id", sourceEditor.document_id);
    formData.append("title", sourceEditor.title);
    formData.append("source_type", sourceEditor.source_type);
    formData.append("evidence_grade", sourceEditor.evidence_grade);
    formData.append("confidence", sourceEditor.confidence);
    formData.append("url", sourceEditor.url);
    formData.append("citation", sourceEditor.citation);
    formData.append("tags", sourceEditor.tags);
    formData.append("notes", sourceEditor.notes);
    formData.append("link_only_reason", sourceEditor.link_only_reason);
    formData.append("snapshot_guidance_acknowledged", sourceEditor.snapshot_guidance_acknowledged ? "true" : "false");
    if (sourceEditor.file) formData.append("file", sourceEditor.file);
    try {
      if (sourceEditor.id) {
        await updateReportSource(Number(sourceEditor.id), formData);
      } else {
        await createReportSource(formData);
      }
      await refreshReport(false, true);
      closeSourceEditor();
      setStatus(sourceEditor.id ? "Source updated." : "Source created.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to save source.");
    } finally {
      setBusy("");
    }
  }

  async function removeSource(sourceId: number) {
    setBusy(`source-delete-${sourceId}`);
    setStatus("");
    setError("");
    try {
      await deleteReportSource(sourceId);
      await refreshReport(false, true);
      setPendingSourceDelete(null);
      setStatus("Source deleted.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to delete source.");
    } finally {
      setBusy("");
    }
  }

  async function uploadDocument(formData: FormData) {
    setBusy("document-upload");
    setStatus("");
    setError("");
    try {
      await uploadDocuments(formData);
      await refreshReport(false, true);
      setStatus("Document uploaded.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to upload document.");
    } finally {
      setBusy("");
    }
  }

  function completionStatusTone(statusValue: string): string {
    if (statusValue === "complete") return "green";
    if (statusValue === "ready_to_finalize") return "cyan";
    return "amber";
  }

  function renderCompletionList(items: CompletionFieldLink[], prefix = ""): ReactNode {
    if (!items.length) return null;
    return (
      <ul className="compact-list">
        {items.map((field, index) => (
          <li key={`${field.section_title}-${field.label}-${prefix}-${index}`}>
            {prefix}
            {field.section_title}: {field.label}
          </li>
        ))}
      </ul>
    );
  }

  function sourceVisualizationNode(sources: SourceRecord[]): ReactNode {
    if (!sources.length) return <span className="pill">0 sources</span>;
    const counts = sources.reduce<Record<string, number>>((acc, source) => {
      const grade = source.evidence_grade || "U";
      acc[grade] = (acc[grade] || 0) + 1;
      return acc;
    }, {});
    return (
      <div className="source-viz">
        {Object.entries(counts).map(([grade, count]) => (
          <span className={`source-grade grade-${grade}`} key={grade} title={grade}>
            {grade} {count}
          </span>
        ))}
      </div>
    );
  }

  function renderSourceTableSection(title: string, description: string, sources: SourceRecord[], editable = false, emptyMessage = "No sources imported yet.") {
    return (
      <div className="source-group">
        <div className="panel-header">
          <div>
            <h3>{title}</h3>
            <p className="muted">{description}</p>
          </div>
          <span className="pill">{sources.length}</span>
        </div>
        {!sources.length ? (
          <div className="empty-state">{emptyMessage}</div>
        ) : (
          <div className="table-wrap">
            <table className="source-table decision-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Type</th>
                  <th>Evidence</th>
                  <th>Reuse</th>
                  <th>Tags</th>
                  <th>Citation</th>
                  <th>Open</th>
                  {editable ? <th /> : null}
                </tr>
              </thead>
              <tbody>
                {sources.map((source) => {
                  const status = sourceDurabilityStatus(source);
                  return (
                    <tr key={`${title}-${source.id}`}>
                      <td>
                        <strong>{source.title}</strong>
                        {source.notes ? (
                          <>
                            <br />
                            <span className="muted">{source.notes}</span>
                          </>
                        ) : null}
                      </td>
                      <td>
                        {source.source_type || ""}
                        <br />
                        <span className="muted">{source.confidence || "No confidence"}</span>
                        {sourceStageContext(source) ? (
                          <>
                            <br />
                            <span className="muted">{sourceStageContext(source)}</span>
                          </>
                        ) : null}
                      </td>
                      <td>
                        <span className={`source-grade grade-${source.evidence_grade || "U"}`}>{source.evidence_grade || "U"}</span>
                      </td>
                      <td>
                        <span className={`pill ${sourceDurabilityTone(status)}`}>{sourceDurabilityLabel(status)}</span>
                        <div className="muted">{sourceDurabilityReason(source)}</div>
                        {(source.normalized_preview || source.notes) ? (
                          <div className="button-row">
                            <button type="button" className="small-button" onClick={() => setPreview(previewFromSource(source))}>
                              Preview
                            </button>
                          </div>
                        ) : null}
                      </td>
                      <td>
                        <div className="tag-row">
                          {(source.tags || []).map((tag) => (
                            <span className="pill" key={`${source.id}-${tag}`}>
                              {tag}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td>{source.citation || ""}</td>
                      <td>
                        <div className="button-row">
                          {source.url ? (
                            <a className="small-button" href={source.url} target="_blank" rel="noreferrer">
                              Open URL
                            </a>
                          ) : null}
                          {source.document_download_url ? (
                            <a className="small-button" href={source.document_download_url}>
                              Download
                            </a>
                          ) : null}
                          {source.normalized_available && source.document_normalized_url ? (
                            <a className="small-button" href={source.document_normalized_url} target="_blank" rel="noreferrer">
                              Open LLM View
                            </a>
                          ) : null}
                        </div>
                      </td>
                      {editable ? (
                        <td>
                          <div className="button-row">
                            <button type="button" className="small-button" onClick={() => openSourceEditor(sourceEditorFromRecord(source))}>
                              Edit
                            </button>
                            <button
                              type="button"
                              className="small-button danger"
                              disabled={busy === `source-delete-${source.id}`}
                              onClick={() => setPendingSourceDelete({ id: source.id, title: source.title })}
                            >
                              {busy === `source-delete-${source.id}` ? "Deleting..." : "Delete"}
                            </button>
                          </div>
                        </td>
                      ) : null}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  function renderTemplateSection(section: TemplateSection): ReactNode {
    const summaryField = sectionSummaryField(section);
    const summaryValue = summaryField ? fieldDisplayValue(formState, summaryField) : "";
    const sectionKey = `section:${section.id}`;
    const sourceContext = sectionContext(formState, section);
    const sectionNote = formState.field_notes[sectionKey] || "";
    const sectionOpen = Boolean(openSections[section.id]);
    const displayFields = section.fields.filter((field) => !isResultField(field));
    const resultFields = section.fields.filter((field) => isResultField(field));

    function renderFieldControl(field: TemplateField, readonly: boolean, value: string) {
      if (field.kind === "textarea") {
        return (
          <textarea
            className="soft-textarea"
            rows={1}
            value={value}
            disabled={readonly}
            onChange={(event) => updateField(field, event.target.value)}
          />
        );
      }
      if (field.kind === "select") {
        return (
          <select
            className="soft-input"
            value={value}
            disabled={readonly}
            onChange={(event) => updateField(field, event.target.value)}
          >
            <option value="">Select</option>
            {filteredOptions(field.options).map((option) => (
              <option value={option} key={option}>
                {option}
              </option>
            ))}
          </select>
        );
      }
      if (field.kind === "checkbox") {
        return (
          <label className="checkbox-line">
            <input
              type="checkbox"
              checked={value === "true"}
              disabled={readonly}
              onChange={(event) => updateField(field, event.target.checked)}
            />
            <span>Checked</span>
          </label>
        );
      }
      return (
        <input
          className="soft-input"
          type={field.kind === "date" ? "date" : field.kind === "metric" ? "number" : "text"}
          step={field.kind === "metric" ? "any" : undefined}
          value={value}
          disabled={readonly}
          onChange={(event) => updateField(field, event.target.value)}
        />
      );
    }

    return (
      <details className="panel inset-panel report-section-toggle" key={section.id} open={sectionOpen}>
        <summary
          className="report-section-summary"
          onClick={(event) => {
            event.preventDefault();
            toggleSection(section.id);
          }}
        >
          <span className="report-toggle-summary-main">
            <span className="report-toggle-caret" aria-hidden="true" />
            <span className="report-section-summary-title">{section.title}</span>
          </span>
          <span className="report-section-summary-preview">
            {summaryField ? (
              <>
                <span className="report-section-summary-label">{displayFieldLabel(summaryField.label)}</span>
                {summaryValue ? (
                  summaryField.kind === "select" ? (
                    <span className={`section-summary-pill tone-${summaryTone(summaryValue)}`}>{summaryValue}</span>
                  ) : (
                    <span className="report-section-summary-text">{summaryValue}</span>
                  )
                ) : (
                  <span className="muted">Not answered</span>
                )}
              </>
            ) : (
              <span className="muted">{section.fields.length} fields</span>
            )}
          </span>
        </summary>
        <div className="report-section-body stack-gap">
          <div className="section-heading">
            <div>
              <div className="section-actions">
                <button
                  type="button"
                  className={`inline-tool ${fieldContextHasSourcesOrCitation(sourceContext) ? "has-note" : ""}`}
                  onClick={() => openFieldPopover(null, sectionKey, `${section.title} section sources`, "sources")}
                >
                  Section Sources {fieldSourceCountLabel(sourceContext)}
                </button>
                <button type="button" className="inline-tool" onClick={() => applySectionSourcesToFields(section)}>
                  Apply to all answers
                </button>
                {section.body_markdown ? (
                  <details className="section-guidance">
                    <summary>Guidance</summary>
                    <div className="prewrap-text muted">{section.body_markdown}</div>
                  </details>
                ) : null}
              </div>
            </div>
            <details className="section-notes">
              <summary className={sectionNote.trim() ? "has-note" : undefined}>Notes</summary>
              <textarea
                className="soft-textarea"
                rows={1}
                value={sectionNote}
                onChange={(event) => updateFieldNote(sectionKey, event.target.value)}
              />
            </details>
          </div>

          {displayFields.length ? (
            <div className="table-wrap">
              <table className="decision-table data-point-table">
                <thead>
                  <tr>
                    <th>Question</th>
                    <th>Response</th>
                  </tr>
                </thead>
                <tbody>
                  {displayFields.map((field, fieldIndex) => {
                    const value = fieldInputValue(formState, field);
                    const context = formState.field_sources[field.id] || { source_ids: [], citation: "" };
                    const note = formState.field_notes[field.id] || "";
                    const exception = formState.field_exceptions[field.id] || "";
                    const readonly = readonlyFieldIds.has(field.id);

                    return (
                      <Fragment key={`${section.id}:${field.path || field.id}:${fieldIndex}`}>
                        <tr className={readonly ? "inherited-field" : ""}>
                          <td>
                            <div className="question-line">
                              <div className="stack-tight">
                                <strong>{displayFieldLabel(field.label)}</strong>
                                {field.help ? <span className="muted">{field.help}</span> : null}
                              </div>
                              <div className="field-tools">
                                <button
                                  type="button"
                                  className={`inline-tool ${fieldContextHasSourcesOrCitation(context) ? "has-note" : ""}`}
                                  onClick={() => openFieldPopover(field, field.id, displayFieldLabel(field.label), "sources")}
                                >
                                  Sources {fieldSourceCountLabel(context)}
                                </button>
                                <button
                                  type="button"
                                  className={`inline-tool ${note.trim() || exception ? "has-note" : ""}`}
                                  onClick={() => openFieldPopover(field, field.id, displayFieldLabel(field.label), "notes")}
                                >
                                  {fieldNoteButtonLabel(field)}
                                </button>
                              </div>
                            </div>
                            <div className="rule-stack">
                              {readonly ? <span className="pill amber">Inherited Read-Only Value</span> : null}
                              {field.notes_required ? <span className="pill">Note Required</span> : null}
                            </div>
                          </td>
                          <td>{renderFieldControl(field, readonly, value)}</td>
                        </tr>
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}

          {resultFields.length ? (
            <div className="stack-gap">
              {resultFields.map((field, fieldIndex) => {
                const value = fieldInputValue(formState, field);
                const context = formState.field_sources[field.id] || { source_ids: [], citation: "" };
                const note = formState.field_notes[field.id] || "";
                const exception = formState.field_exceptions[field.id] || "";
                const readonly = readonlyFieldIds.has(field.id);
                const options = filteredOptions(field.options?.length ? field.options : DEFAULT_FINAL_DECISIONS.map(([label]) => label));

                return (
                  <div className="bold-result" key={`${section.id}:result:${field.path || field.id}:${fieldIndex}`}>
                    <div className="question-line">
                      <div className="stack-tight">
                        <strong>{displayFieldLabel(field.label)}</strong>
                        {field.help ? <span className="muted">{field.help}</span> : null}
                      </div>
                      <div className="field-tools">
                        <button
                          type="button"
                          className={`inline-tool ${fieldContextHasSourcesOrCitation(context) ? "has-note" : ""}`}
                          onClick={() => openFieldPopover(field, field.id, displayFieldLabel(field.label), "sources")}
                        >
                          Sources {fieldSourceCountLabel(context)}
                        </button>
                        <button
                          type="button"
                          className={`inline-tool ${note.trim() || exception ? "has-note" : ""}`}
                          onClick={() => openFieldPopover(field, field.id, displayFieldLabel(field.label), "notes")}
                        >
                          {fieldNoteButtonLabel(field)}
                        </button>
                      </div>
                    </div>
                    {field.kind === "select" ? (
                      <div className="result-spectrum" data-spectrum-options={options.length}>
                        {options.map((option, optionIndex) => (
                          <label key={`${field.id}-${option}`}>
                            <input
                              type="radio"
                              name={field.id}
                              checked={value === option}
                              disabled={readonly}
                              onChange={() => updateField(field, option)}
                            />
                            <span className={`spectrum-${optionIndex + 1} tone-${summaryTone(option)}`}>{option}</span>
                          </label>
                        ))}
                      </div>
                    ) : (
                      <textarea
                        className="soft-textarea"
                        rows={1}
                        value={value}
                        disabled={readonly}
                        onChange={(event) => updateField(field, event.target.value)}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          ) : null}

          {!displayFields.length && !resultFields.length ? (
            <div className="empty-state">This section currently carries context and instructions but no direct fields.</div>
          ) : null}
        </div>
      </details>
    );
  }

  return (
    <>
      {hasUnsavedChanges ? (
        <section className="panel save-state-banner">
          Unsaved edits are present. Leaving or reloading this page now will discard changes since the last saved or refreshed
          report state.
        </section>
      ) : null}

      {status ? <section className="panel status-banner">{status}</section> : null}
      {error ? <section className="panel error-banner">{error}</section> : null}
      {failedProcessing ? (
        <section className="panel warning-box">
          <strong>{failedProcessing}</strong> document or source items are currently in a failed durability/normalization state.
          Check the failed cards below before relying on them in cited answers or finalization.
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-header detail-head">
          <div>
            <button type="button" className="secondary" onClick={() => (window.location.href = companyHref({ id: report.company_id, ticker: report.ticker, name: report.company_name }))}>
              Back to Company
            </button>
            <p className="eyebrow">{report.stage_name}</p>
            <h3 className="company-title">{report.title}</h3>
            <p className="muted">Sources, field notes, exceptions, and citations are saved with this report.</p>
          </div>
          <div className="button-row">
            <button type="button" className="small-button danger" disabled={busy === "delete-report"} onClick={() => void removeReport()}>
              {busy === "delete-report" ? "Deleting..." : "Delete Report"}
            </button>
            <button type="button" className="small-button" disabled={busy === "save"} onClick={() => void persistReport(false)}>
              {busy === "save" ? "Saving..." : "Save Draft"}
            </button>
            <button type="button" className="small-button" disabled={busy === "finalize"} onClick={() => void persistReport(true)}>
              {busy === "finalize" ? "Finalizing..." : "Finalize Report"}
            </button>
          </div>
        </div>

        <div className="panel-body form-grid compact-form three-column">
          <label className="field-block">
            <span className="field-label">Title</span>
            <input
              className="soft-input"
              value={formState.title}
              onChange={(event) => setFormState((current) => ({ ...current, title: event.target.value }))}
            />
          </label>
          <label className="field-block">
            <span className="field-label">Report Month</span>
            <input
              className="soft-input"
              value={formState.report_month}
              onChange={(event) => setFormState((current) => ({ ...current, report_month: event.target.value }))}
            />
          </label>
        </div>
      </section>

      {completion && Object.keys(completion).length ? (
        <section className="panel">
          <div className="panel-header">
            <div>
              <h3>Completion Quality</h3>
              <p className="muted">
                The full template always stays visible. Finalize only persists the non-draft result after every non-exempt field is
                covered, sourced, and note-complete where required.
                {previewCompletionState ? " Showing an unsaved preview of the current form state." : " Showing the last saved report state until you refresh the preview."}
              </p>
            </div>
            <div className="button-row">
              {previewCompletionState ? <span className="pill cyan">Unsaved preview</span> : null}
              <span className={`pill ${completionStatusTone(completion.status)}`}>{completion.status || "unknown"}</span>
              <button type="button" className="secondary" disabled={busy === "preview"} onClick={() => void runPreview()}>
                {busy === "preview" ? "Refreshing..." : "Refresh Completion Preview"}
              </button>
            </div>
          </div>
          <div className="panel-body grid report-quality-panel">
            <div className="rule-stack">
              <span className="pill cyan">Covered {completion.covered_field_count || 0}/{completion.field_count || 0}</span>
              <span className="pill green">Sourced {completion.sourced_field_count || 0}/{completion.source_required_field_count || 0}</span>
              <span className={`pill ${(completion.missing_required_note_ids || []).length ? "amber" : ""}`}>
                Required Notes {completion.required_noted_field_count || 0}/{completion.required_note_field_count || 0}
              </span>
              <span className="pill">Exempt {completion.exempt_field_count || 0}</span>
              <span className="pill">Template {completion.template_field_count || completion.field_count || 0}</span>
              <span className="pill">Coverage {Math.round(Number(completion.coverage_pct || 0))}%</span>
              <span className="pill">Source Coverage {Math.round(Number(completion.source_coverage_pct || 0))}%</span>
              <span className="pill">Notes Coverage {Math.round(Number(completion.notes_coverage_pct || 0))}%</span>
              {completion.final_decision ? <span className="pill">{completion.final_decision}</span> : <span className="pill amber">No final decision</span>}
            </div>
            {(completion.missing_fields?.length || completion.missing_source_links?.length || completion.blocked_source_links?.length || completion.missing_required_notes?.length || completion.exception_missing_notes?.length || completion.decision_requirements?.length) ? (
              <div className="source-guidance-box warning-box">
                <strong>Blocking Gaps</strong>
                {renderCompletionList(completion.missing_fields)}
                {renderCompletionList(completion.missing_source_links, "Missing source: ")}
                {renderCompletionList(completion.blocked_source_links, "Blocked source: ")}
                {renderCompletionList(completion.missing_required_notes, "Missing required note: ")}
                {renderCompletionList(completion.exception_missing_notes || [], "Exception needs note: ")}
                {completion.decision_requirements?.length ? (
                  <ul className="compact-list">
                    {completion.decision_requirements.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}
            {completion.warnings?.length ? (
              <div className="source-guidance-box warning-box">
                <strong>Warnings</strong>
                <div className="muted">{completion.warnings.join("\n")}</div>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      <details className="panel report-collapsible-panel sources-panel">
        <summary className="panel-header report-collapsible-summary">
          <div className="report-collapsible-summary-main">
            <span className="report-toggle-caret" aria-hidden="true" />
            <div>
              <h3>Source Library</h3>
              <p className="muted">Reuse suggested company sources first. Create a new source only when the evidence is not already in the company library.</p>
            </div>
          </div>
          {sourceVisualizationNode(allSources)}
        </summary>
        <div className="panel-body grid">
          <div className="button-row">
            <button type="button" className="primary" onClick={() => openSourceEditor(blankSourceEditor())}>
              Add Source
            </button>
          </div>
          {renderSourceTableSection("This Report’s Sources", "Edit or delete only the sources created in this report.", reportSources, true, "No sources created in this report yet.")}
          {renderSourceTableSection("Suggested Company Sources", "Cited upstream sources and latest-stage evidence are ranked here for reuse first.", suggestedSources, false, "No suggested upstream sources yet.")}
          {renderSourceTableSection("All Company Sources", "Remaining company-library sources are still available for citation without creating duplicates.", remainingCompanySources, false, "No additional company sources in the library.")}
        </div>
      </details>

      <section className="panel">
        <div className="panel-body">
          <div className="report-section-toolbar">
            <div className="button-row">
              <button type="button" className="secondary" onClick={() => setAllSections(false)}>
                Collapse All
              </button>
              <button type="button" className="secondary" onClick={() => setAllSections(true)}>
                Expand All
              </button>
            </div>
          </div>
          <div className="stack-gap">
            {renderReportStageSurface({
              report,
              renderSection: renderTemplateSection,
            })}
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h3>Decision Summary</h3>
            <p className="muted">This controls dashboard position, watchlist summary, archive summary, and monitoring rules.</p>
          </div>
        </div>
        <div className="panel-body grid">
          <label className="field-block">
            <span className="field-label">Summary</span>
            <textarea
              className="soft-textarea"
              rows={4}
              value={formState.summary}
              onChange={(event) => setFormState((current) => ({ ...current, summary: event.target.value }))}
            />
          </label>
          <label className="field-block">
            <span className="field-label">Watchlist Conditions</span>
            <textarea
              className="soft-textarea"
              rows={4}
              value={formState.watchlist_conditions}
              onChange={(event) => setFormState((current) => ({ ...current, watchlist_conditions: event.target.value }))}
            />
          </label>
          <label className="field-block">
            <span className="field-label">Watchlist Subjective Rules</span>
            <textarea
              className="soft-textarea"
              rows={4}
              value={formState.watchlist_subjective_rules}
              onChange={(event) => setFormState((current) => ({ ...current, watchlist_subjective_rules: event.target.value }))}
            />
          </label>
          <label className="field-block">
            <span className="field-label">Archive Red Flags</span>
            <textarea
              className="soft-textarea"
              rows={4}
              value={formState.archive_red_flags}
              onChange={(event) => setFormState((current) => ({ ...current, archive_red_flags: event.target.value }))}
            />
          </label>
          <div className="form-grid two-column">
            <label className="field-block">
              <span className="field-label">Next Action</span>
              <input
                className="soft-input"
                value={formState.next_action}
                onChange={(event) => setFormState((current) => ({ ...current, next_action: event.target.value }))}
              />
            </label>
            <label className="field-block">
              <span className="field-label">Review Date</span>
              <input
                className="soft-input"
                value={formState.review_date}
                onChange={(event) => setFormState((current) => ({ ...current, review_date: event.target.value }))}
              />
            </label>
          </div>
            <div className="grid" id="objective-rules">
              <div className="panel-header">
                <div>
                  <h3>Objective Monitoring Rules</h3>
                  <p className="muted">Define the rule here. Update current values and runtime notes from Monitoring.</p>
                </div>
                <button
                  type="button"
                  className="secondary"
                  onClick={() =>
                    setFormState((current) => ({
                      ...current,
                      watchlist_objective_rules: [
                        ...current.watchlist_objective_rules,
                        { rule_key: `rule-${Date.now()}`, metric_name: "", comparator: "<=", threshold_value: "", source: "", unit: "", notes: "" },
                      ],
                    }))
                  }
                >
                  Add Rule
                </button>
              </div>
              <div className="stack-gap" id="objective-rule-list">
                {formState.watchlist_objective_rules.map((rule, index) => (
                  <article className="row-card compact-row-card objective-rule-card" key={rule.rule_key || `${index}`}>
                    <div className="form-grid two-column">
                      <label className="field-block">
                        <span className="field-label">Metric</span>
                        <input
                          className="soft-input"
                          value={String(rule.metric_name || "")}
                          onChange={(event) =>
                            setFormState((current) => ({
                              ...current,
                              watchlist_objective_rules: current.watchlist_objective_rules.map((entry, entryIndex) =>
                                entryIndex === index ? { ...entry, metric_name: event.target.value } : entry,
                              ),
                            }))
                          }
                        />
                      </label>
                      <label className="field-block">
                        <span className="field-label">Comparator</span>
                        <select
                          className="soft-input"
                          value={String(rule.comparator || "<=")}
                          onChange={(event) =>
                            setFormState((current) => ({
                              ...current,
                              watchlist_objective_rules: current.watchlist_objective_rules.map((entry, entryIndex) =>
                                entryIndex === index ? { ...entry, comparator: event.target.value } : entry,
                              ),
                            }))
                          }
                        >
                          {COMPARATOR_OPTIONS.map((option) => (
                            <option value={option} key={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="field-block">
                        <span className="field-label">Threshold</span>
                        <input
                          className="soft-input"
                          value={String(rule.threshold_value ?? "")}
                          onChange={(event) =>
                            setFormState((current) => ({
                              ...current,
                              watchlist_objective_rules: current.watchlist_objective_rules.map((entry, entryIndex) =>
                                entryIndex === index ? { ...entry, threshold_value: event.target.value } : entry,
                              ),
                            }))
                          }
                        />
                      </label>
                      <label className="field-block">
                        <span className="field-label">Unit</span>
                        <input
                          className="soft-input"
                          value={String(rule.unit || "")}
                          onChange={(event) =>
                            setFormState((current) => ({
                              ...current,
                              watchlist_objective_rules: current.watchlist_objective_rules.map((entry, entryIndex) =>
                                entryIndex === index ? { ...entry, unit: event.target.value } : entry,
                              ),
                            }))
                          }
                        />
                      </label>
                      <label className="field-block">
                        <span className="field-label">Source</span>
                        <input
                          className="soft-input"
                          value={String(rule.source || "")}
                          onChange={(event) =>
                            setFormState((current) => ({
                              ...current,
                              watchlist_objective_rules: current.watchlist_objective_rules.map((entry, entryIndex) =>
                                entryIndex === index ? { ...entry, source: event.target.value } : entry,
                              ),
                            }))
                          }
                        />
                      </label>
                      <label className="field-block">
                        <span className="field-label">Notes</span>
                        <textarea
                          className="soft-textarea"
                          rows={2}
                          value={String(rule.notes || "")}
                          onChange={(event) =>
                            setFormState((current) => ({
                              ...current,
                              watchlist_objective_rules: current.watchlist_objective_rules.map((entry, entryIndex) =>
                                entryIndex === index ? { ...entry, notes: event.target.value } : entry,
                              ),
                            }))
                          }
                        />
                      </label>
                    </div>
                    <button
                      type="button"
                      className="small-button danger"
                      onClick={() =>
                        setFormState((current) => ({
                          ...current,
                          watchlist_objective_rules: current.watchlist_objective_rules.filter((_, entryIndex) => entryIndex !== index),
                        }))
                      }
                    >
                      Remove Rule
                    </button>
                  </article>
                ))}
                {!formState.watchlist_objective_rules.length ? <div className="empty-state">No objective monitoring rules yet.</div> : null}
              </div>
            </div>
            <div className="button-row">
              <button type="button" className="secondary" onClick={() => (window.location.href = companyHref({ id: report.company_id, ticker: report.ticker, name: report.company_name }))}>
                Back to Company
              </button>
              <button type="button" className="secondary" disabled={busy === "save"} onClick={() => void persistReport(false)}>
                {busy === "save" ? "Saving..." : "Save Draft"}
              </button>
              <button type="button" className="primary" disabled={busy === "finalize"} onClick={() => void persistReport(true)}>
                {busy === "finalize" ? "Finalizing..." : "Finalize Report"}
              </button>
            </div>
        </div>
      </section>

      <details className="panel report-collapsible-panel debug-surface-panel">
        <summary className="panel-header report-collapsible-summary">
          <div className="report-collapsible-summary-main">
            <span className="report-toggle-caret" aria-hidden="true" />
            <div>
              <h3>Owner Debug Surfaces</h3>
              <p className="muted">V2-only operational surfaces stay available here so no capability is lost while the default page follows the original app layout.</p>
            </div>
          </div>
          <span className="pill">Owner Only</span>
        </summary>
        <div className="panel-body stack-gap">
          <section className="split native-surface-split">
            <section className="panel inset-panel">
              <div className="panel-header">
                <div>
                  <h3>Completion</h3>
                  <p className="muted">Server-authoritative completion and blocker surfaces remain available here.</p>
                </div>
                <span className={`pill ${completionStatusTone(completion.status)}`}>{completion.status || "unknown"}</span>
              </div>
              <div className="rule-stack">
                <span className="pill">Covered {completion.covered_field_count}/{completion.field_count}</span>
                <span className="pill">Sourced {completion.sourced_field_count}/{completion.source_required_field_count}</span>
                <span className="pill">Notes {completion.required_noted_field_count}/{completion.required_note_field_count}</span>
                <span className="pill">Decision {completion.final_decision || "Not chosen"}</span>
              </div>
              {renderCompletionList(completion.missing_fields)}
              {renderCompletionList(completion.missing_source_links, "Missing source: ")}
              {renderCompletionList(completion.blocked_source_links, "Blocked source: ")}
              {renderCompletionList(completion.missing_required_notes, "Missing note: ")}
            </section>

            <section className="panel inset-panel">
              <div className="panel-header">
                <div>
                  <h3>Agent and Workflow Surface</h3>
                  <p className="muted">The live agent contract, workflow graph, and suggested source surface remain unchanged.</p>
                </div>
              </div>
              <div className="source-guidance-box">
                <strong>{report.agent_contract.goal || "Agent goal not provided."}</strong>
                {report.agent_contract.guidance?.length ? (
                  <ul className="compact-list">
                    {report.agent_contract.guidance.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">No additional guidance bullets are currently present in the live payload.</p>
                )}
              </div>
              <div className="rule-stack">
                <span className="pill">Suggested sources {report.suggested_sources.length}</span>
                <span className="pill">Company sources {report.company_sources.length}</span>
                <span className="pill">Readonly fields {explicitReadonlyFieldIds.length}</span>
                <span className={`pill ${latestUpstreamReport ? "warning" : ""}`}>
                  Latest upstream {latestUpstreamReport ? "available" : "none"}
                </span>
              </div>
              <details className="json-details">
                <summary>Agent Contract JSON</summary>
                <pre className="json-block">{JSON.stringify(report.agent_contract, null, 2)}</pre>
              </details>
              <details className="json-details">
                <summary>Workflow JSON</summary>
                <pre className="json-block">{JSON.stringify(report.workflow, null, 2)}</pre>
              </details>
            </section>
          </section>

          <section className="panel inset-panel">
            <div className="panel-header">
              <div>
                <h3>Report Documents</h3>
                <p className="muted">Attach files directly to this report. Normalized previews and downloads stay on the established `/api/documents/*` contracts.</p>
              </div>
            </div>
            <form
              className="stack-gap"
              onSubmit={(event) => {
                event.preventDefault();
                const formData = new FormData(event.currentTarget);
                formData.set("company_id", String(report.company_id));
                formData.set("report_id", String(report.id));
                void uploadDocument(formData);
                event.currentTarget.reset();
              }}
            >
              <div className="form-grid three-column">
                <label className="field-block">
                  <span className="field-label">File</span>
                  <input className="soft-input" type="file" name="file" required />
                </label>
                <label className="field-block">
                  <span className="field-label">Notes</span>
                  <textarea className="soft-textarea" rows={2} name="notes" />
                </label>
              </div>
              <button type="submit" className="small-button" disabled={busy === "document-upload"}>
                {busy === "document-upload" ? "Uploading..." : "Upload Report Document"}
              </button>
            </form>
            <div className="card-list">
              {report.documents.map((document) => (
                <article className="row-card compact-row-card" key={document.id}>
                  <strong>{document.original_name}</strong>
                  <div className="muted">
                    {document.mime_type || "unknown"} · {documentStatusLabel(document)} · Uploaded {formatDate(document.uploaded_at)}
                  </div>
                  <div className="tag-row">
                    <span className={`pill ${documentStatusTone(document)}`}>{documentStatusLabel(document)}</span>
                  </div>
                  <p>{document.notes || "No notes."}</p>
                  <div className="button-row">
                    <a className="small-button" href={document.download_url}>
                      Download
                    </a>
                    {document.normalized_available ? (
                      <a className="small-button" href={document.normalized_url} target="_blank" rel="noreferrer">
                        Open LLM View
                      </a>
                    ) : null}
                    <button type="button" className="small-button" onClick={() => setPreview(previewFromDocument(document))}>
                      Preview
                    </button>
                  </div>
                </article>
              ))}
              {!report.documents.length ? <div className="empty-state">No report-attached documents yet.</div> : null}
            </div>
          </section>

          <section className="split native-surface-split">
            <section className="panel inset-panel">
              <div className="panel-header">
                <div>
                  <h3>Advanced JSON Controls</h3>
                  <p className="muted">Section ratings and data quality remain part of the live PATCH body even when this report does not currently use them.</p>
                </div>
              </div>
              <label className="field-block">
                <span className="field-label">Section Ratings JSON</span>
                <textarea
                  className="soft-textarea code-textarea"
                  rows={10}
                  value={formState.section_ratings_json}
                  onChange={(event) => setFormState((current) => ({ ...current, section_ratings_json: event.target.value }))}
                />
              </label>
              <label className="field-block">
                <span className="field-label">Data Quality JSON</span>
                <textarea
                  className="soft-textarea code-textarea"
                  rows={10}
                  value={formState.data_quality_json}
                  onChange={(event) => setFormState((current) => ({ ...current, data_quality_json: event.target.value }))}
                />
              </label>
            </section>
            <section className="panel inset-panel">
              <div className="panel-header">
                <div>
                  <h3>Route Audit</h3>
                  <p className="muted">
                    Native report route: <Link href={reportHref(report)}>{reportHref(report)}</Link>
                  </p>
                </div>
              </div>
              <div className="card-list">
                <article className="row-card compact-row-card">
                  <strong>Company Route</strong>
                  <div className="muted">
                    <Link href={companyHref({ id: report.company_id, ticker: report.ticker, name: report.company_name })}>
                      {companyHref({ id: report.company_id, ticker: report.ticker, name: report.company_name })}
                    </Link>
                  </div>
                </article>
                <article className="row-card compact-row-card">
                  <strong>Payload Resource URI</strong>
                  <div className="muted">{report.resource_uri}</div>
                </article>
                <article className="row-card compact-row-card">
                  <strong>API URL</strong>
                  <div className="muted">{report.api_url}</div>
                </article>
              </div>
            </section>
          </section>
        </div>
      </details>

      {fieldPopover ? (
        <dialog className="floating-box" open onClick={(event) => {
          if (event.target === event.currentTarget) closeFieldPopover();
        }}>
          <div className="floating-box-inner field-popover-box">
            <div className="modal-header">
              <div>
                <h3>{fieldPopover.label}</h3>
                <p className="muted">Link evidence and preserve field-level notes.</p>
              </div>
              <button type="button" className="icon-button" onClick={closeFieldPopover} aria-label="Close field popover">
                ×
              </button>
            </div>
            <div className="tabs">
              <button
                type="button"
                className={`tab ${fieldPopover.activeTab === "sources" ? "active" : ""}`}
                onClick={() => setFieldPopover((current) => (current ? { ...current, activeTab: "sources" } : null))}
              >
                Sources
              </button>
              {fieldPopover.allowNotes ? (
                <button
                  type="button"
                  className={`tab ${fieldPopover.activeTab === "notes" ? "active" : ""}`}
                  onClick={() => setFieldPopover((current) => (current ? { ...current, activeTab: "notes" } : null))}
                >
                  {fieldPopover.noteLabel}
                </button>
              ) : null}
            </div>
            {fieldPopover.activeTab === "sources" ? (
              <div className="popover-pane stack-gap">
                <div className="source-picker">
                  {[
                    { title: "This Report’s Sources", description: "Sources created in this report.", sources: reportSources },
                    { title: "Suggested Company Sources", description: "Prior-stage cited sources ranked first for reuse.", sources: suggestedSources },
                    { title: "All Company Sources", description: "Remaining company-library sources available for direct citation.", sources: remainingCompanySources },
                  ].map((group) => (
                    <div className="source-picker-group" key={group.title}>
                      <div className="source-picker-heading">
                        <strong>{group.title}</strong>
                        <small>{group.description}</small>
                      </div>
                      {group.sources.length ? (
                        group.sources.map((source) => {
                          const detailBits = [
                            sourceStageContext(source),
                            source.source_type || "Source",
                            source.evidence_grade || "U",
                            source.confidence || "No confidence",
                            sourceDurabilityLabel(sourceDurabilityStatus(source)),
                          ].filter(Boolean);
                          return (
                            <label className="source-picker-row" key={`${fieldPopover.fieldId}-${source.id}`}>
                              <input
                                type="checkbox"
                                value={source.id}
                                checked={fieldPopover.sourceIds.includes(String(source.id))}
                                onChange={(event) =>
                                  setFieldPopover((current) => {
                                    if (!current) return current;
                                    const nextIds = new Set(current.sourceIds);
                                    if (event.target.checked) nextIds.add(String(source.id));
                                    else nextIds.delete(String(source.id));
                                    return { ...current, sourceIds: [...nextIds] };
                                  })
                                }
                              />
                              <span>
                                <strong>{source.title}</strong>
                                <small>{detailBits.join(" · ")}</small>
                                {source.reusability_reason ? <small>{source.reusability_reason}</small> : null}
                                {source.capture_state === "link_only" && source.link_only_reason ? <small>Why link-only: {source.link_only_reason}</small> : null}
                              </span>
                            </label>
                          );
                        })
                      ) : (
                        <div className="empty-state">No sources in this group yet.</div>
                      )}
                    </div>
                  ))}
                </div>
                <label className="field-block">
                  <span className="field-label">Citation or area</span>
                  <input
                    className="soft-input"
                    value={fieldPopover.citation}
                    placeholder="p. 234, slide 18, paragraph 3"
                    onChange={(event) => setFieldPopover((current) => (current ? { ...current, citation: event.target.value } : null))}
                  />
                </label>
              </div>
            ) : (
              <div className="popover-pane stack-gap">
                <label className="field-block">
                  <span className="field-label">Coverage exception</span>
                  <select
                    className="soft-input"
                    value={fieldPopover.exception}
                    onChange={(event) => setFieldPopover((current) => (current ? { ...current, exception: event.target.value } : null))}
                  >
                    {FIELD_EXCEPTION_OPTIONS.map(([option, label]) => (
                      <option value={option} key={option}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="muted">{fieldPopover.noteHelp}</p>
                <label className="field-block">
                  <span className="field-label">{fieldPopover.noteLabel}</span>
                  <textarea
                    className="soft-textarea"
                    rows={6}
                    placeholder={fieldPopover.notePlaceholder}
                    value={fieldPopover.note}
                    onChange={(event) => setFieldPopover((current) => (current ? { ...current, note: event.target.value } : null))}
                  />
                </label>
              </div>
            )}
            <div className="modal-actions">
              <button type="button" className="small-button" onClick={closeFieldPopover}>
                Cancel
              </button>
              <button type="button" className="small-button" onClick={saveFieldPopover}>
                Save
              </button>
            </div>
          </div>
        </dialog>
      ) : null}

      {pendingSourceDelete ? (
        <dialog className="floating-box confirm-dialog" open onClick={(event) => {
          if (event.target === event.currentTarget) setPendingSourceDelete(null);
        }}>
          <div className="floating-box-inner">
            <div className="modal-header">
              <div>
                <h3>Delete Source</h3>
                <p className="muted">
                  Delete {pendingSourceDelete.title || "this source"}? This removes it from the report and unlinks it from cited answers.
                </p>
              </div>
              <button type="button" className="icon-button" onClick={() => setPendingSourceDelete(null)} aria-label="Close delete source dialog">
                ×
              </button>
            </div>
            <div className="modal-actions">
              <button type="button" className="small-button" onClick={() => setPendingSourceDelete(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="small-button danger"
                disabled={busy === `source-delete-${pendingSourceDelete.id}`}
                onClick={() => void removeSource(pendingSourceDelete.id)}
              >
                {busy === `source-delete-${pendingSourceDelete.id}` ? "Deleting..." : "Delete Source"}
              </button>
            </div>
          </div>
        </dialog>
      ) : null}

      {sourceEditorOpen ? (
        <dialog className="floating-box" open onClick={(event) => {
          if (event.target === event.currentTarget) closeSourceEditor();
        }}>
          <div className="floating-box-inner source-editor-modal">
            <div className="modal-header">
              <div>
                <h3>{sourceEditor.id ? "Edit Source" : "Add Source"}</h3>
                <p className="muted">Import links, files, source grades, and tags. Saved sources stay available across the company record.</p>
              </div>
              <button type="button" className="icon-button" onClick={closeSourceEditor} aria-label="Close source editor">
                ×
              </button>
            </div>
            <div className="stack-gap">
              <div className="source-guidance-box warning-box">
                <strong>Durability Rules</strong>
                <ul className="compact-list">
                  <li>Cited `link_only`, `pending`, and `failed` sources block finalization.</li>
                  <li>Cited `limited` sources remain allowed but should be checked against the original artifact.</li>
                  <li>URL-only sources require snapshot-guidance acknowledgment and a `link_only_reason`.</li>
                </ul>
              </div>
              <div className="form-grid two-column">
                <label className="field-block">
                  <span className="field-label">Title</span>
                  <input
                    className="soft-input"
                    value={sourceEditor.title}
                    onChange={(event) => setSourceEditor((current) => ({ ...current, title: event.target.value }))}
                  />
                </label>
                <label className="field-block">
                  <span className="field-label">Type</span>
                  <select
                    className="soft-input"
                    value={sourceEditor.source_type}
                    onChange={(event) => setSourceEditor((current) => ({ ...current, source_type: event.target.value }))}
                  >
                    {SOURCE_TYPES.map((option) => (
                      <option value={option} key={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field-block">
                  <span className="field-label">Evidence Grade</span>
                  <select
                    className="soft-input"
                    value={sourceEditor.evidence_grade}
                    onChange={(event) => setSourceEditor((current) => ({ ...current, evidence_grade: event.target.value }))}
                  >
                    {EVIDENCE_GRADE_OPTIONS.map((option) => (
                      <option value={option} key={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field-block">
                  <span className="field-label">Confidence</span>
                  <select
                    className="soft-input"
                    value={sourceEditor.confidence}
                    onChange={(event) => setSourceEditor((current) => ({ ...current, confidence: event.target.value }))}
                  >
                    {CONFIDENCE_OPTIONS.map((option) => (
                      <option value={option} key={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="form-grid two-column">
                <label className="field-block">
                  <span className="field-label">URL</span>
                  <input
                    className="soft-input"
                    value={sourceEditor.url}
                    onChange={(event) => setSourceEditor((current) => ({ ...current, url: event.target.value }))}
                  />
                </label>
                <label className="field-block">
                  <span className="field-label">Default Citation</span>
                  <input
                    className="soft-input"
                    value={sourceEditor.citation}
                    onChange={(event) => setSourceEditor((current) => ({ ...current, citation: event.target.value }))}
                  />
                </label>
                <label className="field-block">
                  <span className="field-label">Tags</span>
                  <input
                    className="soft-input"
                    value={sourceEditor.tags}
                    onChange={(event) => setSourceEditor((current) => ({ ...current, tags: event.target.value }))}
                  />
                </label>
                <label className="field-block">
                  <span className="field-label">Snapshot File</span>
                  <input
                    className="soft-input"
                    type="file"
                    onChange={(event) =>
                      setSourceEditor((current) => ({
                        ...current,
                        file: event.target.files?.[0] || null,
                      }))
                    }
                  />
                </label>
              </div>
              <label className="field-block">
                <span className="field-label">Notes</span>
                <textarea
                  className="soft-textarea"
                  rows={3}
                  value={sourceEditor.notes}
                  onChange={(event) => setSourceEditor((current) => ({ ...current, notes: event.target.value }))}
                />
              </label>
              <label className="field-block">
                <span className="field-label">Link-Only Reason</span>
                <textarea
                  className="soft-textarea"
                  rows={2}
                  value={sourceEditor.link_only_reason}
                  onChange={(event) => setSourceEditor((current) => ({ ...current, link_only_reason: event.target.value }))}
                />
              </label>
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={sourceEditor.snapshot_guidance_acknowledged}
                  onChange={(event) =>
                    setSourceEditor((current) => ({
                      ...current,
                      snapshot_guidance_acknowledged: event.target.checked,
                    }))
                  }
                />
                <span>I read the snapshot guidance and understand URL-only sources remain degraded until a snapshot is uploaded.</span>
              </label>
            </div>
            <div className="modal-actions">
              <button type="button" className="small-button" onClick={closeSourceEditor}>
                Cancel
              </button>
              <button type="button" className="small-button" disabled={busy === "source-save"} onClick={() => void persistSource()}>
                {busy === "source-save" ? "Saving..." : sourceEditor.id ? "Update Source" : "Save Source"}
              </button>
            </div>
          </div>
        </dialog>
      ) : null}

      {preview ? (
        <dialog className="floating-box" open onClick={(event) => {
          if (event.target === event.currentTarget) setPreview(null);
        }}>
          <div className="floating-box-inner preview-dialog-box">
            <div className="modal-header">
              <div>
                <h3>{preview.title}</h3>
                <p className="muted">{preview.meta || "LLM-ready source preview."}</p>
              </div>
              <button type="button" className="icon-button" onClick={() => setPreview(null)} aria-label="Close preview">
                ×
              </button>
            </div>
            <pre className="json-block preview-block">{preview.preview || preview.notes || "No normalized preview available."}</pre>
            <div className="modal-actions">
              {preview.normalizedAvailable && preview.normalizedUrl ? (
                <a className="small-button" href={preview.normalizedUrl} target="_blank" rel="noreferrer">
                  Open LLM View
                </a>
              ) : null}
              {preview.downloadUrl ? (
                <a className="small-button" href={preview.downloadUrl}>
                  Download Original
                </a>
              ) : null}
              <button type="button" className="small-button" onClick={() => setPreview(null)}>
                Close Preview
              </button>
            </div>
          </div>
        </dialog>
      ) : null}
    </>
  );
}
