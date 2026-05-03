import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";

import { buildQueryPath } from "../lib/query";
import { companyHref, reportHref } from "../lib/routes";
import type { CompanySummaryRecord, ReportSummaryRecord } from "../lib/types";

export type FilterOption = {
  label: string;
  value: string;
};

function formatDate(value: string): string {
  if (!value) return "No date";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return date.toLocaleDateString();
}

function resultTone(result: string | undefined): string {
  if (result === "Proceed to Next Step") return "green";
  if (result === "Watchlist") return "amber";
  if (result === "Archive") return "red";
  if (String(result || "").startsWith("Return to ")) return "cyan";
  return "";
}

function statusTone(bucket: string | undefined): string {
  if (bucket === "funnel") return "green";
  if (bucket === "watchlist") return "amber";
  if (bucket === "archive") return "red";
  if (bucket === "monitoring") return "cyan";
  return "";
}

function companySummary(company: CompanySummaryRecord, mode: "pool" | "funnel" | "watchlist" | "archive" | "companies"): string {
  if (mode === "watchlist") return company.watchlist_conditions || company.latest_summary || "No watchlist summary yet.";
  if (mode === "archive") return company.archive_red_flags || company.latest_summary || "No archive summary yet.";
  if (mode === "pool" && company.bucket === "watchlist") return company.watchlist_conditions || company.latest_summary || "No watchlist summary yet.";
  if (mode === "pool" && company.bucket === "archive") return company.archive_red_flags || company.latest_summary || "No archive summary yet.";
  return company.latest_summary || company.latest_result || "No summary yet.";
}

function watchlistRuleLine(company: CompanySummaryRecord): string {
  const rules = company.monitoring_rules || [];
  if (!rules.length) return "No objective monitoring rules.";
  const triggered = rules.filter((rule) => Boolean(rule.triggered)).length;
  return `${rules.length} objective rules · ${triggered} triggered`;
}

function compactSummary(text: string, emptyMessage: string) {
  const normalized = String(text || "").trim();
  if (!normalized) return <p className="muted">{emptyMessage}</p>;
  if (normalized.length <= 120) return <p>{normalized}</p>;
  return (
    <details className="summary-cell summary-toggle">
      <summary className="summary-preview">{normalized}</summary>
    </details>
  );
}

