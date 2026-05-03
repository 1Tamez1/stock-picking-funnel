import { NativeTemplatesClient } from "../../components/native-templates-client";
import { SurfaceHeader } from "../../components/surface-header";
import { getStages, getTemplates } from "../../lib/api";
import { legacyRoutePath } from "../../lib/legacy";

export default async function TemplatesPage() {
  const [templates, stages] = await Promise.all([getTemplates(), getStages()]);
  return (
    <>
      <SurfaceHeader
        eyebrow="Editable Research Forms"
        title="Templates"
        description="Native template library and editor backed by the preserved template save/version logic. Future reports use the next active version; historical reports keep their pinned snapshot."
        legacyHref={legacyRoutePath("/templates")}
      />
      <NativeTemplatesClient initialTemplates={templates.templates} stages={stages.stages} />
    </>
  );
}
