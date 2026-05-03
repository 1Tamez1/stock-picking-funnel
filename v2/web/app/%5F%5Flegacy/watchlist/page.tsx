import { LegacyParityFrame } from "../../../components/legacy-parity-frame";
import { legacyViewSrc } from "../../../lib/legacy";

export default function LegacyWatchlistPage() {
  return (
    <LegacyParityFrame
      eyebrow="Legacy Fallback"
      title="Watchlist"
      description="Preserved legacy watchlist route for parity comparison and operator fallback."
      src={legacyViewSrc("watchlist")}
    />
  );
}
