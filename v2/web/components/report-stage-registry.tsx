import type { ReactNode } from "react";

import { BusinessUnderwritingStageSurface } from "./report-stages/business-underwriting-stage";
import { DataCollectionStageSurface } from "./report-stages/data-collection-stage";
import { ExecutionRulesStageSurface } from "./report-stages/execution-rules-stage";
import { FinancialUnderwritingStageSurface } from "./report-stages/financial-underwriting-stage";
import { ManagementUnderwritingStageSurface } from "./report-stages/management-underwriting-stage";
import { ScreeningStageSurface } from "./report-stages/screening-stage";
import { StageSurfaceLayout, type StageSurfaceProps } from "./report-stages/shared";
import { ValuationPositionSizeStageSurface } from "./report-stages/valuation-position-size-stage";
import type { ReportRecord, TemplateSection } from "../lib/types";

export const STAGE_RENDERER_KEYS = [
  "data_collection",
  "screening",
  "business_underwriting",
  "management_underwriting",
  "financial_underwriting",
  "valuation_position_size",
  "execution_rules",
] as const;

export type StageRendererKey = (typeof STAGE_RENDERER_KEYS)[number];

type StageSurfaceRenderer = (props: StageSurfaceProps) => ReactNode;

const STAGE_RENDERER_COMPONENTS: Record<StageRendererKey, StageSurfaceRenderer> = {
  data_collection: DataCollectionStageSurface,
  screening: ScreeningStageSurface,
  business_underwriting: BusinessUnderwritingStageSurface,
  management_underwriting: ManagementUnderwritingStageSurface,
  financial_underwriting: FinancialUnderwritingStageSurface,
  valuation_position_size: ValuationPositionSizeStageSurface,
  execution_rules: ExecutionRulesStageSurface,
};

function GenericFallbackStageSurface(props: StageSurfaceProps) {
  return (
    <StageSurfaceLayout
      {...props}
      definition={{
        componentKey: "generic-stage-fallback",
        label: props.report.stage_name,
        summary: "This stage remains backed by the preserved compatibility payload.",
        focusPoints: [],
        inheritedSource: (report) => report.workflow.latest_upstream_report,
        groups: [],
      }}
    />
  );
}

export function renderReportStageSurface({
  report,
  renderSection,
}: {
  report: ReportRecord;
  renderSection: (section: TemplateSection) => ReactNode;
}): ReactNode {
  const renderer = STAGE_RENDERER_COMPONENTS[(report.stage_key as StageRendererKey) || "screening"] || GenericFallbackStageSurface;
  return renderer({ report, renderSection });
}
