import { CompanyCollection, PaginationNav, QueryToolbar } from "../../components/native-route-surfaces";
import { SurfaceHeader } from "../../components/surface-header";
import { getCompanies } from "../../lib/api";
import { legacyRoutePath } from "../../lib/legacy";
import { COMPANY_ORDER_OPTIONS } from "../../lib/list-options";
import { buildQueryPath, parseIntegerParam, parseStringParam, type SearchParamRecord } from "../../lib/query";

export default async function WatchlistPage({ searchParams }: { searchParams: Promise<SearchParamRecord> }) {
  const params = await searchParams;
  const search = parseStringParam(params, "search");
  const order = parseStringParam(params, "order", "review_date_asc");
  const perPage = parseIntegerParam(params, "per_page", 50, { min: 1, max: 200 });
  const page = parseIntegerParam(params, "page", 1, { min: 1 });
  const payload = await getCompanies(buildQueryPath("/api/companies", { bucket: "watchlist", search, order, per_page: perPage, page }));

  return (
    <>
      <SurfaceHeader
        eyebrow="Deferred Candidates"
        title="Watchlist"
        description="Native watchlist backed by the preserved watchlist company list semantics. Review dates, watchlist conditions, and objective monitoring rule summaries stay visible on the routed page."
        legacyHref={legacyRoutePath("/watchlist")}
      />
      <QueryToolbar
        action="/watchlist"
        search={search}
        searchPlaceholder="Ticker or company name"
        order={order}
        orderOptions={[...COMPANY_ORDER_OPTIONS]}
        perPage={perPage}
        resetHref="/watchlist"
      />
      <PaginationNav path="/watchlist" params={{ search, order }} page={page} perPage={perPage} total={payload.total} label="watchlist companies" />
      <CompanyCollection companies={payload.companies} mode="watchlist" emptyMessage="No watchlist companies match the current filters." />
    </>
  );
}
