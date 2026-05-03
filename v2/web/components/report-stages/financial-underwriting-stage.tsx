import { StageSurfaceLayout, type StageSurfaceDefinition, type StageSurfaceProps } from "./shared";

const definition: StageSurfaceDefinition = {
  componentKey: "financial-underwriting-stage",
  label: "Financial Underwriting",
  summary: "This stage keeps accounting reality, owner earnings, normalization, and red-flag work visible before valuation can begin.",
  focusPoints: [
    "Preserve the management handoff before financial worksheets are edited.",
    "Keep hard financial gates separate from worksheets and red-flag logging.",
    "Retain return/watchlist/archive routing sections as explicit workflow output.",
  ],
  inheritedLabel: "Latest completed Management Underwriting report",
  inheritedSource: (report) => report.inherited_management_underwriting || report.workflow.latest_upstream_report,
  groups: [
    {
      key: "framing",
      title: "Framing, Inheritance, And Snapshot",
      description: "Inherited management context, the fast kill screen, and the initial financial snapshot remain grouped at the front.",
      test: (section) =>
        section.title.includes("Financial Underwriting Questionnaire")
        || section.title === "Core Rules"
        || section.title === "Evidence, Sources, And Confidence"
        || section.title === "Inherited From Management Underwriting"
        || section.title === "Basic Inputs"
        || section.title.startsWith("Part I.")
        || section.title.startsWith("Part II.")
        || section.title.startsWith("Part III.")
        || section.title === "1. Economics In Plain Numbers"
        || section.title === "2. Why Does This Need Financial Underwriting?",
    },
    {
      key: "analysis",
      title: "Hard Financial Gates And Core Worksheets",
      description: "Accounting reality, owner earnings, returns, balance sheet stress, and normalization work stay in their own native cluster.",
      test: (section) =>
        section.title.startsWith("Part IV.")
        || section.title.startsWith("Part V.")
        || section.title.startsWith("Part VI.")
        || section.title === "1. Multi-Year Financial Read"
        || section.title === "2. Owner Earnings Worksheet"
        || section.title === "3. Returns, Incremental Capital, And Margin Bridge"
        || section.title === "4. Cash Conversion And Working Capital"
        || section.title === "5. Balance Sheet Stress Snapshot"
        || section.title === "6. Per-Share Value Creation And Retained-Capital Test"
        || section.title === "7. Normalization Bridge",
    },
    {
      key: "decision",
      title: "Red Flags, Verification, Category Standard, And Decision Output",
      description: "Accounting red flags, verification, valuation-standard selection, and decision routing remain visible on the main report surface.",
      test: (section) =>
        section.title.startsWith("Part VII.")
        || section.title.startsWith("Part VIII.")
        || section.title.startsWith("Part IX.")
        || section.title.startsWith("Part X.")
        || section.title.startsWith("Part XI.")
        || section.title === "Category Options"
        || [
          "Asset-Light Compounder",
          "Good Predictable Business",
          "Asset-Heavy / Reinvestment-Heavy Business",
          "Cyclical / Commodity / Balance-Sheet-Sensitive Business",
          "Financial / Insurer",
          "Roll-Up / Serial Acquirer",
          "Fragile / Promotional / Over-Leveraged",
        ].includes(section.title)
        || section.title === "Hard Gate Summary"
        || section.title === "Quality Summary"
        || section.title === "Final Decision"
        || section.title.startsWith("If It ")
        || section.title.startsWith("One-Page "),
    },
  ],
};

export function FinancialUnderwritingStageSurface(props: StageSurfaceProps) {
  return <StageSurfaceLayout {...props} definition={definition} />;
}