export function QueryToolbar({
  action,
  search,
  searchPlaceholder,
  order,
  orderOptions,
  perPage,
  resetHref,
  children,
}: {
  action: string;
  search: string;
  searchPlaceholder: string;
  order: string;
  orderOptions: FilterOption[];
  perPage: number;
  resetHref: string;
  children?: ReactNode;
}) {
  return (
    <section className="panel toolbar-panel">
      <form action={action} className="toolbar-form">
        <div className="toolbar-grid">
          <label className="field-block">
            <span className="field-label">Search</span>
            <input className="soft-input" name="search" defaultValue={search} placeholder={searchPlaceholder} />
          </label>
          {children}
          <label className="field-block">
            <span className="field-label">Order</span>
            <select className="soft-input" name="order" defaultValue={order}>
              {orderOptions.map((option) => (
                <option value={option.value} key={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field-block">
            <span className="field-label">Rows</span>
            <select className="soft-input" name="per_page" defaultValue={String(perPage)}>
              {[25, 50, 100, 200].map((value) => (
                <option value={value} key={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="toolbar-actions">
          <button type="submit" className="small-button">
            Apply
          </button>
          <Link href={resetHref as Route} className="ghost-link">
            Reset
          </Link>
        </div>
      </form>
    </section>
  );
}

export function PaginationNav({
  path,
  params,
  page,
  perPage,
  total,
  label,
}: {
  path: string;
  params: Record<string, string | number | boolean | null | undefined>;
  page: number;
  perPage: number;
  total: number;
  label: string;
}) {
  const totalPages = Math.max(1, Math.ceil(Number(total || 0) / Math.max(1, Number(perPage || 1))));
  const start = total ? (page - 1) * perPage + 1 : 0;
  const end = total ? Math.min(total, start + perPage - 1) : 0;
  if (totalPages <= 1) {
    return (
      <section className="panel pagination-panel">
        <span className="muted">{total ? `${start}-${end} of ${total} ${label}` : `0 ${label}`}</span>
      </section>
    );
  }
  const previousHref = buildQueryPath(path, { ...params, page: Math.max(1, page - 1), per_page: perPage }) as Route;
  const nextHref = buildQueryPath(path, { ...params, page: Math.min(totalPages, page + 1), per_page: perPage }) as Route;
  const firstHref = buildQueryPath(path, { ...params, page: 1, per_page: perPage }) as Route;
  const lastHref = buildQueryPath(path, { ...params, page: totalPages, per_page: perPage }) as Route;

  return (
    <section className="panel pagination-panel">
      <span className="muted">{total ? `${start}-${end} of ${total} ${label}` : `0 ${label}`}</span>
      <div className="button-row">
        <Link href={firstHref} className="ghost-link">
          First
        </Link>
        <Link href={previousHref} className="ghost-link">
          Back
        </Link>
        <span className="pill">
          Page {page} of {totalPages}
        </span>
        <Link href={nextHref} className="ghost-link">
          Next
        </Link>
        <Link href={lastHref} className="ghost-link">
          Last
        </Link>
      </div>
    </section>
  );
}

export function CompanyCollection({
  companies,
  mode,
  emptyMessage,
}: {
  companies: CompanySummaryRecord[];
  mode: "pool" | "funnel" | "watchlist" | "archive" | "companies";
  emptyMessage: string;
}) {
  if (!companies.length) {
    return <section className="panel empty-state">{emptyMessage}</section>;
  }
  return (
    <section className="card-list">
      {companies.map((company) => (
        <article className="row-card" key={company.id}>
          <header>
            <strong>
              <Link href={companyHref(company)}>{company.ticker || company.name || `Company ${company.id}`}</Link>
            </strong>
            <div className="button-row">
              <span className={`pill ${statusTone(company.bucket)}`}>{company.bucket || "pool"}</span>
              {company.current_stage_name ? <span className="pill">{company.current_stage_name}</span> : null}
              {company.latest_result ? <span className={`pill ${resultTone(company.latest_result)}`}>{company.latest_result}</span> : null}
            </div>
          </header>
          <p className="muted">{company.name || "Unnamed company"}</p>
          {compactSummary(companySummary(company, mode), "No summary yet.")}
          <div className="support-grid">
            <span className="muted">Next action: {company.next_action || "None saved"}</span>
            <span className="muted">Review date: {company.review_date || "None saved"}</span>
          </div>
          {mode === "watchlist" ? <p className="muted">{watchlistRuleLine(company)}</p> : null}
        </article>
      ))}
    </section>
  );
}

export function ReportCollection({
  reports,
  emptyMessage,
}: {
  reports: ReportSummaryRecord[];
  emptyMessage: string;
}) {
  if (!reports.length) {
    return <section className="panel empty-state">{emptyMessage}</section>;
  }
  return (
    <section className="card-list">
      {reports.map((report) => (
        <article className="row-card" key={report.id}>
          <header>
            <strong>
              <Link href={reportHref(report)}>{report.title || `Report ${report.id}`}</Link>
            </strong>
            <div className="button-row">
              <span className="pill">{report.stage_name || "Unknown stage"}</span>
              <span className={`pill ${resultTone(report.result)}`}>{report.result || "Draft"}</span>
            </div>
          </header>
          <p className="muted">
            {[report.ticker, report.company_name, report.report_month].filter(Boolean).join(" · ")}
          </p>
          {compactSummary(report.summary || report.next_action || "", "No summary yet.")}
          <div className="support-grid">
            <span className="muted">Updated: {formatDate(report.updated_at)}</span>
            <span className="muted">
              Completed: {report.completed_at ? formatDate(report.completed_at) : "Draft / not finalized"}
            </span>
          </div>
          {report.company_name && report.ticker ? (
            <div className="button-row">
              <Link
                href={companyHref({ id: report.company_id, ticker: report.ticker, name: report.company_name })}
                className="ghost-link"
              >
                Open Company
              </Link>
            </div>
          ) : null}
        </article>
      ))}
    </section>
  );
}
