import { StageSurfaceLayout, type StageSurfaceDefinition, type StageSurfaceProps } from "./shared";

const definition: StageSurfaceDefinition = {
  componentKey: "business-underwriting-stage",
  label: "Business Underwriting",
  summary: "This stage expands the screening thesis into moat, market-boundary, unit-economics, and reinvestment work while preserving the inherited screening handoff.",
  focusPoints: [
    "Inherited screening context remains visible and non-silent.",
    "Evidence-log workflow remains separate from the moat and economics sections.",
    "The pass/watchlist/archive routing sections remain explicit.",
  ],
  inheritedLabel: "Latest completed Screening report",
  inheritedSource: (report) => report.inherited_screening || report.workflow.latest_upstream_report,
  groups: [
    {
      key: "framing",
      title: "Framing, Inheritance, And Evidence",
      description: "Inherited screening context, delta thesis, and the evidence log stay visible before the moat and economics sections.",
      test: (section) =>
        section.title.includes("Business Underwriting Questionnaire")
        || section.title === "Core Rules"
        || section.title === "Inherited From Screening"
        || section.title.startsWith("Part I.")
        || section.title.startsWith("Part II.")
        || section.title === "1. Evidence Coverage Check"
        || section.title === "2. Evidence Log"
        || section.title === "3. Evidence Read",
    },
    {
      key: "analysis",
      title: "Business Quality, Unit Economics, And Industry Structure",
      description: "Market boundaries, moat sources, franchise tests, unit economics, reinvestment, and industry evolution stay grouped together.",
      test: (section) =>
        section.title.startsWith("Part III.")
        || section.title.startsWith("Part IV.")
        || section.title.startsWith("Part V.")
        || section.title.startsWith("Part VI.")
        || section.title.startsWith("Part VII.")
        || section.title.startsWith("Part VIII.")
        || section.title.startsWith("Part IX.")
        || section.title.startsWith("1. Market Boundary")
        || section.title.startsWith("2. Value Chain")
        || section.title.startsWith("1. Supply Advantage")
        || section.title.startsWith("2. Demand Advantage")
        || section.title.startsWith("3. Scale Advantage")
        || section.title.startsWith("4. Local Dominance")
        || section.title.startsWith("5. Overall Advantage Conclusion")
        || section.title.startsWith("1. Core Operating Statistics")
        || section.title.startsWith("2. Unit Economics"),
    },
    {
      key: "decision",
      title: "Verification And Decision Output",
      description: "Verification tasks, decision sections, and the business-underwriting conclusion stay preserved as explicit workflow output.",
      test: (section) =>
        section.title.startsWith("Part X.")
        || section.title.startsWith("Part XI.")
        || section.title.startsWith("Part XII.")
        || section.title === "Hard Gate Summary"
        || section.title === "Business Quality Summary"
        || section.title === "Final Decision"
        || section.title.startsWith("If It ")
        || section.title.startsWith("One-Page "),
    },
  ],
};

export function BusinessUnderwritingStageSurface(props: StageSurfaceProps) {
  return <StageSurfaceLayout {...props} definition={definition} />;
}
