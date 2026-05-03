import { LegacyParityFrame } from "../../../components/legacy-parity-frame";
import { legacyViewSrc } from "../../../lib/legacy";

export default function LegacyMonitoringPage() {
  return (
    <LegacyParityFrame
      eyebrow="Legacy Fallback"
      title="Monitoring"
      description="Preserved legacy monitoring route for parity comparison and operator fallback."
      src={legacyViewSrc("monitoring")}
    />
  );
}
