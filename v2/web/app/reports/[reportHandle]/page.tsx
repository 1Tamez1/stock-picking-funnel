import Link from "next/link";

import { NativeReportClient } from "../../../components/native-report-client";
import { SurfaceHeader } from "../../../components/surface-header";
import { getReport } from "../../../lib/api";
import { companyHref, legacyReportHref, parseHandle } from "../../../lib/routes";

export default async function ReportPage({ params }: { params: Promise<{ reportHandle: string }> }) {
  const { reportHandle } = await params;
  const reportId = parseHandle(reportHandle);
  const payload = await getReport(reportId);
  return (
    <>
      <SurfaceHeader
        eyebrow="Report Workspace"
        title={payload.report.title}
        description="Native schema-driven report editor backed by the preserved compatibility API. Pinned template rendering, source/document workflows, completion preview, finalization, revision control, and inherited-field annotations remain server-authoritative."
        legacyHref={legacyReportHref(payload.report)}
        actions={
          <Link
            href={companyHref({ id: payload.report.company_id, ticker: payload.report.ticker, name: payload.report.company_name })}
            className="ghost-link"
          >
            Company Route
          </Link>
        }
      />
      <NativeReportClient initialReport={payload.report} />
    </>
  );
}
