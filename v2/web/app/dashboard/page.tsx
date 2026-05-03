import Link from "next/link";
import type { Route } from "next";

import { SurfaceHeader } from "../../components/surface-header";
import { getBootstrap } from "../../lib/api";
import { legacyRoutePath } from "../../lib/legacy";
import { buildQueryPath } from "../../lib/query";
import { companyHref } from "../../lib/routes";

const BUCKET_ROUTES: Record<string, string> = {
  pool: "/pool",
  funnel: "/funnel",
  watchlist: "/watchlist",
  archive: "/archive",
  monitoring: "/monitoring",
};

function bucketHref(bucketKey: string): Route {
  return (BUCKET_ROUTES[bucketKey] || buildQueryPath("/companies", { bucket: bucketKey })) as Route;
}

export default async function DashboardPage() {
  const payload = await getBootstrap();
  return (
    <>
      <SurfaceHeader
        eyebrow="Research Control"
        title="Dashboard"
        description="Native dashboard backed by the preserved bootstrap payload. Bucket counts, stage counts, monitoring alerts, and deep links stay aligned with the compatibility backend."
        legacyHref={legacyRoutePath("/dashboard")}
      />
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Bucket Overview</p>
            <h2>Research Buckets</h2>
          </div>
        </div>
        <div className="metric-grid">
          {payload.dashboard.buckets.map((bucket) => (
            <Link href={bucketHref(bucket.key)} className="metric-card metric-link" key={bucket.key}>
              <span className="muted">{bucket.name}</span>
              <strong>{bucket.count}</strong>
              <span className="metric-caption">Open {bucket.name.toLowerCase()} companies</span>
            </Link>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Stage Flow</p>
            <h2>Funnel Stages</h2>
          </div>
        </div>
        <div className="metric-grid">
          {payload.dashboard.stages.map((stage) => (
            <Link
              href={buildQueryPath("/funnel", { stage_id: stage.id }) as Route}
              className="metric-card metric-link"
              key={stage.id}
            >
              <span className="muted">{stage.name}</span>
              <strong>{stage.count}</strong>
              <span className="metric-caption">{stage.completed_reports} completed reports</span>
            </Link>
          ))}
        </div>
      </section>
      <section className="split">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Alerts</p>
              <h2>Triggered Monitoring Rules</h2>
            </div>
          </div>
          {payload.dashboard.alerts.length ? (
            <div className="card-list">
              {payload.dashboard.alerts.map((rule) => (
                <article className="row-card compact-row-card" key={rule.id}>
                  <header>
                    <strong>
                      <Link
                        href={companyHref({
                          id: rule.company_id,
                          ticker: rule.ticker,
                          name: rule.company_name,
                        })}
                      >
                        {rule.ticker || rule.company_name || `Company ${rule.company_id}`}
                      </Link>
                    </strong>
                    <span className={`pill ${Boolean(rule.triggered) ? "red" : "amber"}`}>
                      {Boolean(rule.triggered) ? "Triggered" : "Waiting"}
                    </span>
                  </header>
                  <p className="muted">{rule.metric_name}</p>
                  <p>
                    Current value {rule.current_value ?? "unknown"} {rule.comparator} {rule.threshold_value ?? "unknown"} {rule.unit || ""}
                  </p>
                </article>
              ))}
            </div>
          ) : (
            <div className="empty-state">No triggered monitoring rules right now.</div>
          )}
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Activity</p>
              <h2>Saved Research Totals</h2>
            </div>
          </div>
          <div className="metric-grid">
            <article className="metric-card">
              <span className="muted">Reports Created</span>
              <strong>{payload.settings_summary.reports_created_total ?? 0}</strong>
            </article>
            <article className="metric-card">
              <span className="muted">Sources Uploaded</span>
              <strong>{payload.settings_summary.sources_uploaded_total ?? 0}</strong>
            </article>
            <article className="metric-card">
              <span className="muted">Outside Pool</span>
              <strong>{payload.settings_summary.companies_outside_pool_total ?? 0}</strong>
            </article>
          </div>
        </section>
      </section>
    </>
  );
}
