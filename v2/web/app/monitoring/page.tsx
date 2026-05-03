import { NativeMonitoringClient } from "../../components/native-monitoring-client";
import { SurfaceHeader } from "../../components/surface-header";
import { getMonitoring } from "../../lib/api";
import { legacyRoutePath } from "../../lib/legacy";

export default async function MonitoringPage() {
  const payload = await getMonitoring();
  return (
    <>
      <SurfaceHeader
        eyebrow="Rules and Alerts"
        title="Monitoring"
        description="Native runtime rule editor backed by the preserved compatibility API. Trigger state, report-owned rule structure, and alert semantics remain server-authoritative."
        legacyHref={legacyRoutePath("/monitoring")}
      />
      <NativeMonitoringClient initialRules={payload.rules} />
    </>
  );
}
