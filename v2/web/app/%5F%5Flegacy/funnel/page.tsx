import { LegacyParityFrame } from "../../../components/legacy-parity-frame";
import { legacyViewSrc } from "../../../lib/legacy";

export default function LegacyFunnelPage() {
  return (
    <LegacyParityFrame
      eyebrow="Legacy Fallback"
      title="Funnel"
      description="Preserved legacy funnel route for parity comparison and operator fallback."
      src={legacyViewSrc("funnel")}
    />
  );
}
