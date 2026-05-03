import { PaginationNav, QueryToolbar, ReportCollection } from "../../components/native-route-surfaces";
import { SurfaceHeader } from "../../components/surface-header";
import { getBootstrap, getReports, getStages } from "../../lib/api";
import { legacyRoutePath } from "../../lib/legacy";
import { REPORT_ORDER_OPTIONS } from "../../lib/list-options";
import { buildQueryPath, parseBooleanParam, parseIntegerParam, parseStringParam, type SearchParamRecord } from "../../lib/query";

export default async function ReportsPage({ searchParams }: { searchParams: Promise<SearchParamRecord> }) {
  const params = await searchParams;
  const search = parseStringParam(params, "search");
  const stageId = parseStringParam(params, "stage_id");
  const result = parseStringParam(params, "result");
  const includeDrafts = parseBooleanParam(params, "include_drafts");
  const order = parseStringParam(params, "order", "completed_desc");
  const perPage = parseIntegerParam(params, "per_page", 50, { min: 1, max: 200 });
  const page = parseIntegerParam(params, "page", 1, { min: 1 });
  const [payload, stages, bootstrap] = await Promise.all([
    getReports(buildQueryPath("/api/reports", { search, stage_id: stageId, result, include_drafts: includeDrafts, order, per_page: perPage, page })),
    getStages(),
    getBootstrap(),
  ]);
  const resultOptions = includeDrafts
    ? [{ label: "All Results", value: "" }, { label: "Draft", value: "Draft" }, ...(bootstrap.report_actions || []).map((value) => ({ label: value, value }))]
    : [{ label: "All Results", value: "" }, ...(bootstrap.report_actions || []).map((value) => ({ label: value, value }))];

  return (
    <>
      <SurfaceHeader
        eyebrow="Cross-Company Research"
        title="Reports"
        description="Native cross-company report index backed by the preserved report summary list API. Stage/result filters, draft inclusion, ordering, pagination, and open-report flow stay URL-driven."
        legacyHref={legacyRoutePath("/reports")}
      />
      <QueryToolbar
        action="/reports"
        search={search}
        searchPlaceholder="Report title, company, or ticker"
        order={order}
        orderOptions={[...REPORT_ORDER_OPTIONS]}
        perPage={perPage}
        resetHref="/reports"
      >
        <label className="field-block">
          <span className="field-label">Stage</span>
          <select className="soft-input" name="stage_id" defaultValue={stageId}>
            <option value="">All Stages</option>
            {stages.stages.map((stage) => (
              <option value={stage.id} key={stage.id}>
                {stage.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field-block">
          <span className="field-label">Result</span>
          <select className="soft-input" name="result" defaultValue={result}>
            {resultOptions.map((option) => (
              <option value={option.value} key={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field-block checkbox-line toolbar-checkbox">
          <input type="checkbox" name="include_drafts" defaultChecked={includeDrafts} value="true" />
          <span>
            <span className="field-label">Include Drafts</span>
            <span className="muted">Keep draft reports visible and allow draft-only result filtering.</span>
          </span>
        </label>
      </QueryToolbar>
      <PaginationNav
        path="/reports"
        params={{ search, stage_id: stageId, result, include_drafts: includeDrafts, order }}
        page={page}
        perPage={perPage}
        total={payload.total}
        label="reports"
      />
      <ReportCollection reports={payload.reports} emptyMessage="No reports match the current filters." />
    </>
  );
}
