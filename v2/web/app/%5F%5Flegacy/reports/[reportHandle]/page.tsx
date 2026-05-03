import { LegacyParityFrame } from "../../../../components/legacy-parity-frame";
import { legacyReportSrc } from "../../../../lib/legacy";
import { parseHandle } from "../../../../lib/routes";

export default async function LegacyReportPage({ params }: { params: Promise<{ reportHandle: string }> }) {
  const { reportHandle } = await params;
  const reportId = parseHandle(reportHandle);
  return (
    <LegacyParityFrame
      eyebrow="Legacy Fallback"
      title={`Report ${reportId}`}
      description="Preserved legacy report route for parity comparison and operator fallback."
      src={legacyReportSrc(reportId)}
    />
  );
}
