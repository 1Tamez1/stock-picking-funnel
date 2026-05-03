"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  createReport,
  deleteReport,
  deleteReportSource,
  getCompany,
  updateMonitoringRule,
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
import type { CompanyRecord, DocumentRecord, MonitoringRuleRecord, SourceRecord, StageRecord } from "../lib/types";

function formatDate(value: string): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return date.toLocaleString();
}

function reviewValue(company: CompanyRecord): string {
  return company.review_date || company.next_action || company.latest_summary || "No watchlist or archive summary yet.";
}

function previewPayload(item: DocumentRecord | SourceRecord) {
  const title = "original_name" in item ? item.original_name : item.title || item.document_name || `Document ${item.document_id}`;
  const preview = "original_name" in item ? item.normalized_preview : item.normalized_preview || item.notes || "";
  const notes = "original_name" in item ? item.normalized_notes : item.normalized_notes || item.notes || "";
  const normalizedUrl = "original_name" in item ? item.normalized_url : item.document_normalized_url;
  const downloadUrl = "original_name" in item ? item.download_url : item.document_download_url;
  const normalizedAvailable = "original_name" in item ? item.normalized_available : item.normalized_available;
  return {
    title,
    meta: [item.normalized_status, item.normalized_format, item.normalized_method].filter(Boolean).join(" · "),
    preview,
    notes,
    normalizedUrl,
    downloadUrl,
    normalizedAvailable,
  };
}

function pendingDocumentCount(company: CompanyRecord): number {
  const pendingDocuments = company.documents.filter((document) => document.normalized_status === "pending");
  const pendingSources = company.company_sources.filter((source) => source.capture_state === "pending");
  return pendingDocuments.length + pendingSources.length;
}

function failedDocumentCount(company: CompanyRecord): number {
  const failedDocuments = company.documents.filter((document) => document.normalized_status === "failed");
  const failedSources = company.company_sources.filter((source) => sourceDurabilityStatus(source) === "failed");
  return failedDocuments.length + failedSources.length;
}

