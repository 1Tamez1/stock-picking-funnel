import { CompanyCollection, PaginationNav, QueryToolbar } from "../../components/native-route-surfaces";
import { SurfaceHeader } from "../../components/surface-header";
import { getCompanies } from "../../lib/api";
import { legacyRoutePath } from "../../lib/legacy";
import { COMPANY_ORDER_OPTIONS } from "../../lib/list-options";
import { buildQueryPath, parseIntegerParam, parseStringParam, type SearchParamRecord } from "../../lib/query";

export default async function ArchivePage({ searchParams }: { searchParams: Promise<SearchParamRecord> }) {
  const params = await searchParams;
  const search = parseStringParam(params, "search");
  const order = parseStringParam(params, "order", "updated_desc");
  const perPage = parseIntegerParam(params, "per_page", 50, { min: 1, max: 200 });
  const page = parseIntegerParam(params, "page", 1, { min: 1 });
  const payload = await getCompanies(buildQueryPath("/api/companies", { bucket: "archive", search, order, per_page: perPage, page }));

  return (
    <>
      <SurfaceHeader
        eyebrow="Rejected or Paused"
        title="Archive"
        description="Native archive page backed by the preserved archive list semantics. Archive red flags, saved summaries, and company-open flow stay routed without dropping backend authority."
        legacyHref={legacyRoutePath("/archive")}
      />
      <QueryToolbar
        action="/archive"
        search={search}
        searchPlaceholder="Ticker or company name"
        order={order}
        orderOptions={[...COMPANY_ORDER_OPTIONS]}
        perPage={perPage}
        resetHref="/archive"
      />
      <PaginationNav path="/archive" params={{ search, order }} page={page} perPage={perPage} total={payload.total} label="archived companies" />
      <CompanyCollection companies={payload.companies} mode="archive" emptyMessage="No archived companies match the current filters." />
    </>
  );
}
