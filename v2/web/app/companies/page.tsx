import { NativeCompanyCreateForm } from "../../components/native-company-create-form";
import { CompanyCollection, PaginationNav, QueryToolbar } from "../../components/native-route-surfaces";
import { PageHeader } from "../../components/page-header";
import { getCompanies } from "../../lib/api";
import { COMPANY_BUCKET_OPTIONS, COMPANY_ORDER_OPTIONS } from "../../lib/list-options";
import { buildQueryPath, parseIntegerParam, parseStringParam, type SearchParamRecord } from "../../lib/query";

export default async function CompaniesPage({ searchParams }: { searchParams: Promise<SearchParamRecord> }) {
  const params = await searchParams;
  const search = parseStringParam(params, "search");
  const bucket = parseStringParam(params, "bucket");
  const order = parseStringParam(params, "order", "updated_desc");
  const perPage = parseIntegerParam(params, "per_page", 50, { min: 1, max: 200 });
  const page = parseIntegerParam(params, "page", 1, { min: 1 });
  const payload = await getCompanies(buildQueryPath("/api/companies", { search, bucket, order, per_page: perPage, page }));

  return (
    <>
      <PageHeader
        eyebrow="Research Universe"
        title="Companies"
        description="Canonical native company index. It shares the preserved company list semantics with the compatibility backend while keeping a routed company directory separate from the bucket pages."
      />
      <NativeCompanyCreateForm />
      <QueryToolbar
        action="/companies"
        search={search}
        searchPlaceholder="Ticker or company name"
        order={order}
        orderOptions={[...COMPANY_ORDER_OPTIONS]}
        perPage={perPage}
        resetHref="/companies"
      >
        <label className="field-block">
          <span className="field-label">Status</span>
          <select className="soft-input" name="bucket" defaultValue={bucket}>
            {COMPANY_BUCKET_OPTIONS.map((option) => (
              <option value={option.value} key={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </QueryToolbar>
      <PaginationNav path="/companies" params={{ search, bucket, order }} page={page} perPage={perPage} total={payload.total} label="companies" />
      <CompanyCollection companies={payload.companies} mode="pool" emptyMessage="No companies match the current filters." />
    </>
  );
}