export function NativeCompanyClient({
  initialCompany,
  stages,
}: {
  initialCompany: CompanyRecord;
  stages: StageRecord[];
}) {
  const initialRuleDrafts = Object.fromEntries(
    initialCompany.monitoring_rules.map((rule) => [
      rule.id,
      {
        current_value: rule.current_value == null ? "" : String(rule.current_value),
        notes: rule.notes || "",
      },
    ]),
  );
  const [company, setCompany] = useState(initialCompany);
  const [createDraft, setCreateDraft] = useState({
    stage_id: initialCompany.current_stage_id == null ? String(stages[0]?.id || "") : String(initialCompany.current_stage_id),
    report_month: "",
    title: "",
  });
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string>("");
  const [preview, setPreview] = useState<ReturnType<typeof previewPayload> | null>(null);
  const [ruleDrafts, setRuleDrafts] = useState<Record<number, { current_value: string; notes: string }>>(initialRuleDrafts);
  const [savedSnapshot, setSavedSnapshot] = useState(() =>
    JSON.stringify({
      createDraft: {
        stage_id: initialCompany.current_stage_id == null ? String(stages[0]?.id || "") : String(initialCompany.current_stage_id),
        report_month: "",
        title: "",
      },
      ruleDrafts: initialRuleDrafts,
    }),
  );

  async function refreshCompany(showStatus = false, preserveRuleDrafts = true) {
    const result = await getCompany(company.id);
    setCompany(result.company);
    if (!preserveRuleDrafts) {
      const nextRuleDrafts = Object.fromEntries(
        result.company.monitoring_rules.map((rule) => [
          rule.id,
          {
            current_value: rule.current_value == null ? "" : String(rule.current_value),
            notes: rule.notes || "",
          },
        ]),
      );
      setRuleDrafts(nextRuleDrafts);
      setSavedSnapshot(JSON.stringify({ createDraft, ruleDrafts: nextRuleDrafts }));
    }
    if (showStatus) setStatus(`Refreshed ${result.company.ticker}.`);
  }

  useEffect(() => {
    if (!pendingDocumentCount(company)) return undefined;
    const timer = window.setInterval(() => {
      void refreshCompany(false, true);
    }, 8000);
    return () => window.clearInterval(timer);
  }, [company]);

  const currentSnapshot = useMemo(() => JSON.stringify({ createDraft, ruleDrafts }), [createDraft, ruleDrafts]);
  const hasUnsavedChanges = currentSnapshot !== savedSnapshot;
  const failedProcessing = useMemo(() => failedDocumentCount(company), [company]);

  useEffect(() => {
    if (!hasUnsavedChanges) return undefined;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [hasUnsavedChanges]);

  const metrics = useMemo(
    () => ({
      reports: company.reports.length,
      documents: company.documents.length,
      sources: company.company_sources.length,
      pending: pendingDocumentCount(company),
    }),
    [company],
  );

  async function handleCreateReport() {
    setBusy("create-report");
    setStatus("");
    setError("");
    try {
      const result = await createReport({
        company_id: company.id,
        stage_id: createDraft.stage_id,
        report_month: createDraft.report_month,
        title: createDraft.title,
      });
      window.location.href = reportHref(result.report);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to create report.");
    } finally {
      setBusy("");
    }
  }

  async function handleDeleteReport(reportId: number, title: string) {
    if (!window.confirm(`Delete ${title}? This removes it from the company timeline and unlinks derived company state.`)) return;
    setBusy(`delete-report-${reportId}`);
    setStatus("");
    setError("");
    try {
      const result = await deleteReport(reportId);
      setCompany(result.company);
      setRuleDrafts(
        Object.fromEntries(
          result.company.monitoring_rules.map((rule) => [
            rule.id,
            {
              current_value: rule.current_value == null ? "" : String(rule.current_value),
              notes: rule.notes || "",
            },
          ]),
        ),
      );
      setStatus("Report deleted.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to delete report.");
    } finally {
      setBusy("");
    }
  }

  async function handleUploadDocuments(formData: FormData) {
    setBusy("upload-document");
    setStatus("");
    setError("");
    try {
      await uploadDocuments(formData);
      await refreshCompany(false, true);
      setStatus("Document uploaded.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to upload document.");
    } finally {
      setBusy("");
    }
  }

  async function handleDeleteSource(source: SourceRecord) {
    if (!window.confirm(`Delete ${source.title}? This removes it from the company source library and unlinks cited answers.`)) return;
    setBusy(`delete-source-${source.id}`);
    setStatus("");
    setError("");
    try {
      await deleteReportSource(source.id);
      await refreshCompany(false, true);
      setStatus("Source deleted.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to delete source.");
    } finally {
      setBusy("");
    }
  }

  async function handleRuleSave(rule: MonitoringRuleRecord) {
    const draft = ruleDrafts[rule.id];
    if (!draft) return;
    setBusy(`rule-${rule.id}`);
    setStatus("");
    setError("");
    try {
      await updateMonitoringRule(rule.id, draft);
      await refreshCompany(false, false);
      setStatus(`Saved runtime update for ${rule.metric_name}.`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to save monitoring update.");
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      {hasUnsavedChanges ? (
        <section className="panel save-state-banner">
          Unsaved company-stage inputs are present. Leaving or reloading this page now will discard the current report-creation
          draft or monitoring edits.
        </section>
      ) : null}
      <section className="metric-grid">
        <article className="metric-card">
          <span className="eyebrow">Reports</span>
          <strong>{metrics.reports}</strong>
          <p className="muted">Stage reports attached to this company.</p>
        </article>
        <article className="metric-card">
          <span className="eyebrow">Documents</span>
          <strong>{metrics.documents}</strong>
          <p className="muted">Files attached at company or report scope.</p>
        </article>
        <article className="metric-card">
          <span className="eyebrow">Company Sources</span>
          <strong>{metrics.sources}</strong>
          <p className="muted">Reusable source objects available to later stages.</p>
        </article>
        <article className="metric-card">
          <span className="eyebrow">Pending LLM Views</span>
          <strong>{metrics.pending}</strong>
          <p className="muted">Documents or sources still waiting for normalization.</p>
        </article>
      </section>

      {status ? <section className="panel status-banner">{status}</section> : null}
      {error ? <section className="panel error-banner">{error}</section> : null}
      {failedProcessing ? (
        <section className="panel warning-box">
          <strong>{failedProcessing}</strong> document or reusable source items currently show failed processing or failed
          durability. Review them before reusing those artifacts downstream.
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>
              {company.ticker} · {company.name}
            </h2>
            <p className="muted">{company.notes || "No company notes yet."}</p>
          </div>
          <div className="rule-stack">
            <span className="pill">{company.bucket || "unknown"}</span>
            {company.latest_result ? <span className="pill green">{company.latest_result}</span> : null}
            {company.current_stage_name ? <span className="pill">{company.current_stage_name}</span> : null}
          </div>
        </div>
        <div className="split">
          <div className="panel inset-panel">
            <h3>Current Summary</h3>
            <p>{company.latest_summary || "No latest summary yet."}</p>
          </div>
          <div className="panel inset-panel">
            <h3>Watchlist / Archive Context</h3>
            <p className="prewrap-text">{reviewValue(company)}</p>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Reports</h2>
            <p className="muted">Create a new stage report or continue any existing report from its own routed page.</p>
          </div>
        </div>
        <div className="stack-gap">
          <div className="form-grid three-column">
            <label className="field-block">
              <span className="field-label">Stage</span>
              <select
                className="soft-input"
                value={createDraft.stage_id}
                onChange={(event) => setCreateDraft((current) => ({ ...current, stage_id: event.target.value }))}
              >
                {stages.map((stage) => (
                  <option value={stage.id} key={stage.id}>
                    {stage.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field-block">
              <span className="field-label">Report Month</span>
              <input
                className="soft-input"
                value={createDraft.report_month}
                onChange={(event) => setCreateDraft((current) => ({ ...current, report_month: event.target.value }))}
                placeholder="April 2026"
              />
            </label>
            <label className="field-block">
              <span className="field-label">Title</span>
              <input
                className="soft-input"
                value={createDraft.title}
                onChange={(event) => setCreateDraft((current) => ({ ...current, title: event.target.value }))}
                placeholder="Optional custom title"
              />
            </label>
          </div>
          <div className="button-row">
            <button type="button" className="small-button" disabled={busy === "create-report"} onClick={() => void handleCreateReport()}>
              {busy === "create-report" ? "Creating..." : "Create Report"}
            </button>
            <Link href="/companies" className="ghost-link">
              Back to Companies Index
            </Link>
          </div>
          <div className="card-list">
            {company.reports.map((report) => (
              <article className="row-card" key={report.id}>
                <header>
                  <strong>
                    <Link href={reportHref(report)}>{report.title}</Link>
                  </strong>
                  <span className="pill">{report.result || "Draft"}</span>
                </header>
                <p className="muted">
                  {report.stage_name} · {report.report_month || "No report month"} · Updated {formatDate(report.updated_at)}
                </p>
                <p>{report.summary || "No summary yet."}</p>
                <div className="button-row">
                  <Link href={reportHref(report)} className="small-button">
                    Open Report
                  </Link>
                  <button
                    type="button"
                    className="small-button danger"
                    disabled={busy === `delete-report-${report.id}`}
                    onClick={() => void handleDeleteReport(report.id, report.title)}
                  >
                    {busy === `delete-report-${report.id}` ? "Deleting..." : "Delete"}
                  </button>
                </div>
              </article>
            ))}
            {!company.reports.length ? <div className="empty-state">No reports yet.</div> : null}
          </div>
        </div>
      </section>

      <section className="split native-surface-split">
        <section className="panel">
          <div className="panel-header">
            <div>
              <h2>Documents</h2>
              <p className="muted">
                Upload filings, spreadsheets, notes, or snapshots. Normalized LLM views continue to come from the backend.
              </p>
            </div>
          </div>
          <form
            className="stack-gap"
            onSubmit={(event) => {
              event.preventDefault();
              const formData = new FormData(event.currentTarget);
              void handleUploadDocuments(formData);
              event.currentTarget.reset();
            }}
          >
            <input type="hidden" name="company_id" value={company.id} />
            <div className="form-grid three-column">
              <label className="field-block">
                <span className="field-label">Attach To Report</span>
                <select className="soft-input" name="report_id" defaultValue="">
                  <option value="">Company-level document</option>
                  {company.reports.map((report) => (
                    <option value={report.id} key={report.id}>
                      {report.title}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field-block">
                <span className="field-label">File</span>
                <input className="soft-input" name="file" type="file" required />
              </label>
              <label className="field-block">
                <span className="field-label">Notes</span>
                <textarea className="soft-textarea" name="notes" rows={2} />
              </label>
            </div>
            <button type="submit" className="small-button" disabled={busy === "upload-document"}>
              {busy === "upload-document" ? "Uploading..." : "Upload Document"}
            </button>
          </form>
          <div className="card-list">
            {company.documents.map((document) => {
              const previewItem = previewPayload(document);
              return (
                <article className="row-card compact-row-card" key={document.id}>
                  <strong>{document.original_name}</strong>
                  <div className="muted">
                    {document.mime_type || "unknown"} · {document.size_bytes} bytes · {documentStatusLabel(document)}
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
                    <button type="button" className="small-button" onClick={() => setPreview(previewItem)}>
                      Preview
                    </button>
                  </div>
                </article>
              );
            })}
            {!company.documents.length ? <div className="empty-state">No documents attached yet.</div> : null}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <div>
              <h2>Company Sources</h2>
              <p className="muted">
                Reuse these sources in downstream reports instead of re-uploading duplicate evidence.
              </p>
            </div>
          </div>
          <div className="card-list">
            {company.company_sources.map((source) => {
              const previewItem = previewPayload(source);
              return (
                <article className="row-card compact-row-card" key={source.id}>
                  <header>
                    <strong>{source.title}</strong>
                    <span className={`pill ${sourceDurabilityTone(sourceDurabilityStatus(source))}`}>
                      {sourceDurabilityLabel(sourceDurabilityStatus(source))}
                    </span>
                  </header>
                  <div className="muted">
                    {source.source_type || "Unspecified"} · {source.evidence_grade || "U"} · {source.confidence || "No confidence"}
                  </div>
                  {sourceStageContext(source) ? <div className="muted">{sourceStageContext(source)}</div> : null}
                  <p>{source.notes || source.citation || "No source notes yet."}</p>
                  <p className="muted">{sourceDurabilityReason(source)}</p>
                  <div className="tag-row">
                    {(source.tags || []).map((tag) => (
                      <span className="pill" key={`${source.id}-${tag}`}>
                        {tag}
                      </span>
                    ))}
                  </div>
                  <div className="button-row">
                    {source.url ? (
                      <a className="small-button" href={source.url} target="_blank" rel="noreferrer">
                        Open URL
                      </a>
                    ) : null}
                    {source.document_download_url ? (
                      <a className="small-button" href={source.document_download_url}>
                        Download Snapshot
                      </a>
                    ) : null}
                    {source.normalized_available && source.document_normalized_url ? (
                      <a className="small-button" href={source.document_normalized_url} target="_blank" rel="noreferrer">
                        Open LLM View
                      </a>
                    ) : null}
                    {(source.normalized_preview || source.notes) ? (
                      <button type="button" className="small-button" onClick={() => setPreview(previewItem)}>
                        Preview
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="small-button danger"
                      disabled={busy === `delete-source-${source.id}`}
                      onClick={() => void handleDeleteSource(source)}
                    >
                      {busy === `delete-source-${source.id}` ? "Deleting..." : "Delete"}
                    </button>
                  </div>
                </article>
              );
            })}
            {!company.company_sources.length ? <div className="empty-state">No company sources yet.</div> : null}
          </div>
        </section>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Monitoring Rules</h2>
            <p className="muted">Runtime fields stay editable here. Structural rule creation still happens through report finalization.</p>
          </div>
        </div>
        {company.monitoring_rules.length ? (
          <div className="table-wrap">
            <table className="native-table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Rule</th>
                  <th>Source</th>
                  <th>Runtime Updates</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {company.monitoring_rules.map((rule) => {
                  const draft = ruleDrafts[rule.id] || { current_value: "", notes: "" };
                  return (
                    <tr key={rule.id}>
                      <td>{rule.metric_name}</td>
                      <td>
                        {rule.comparator} {rule.threshold_value ?? ""} {rule.unit || ""}
                      </td>
                      <td>{rule.source || "Report objective rule"}</td>
                      <td>
                        <div className="rule-edit-grid">
                          <input
                            className="soft-input"
                            type="number"
                            step="any"
                            value={draft.current_value}
                            onChange={(event) =>
                              setRuleDrafts((current) => ({
                                ...current,
                                [rule.id]: {
                                  ...draft,
                                  current_value: event.target.value,
                                },
                              }))
                            }
                          />
                          <textarea
                            className="soft-textarea"
                            rows={2}
                            value={draft.notes}
                            onChange={(event) =>
                              setRuleDrafts((current) => ({
                                ...current,
                                [rule.id]: {
                                  ...draft,
                                  notes: event.target.value,
                                },
                              }))
                            }
                          />
                          <button
                            type="button"
                            className="small-button"
                            disabled={busy === `rule-${rule.id}`}
                            onClick={() => void handleRuleSave(rule)}
                          >
                            {busy === `rule-${rule.id}` ? "Saving..." : "Save"}
                          </button>
                        </div>
                      </td>
                      <td>
                        <span className={`pill ${Boolean(rule.triggered) ? "green" : "amber"}`}>
                          {Boolean(rule.triggered) ? "Triggered" : "Waiting"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">No monitoring rules exist for this company yet.</div>
        )}
      </section>

      {preview ? (
        <section className="panel preview-panel">
          <div className="panel-header">
            <div>
              <h2>{preview.title}</h2>
              <p className="muted">{preview.meta || "LLM-ready source preview."}</p>
            </div>
            <div className="button-row">
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
          <pre className="json-block preview-block">{preview.preview || preview.notes || "No normalized preview available."}</pre>
        </section>
      ) : null}

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>Route Audit</h2>
            <p className="muted">
              Native detail route: <Link href={companyHref(company)}>{companyHref(company)}</Link>
            </p>
          </div>
        </div>
      </section>
    </>
  );
}
