import { LegacyParityFrame } from "../../../../components/legacy-parity-frame";
import { legacyCompanySrc } from "../../../../lib/legacy";
import { parseHandle } from "../../../../lib/routes";

export default async function LegacyCompanyPage({ params }: { params: Promise<{ companyHandle: string }> }) {
  const { companyHandle } = await params;
  const companyId = parseHandle(companyHandle);
  return (
    <LegacyParityFrame
      eyebrow="Legacy Fallback"
      title={`Company ${companyId}`}
      description="Preserved legacy company route for parity comparison and operator fallback."
      src={legacyCompanySrc(companyId)}
    />
  );
}
