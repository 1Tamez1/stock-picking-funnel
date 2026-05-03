import { LegacyParityFrame } from "../../../components/legacy-parity-frame";
import { legacyViewSrc } from "../../../lib/legacy";

export default function LegacyDashboardPage() {
  return (
    <LegacyParityFrame
      eyebrow="Legacy Fallback"
      title="Dashboard"
      description="Preserved legacy dashboard route for parity comparison and operator fallback."
      src={legacyViewSrc("dashboard")}
    />
  );
}
