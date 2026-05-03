import Link from "next/link";
import type { Route } from "next";

import { CompanyCollection, PaginationNav, QueryToolbar } from "../../components/native-route-surfaces";
import { SurfaceHeader } from "../../components/surface-header";
import { getBootstrap, getCompanies } from "../../lib/api";
import { legacyRoutePath } from "../../lib/legacy";
import { COMPANY_ORDER_OPTIONS } from "../../lib/list-options";
import { buildQueryPath, parseIntegerParam, parseStringParam, type SearchParamRecord } from "../../lib/query";

export default async function FunnelPage({ searchParams }: { searchParams: Promise<SearchParamRecord> }) {
  const params = await searchParams;
  const search = parseStringParam(params, "search");
  const stageId = parseStringParam(params, "stage_id");
  const order = parseStringParam(params, "order", "updated_desc");
  const perPage = parseIntegerParam(params, "per_page", 50, { min: 1, max: 200 });
  const page = parseIntegerParam(params, "page", 1, { min: 1 });
  const [bootstrap, payload] = await Promise.all([
    getBootstrap(),
    getCompanies(buildQueryPath("/api/companies", { bucket: "funnel", stage_id: stageId, search, order, per_page: perPage, page })),
  ]);

  return (
    <>
      <SurfaceHeader
        eyebrow="Active Research"
        title="Funnel"
        description="Native funnel board backed by the preserved active-company list API. Stage filtering remains URL-driven and stage counts still come from the compatibility bootstrap payload."
        legacyHref={legacyRoutePath("/funnel")}
      />
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Stage Filters</p>
            <h2>Current Funnel Load</h2>
          </div>
        </div>
        <div className="metric-grid">
          <Link href={"/funnel" as Route} className={`metric-card metric-link ${stageId ? "" : "selected-card"}`}>
            <span className="muted">All Active Companies</span>
            <strong>{bootstrap.dashboard.buckets.find((bucket) => bucket.key === "funnel")?.count ?? payload.total}</strong>
            <span className="metric-caption">Clear stage filter</span>
          </Link>
          {bootstrap.dashboard.stages.map((stage) => (
            <Link
              href={buildQueryPath("/funnel", { stage_id: stage.id }) as Route}
              className={`metric-card metric-link ${stageId === String(stage.id) ? "selected-card" : ""}`}
              key={stage.id}
            >
              <span className="muted">{stage.name}</span>
              <strong>{stage.count}</strong>
              <span className="metric-caption">{stage.completed_reports} completed reports</span>
            </Link>
          ))}
        </div>
      </section>
      <QueryToolbar
        action="/funnel"
        search={search}
        searchPlaceholder="Ticker or company name"
        order={order}
        orderOptions={[...COMPANY_ORDER_OPTIONS]}
        perPage={perPage}
        resetHref="/funnel"
      >
        <label className="field-block">
          <span className="field-label">Stage</span>
          <select className="soft-input" name="stage_id" defaultValue={stageId}>
            <option value="">All Stages</option>
            {bootstrap.dashboard.stages.map((stage) => (
              <option value={stage.id} key={stage.id}>
                {stage.name}
              </option>
            ))}
          </select>
        </label>
      </QueryToolbar>
      <PaginationNav path="/funnel" params={{ search, stage_id: stageId, order }} page={page} perPage={perPage} total={payload.total} label="active companies" />
      <CompanyCollection companies={payload.companies} mode="funnel" emptyMessage="No active companies match the current funnel filters." />
    </>
  );
}
