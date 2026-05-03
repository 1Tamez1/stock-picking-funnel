import Link from "next/link";

import { NativeCompanyClient } from "../../../components/native-company-client";
import { SurfaceHeader } from "../../../components/surface-header";
import { getCompany, getStages } from "../../../lib/api";
import { legacyCompanyHref } from "../../../lib/routes";
import { parseHandle } from "../../../lib/routes";

export default async function CompanyPage({ params }: { params: Promise<{ companyHandle: string }> }) {
  const { companyHandle } = await params;
  const companyId = parseHandle(companyHandle);
  const [companyPayload, stagesPayload] = await Promise.all([getCompany(companyId), getStages()]);
  return (
    <>
      <SurfaceHeader
        eyebrow="Company Page"
        title={`${companyPayload.company.ticker} Research`}
        description="Native company detail backed by the preserved compatibility API. Report creation, company documents, company sources, monitoring updates, and company-to-report routing all remain on the established execution path."
        legacyHref={legacyCompanyHref(companyPayload.company)}
        actions={
          <Link href="/companies" className="ghost-link">
            Companies Index
          </Link>
        }
      />
      <NativeCompanyClient initialCompany={companyPayload.company} stages={stagesPayload.stages} />
    </>
  );
}
