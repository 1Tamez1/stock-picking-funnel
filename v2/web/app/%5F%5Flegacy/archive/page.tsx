import { LegacyParityFrame } from "../../../components/legacy-parity-frame";
import { legacyViewSrc } from "../../../lib/legacy";

export default function LegacyArchivePage() {
  return (
    <LegacyParityFrame
      eyebrow="Legacy Fallback"
      title="Archive"
      description="Preserved legacy archive route for parity comparison and operator fallback."
      src={legacyViewSrc("archive")}
    />
  );
}
