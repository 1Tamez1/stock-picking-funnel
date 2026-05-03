import Link from "next/link";

import { companyHref, reportHref } from "../lib/routes";

type CompanySummary = {
  id: number;
  public_id?: string;
  ticker?: string;
  name?: string;
  bucket?: string;
  current_stage_name?: string;
  latest_summary?: string;
};

type ReportSummary = {
  id: number;
  public_id?: string;
  title?: string;
  stage_name?: string;
  result?: string;
  ticker?: string;
  summary?: string;
};

export function CompanyList({ companies }: { companies: CompanySummary[] }) {
  return (
    <section className="panel">
      <h2>Companies</h2>
      <div className="card-list">
        {companies.map((company) => (
          <article className="row-card" key={company.id}>
            <header>
              <strong>
                <Link href={companyHref(company)}>{company.ticker || company.name || `Company ${company.id}`}</Link>
              </strong>
              <span className="pill">{company.bucket || "unknown"}</span>
            </header>
            <p className="muted">{company.name || "Unnamed company"}</p>
            <p>{company.latest_summary || company.current_stage_name || "No summary yet."}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

export function ReportList({ reports }: { reports: ReportSummary[] }) {
  return (
    <section className="panel">
      <h2>Reports</h2>
      <div className="card-list">
        {reports.map((report) => (
          <article className="row-card" key={report.id}>
            <header>
              <strong>
                <Link href={reportHref(report)}>{report.title || `Report ${report.id}`}</Link>
              </strong>
              <span className="pill">{report.result || "Draft"}</span>
            </header>
            <p className="muted">{[report.ticker, report.stage_name].filter(Boolean).join(" - ")}</p>
            <p>{report.summary || "No summary yet."}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
