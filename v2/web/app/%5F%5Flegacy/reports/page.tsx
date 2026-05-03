import { LegacyParityFrame } from "../../../components/legacy-parity-frame";
import { legacyViewSrc } from "../../../lib/legacy";

export default function LegacyReportsPage() {
  return (
    <LegacyParityFrame
      eyebrow="Legacy Fallback"
      title="Reports"
      description="Preserved legacy reports route for parity comparison and operator fallback."
      src={legacyViewSrc("reports")}
    />
  );
}
