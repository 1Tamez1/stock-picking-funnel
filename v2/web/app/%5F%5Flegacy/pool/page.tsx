import { LegacyParityFrame } from "../../../components/legacy-parity-frame";
import { legacyViewSrc } from "../../../lib/legacy";

export default function LegacyPoolPage() {
  return (
    <LegacyParityFrame
      eyebrow="Legacy Fallback"
      title="All Companies"
      description="Preserved legacy all-companies route for parity comparison and operator fallback."
      src={legacyViewSrc("pool")}
    />
  );
}
