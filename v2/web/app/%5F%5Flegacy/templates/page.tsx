import { LegacyParityFrame } from "../../../components/legacy-parity-frame";
import { legacyViewSrc } from "../../../lib/legacy";

export default function LegacyTemplatesPage() {
  return (
    <LegacyParityFrame
      eyebrow="Legacy Fallback"
      title="Templates"
      description="Preserved legacy templates route for parity comparison and operator fallback."
      src={legacyViewSrc("templates")}
    />
  );
}
