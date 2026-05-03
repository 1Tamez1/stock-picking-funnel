import { StageSurfaceLayout, type StageSurfaceDefinition, type StageSurfaceProps } from "./shared";

const definition: StageSurfaceDefinition = {
  componentKey: "valuation-position-size-stage",
  label: "Valuation And Position Size",
  summary: "This stage preserves imported financial underwriting context, price ladders, margin-of-safety work, and position-size decisions without flattening them into generic schema rows.",
  focusPoints: [
    "Keep imported financial inputs and valuation-only adjustments separate.",
    "Preserve the price ladder, sensitivity, and boundary sections as visible workflow blocks.",
    "Retain execution/watchlist/return/archive routing sections on the native page.",
  ],
  inheritedLabel: "Latest completed Financial Underwriting report",
  inheritedSource: (report) => report.inherited_financial_underwriting || report.workflow.latest_upstream_report,
  groups: [
    {
      key: "framing",
      title: "Framing, Inheritance, And Method Selection",
      description: "Inherited financial context, valuation thesis, and method-selection work stay grouped together.",
      test: (section) =>
        section.title.includes("Valuation And Position Size Questionnaire")
        || section.title === "Core Rules"
        || section.title === "Evidence, Sources, And Confidence"
        || section.title === "Inherited From Financial Underwriting"
        || section.title.startsWith("Part I.")
        || section.title.startsWith("Part II.")
        || section.title.startsWith("Part III.")
        || section.title === "1. Value Drivers In Plain English"
        || section.title === "2. Method Selection Decision",
    },
    {
      key: "analysis",
      title: "Imported Economics, Price Ladder, Margin Of Safety, And Position Size",
      description: "Imported economics, valuation ladders, margin-of-safety work, downside mapping, and position-size decisions remain separated from the final routing block.",
      test: (section) =>
        section.title.startsWith("Part IV.")
        || section.title.startsWith("Part V.")
        || section.title.startsWith("Part VI.")
        || section.title.startsWith("Part VII.")
        || section.title.startsWith("Part VIII.")
        || section.title === "1. Imported Economics From Financial Underwriting"
        || section.title === "2. Valuation-Specific Adjustments Only"
        || section.title === "3. Key Assumption Register"
        || section.title === "4. Required Return And Discount Discipline"
        || section.title === "1. Primary Valuation Workup"
        || section.title === "2. Enterprise To Equity Bridge"
        || section.title === "3. Cross-Check Valuation Table"
        || section.title === "4. Conservative Worth And Price Ladder"
        || section.title === "1. Margin Of Safety Test"
        || section.title === "2. Range And Sensitivity Table"
        || section.title === "3. Market Expectations Check"
        || section.title === "4. No-Rerating Return Check"
        || section.title === "1. Permanent-Loss Scenarios"
        || section.title === "2. Time Risk, Liquidity, And Balance-Sheet Endurance"
        || section.title === "1. Sizing Inputs"
        || section.title === "2. Position Size Gate Table"
        || section.title === "3. Buy, Add, And No-Buy Boundaries"
        || section.title === "4. Concentration And Opportunity Cost",
    },
    {
      key: "decision",
      title: "Error Prevention, Valuation Standard, And Decision Output",
      description: "Munger checks, valuation standard selection, watchlist/archive/return sections, and the one-page conclusion remain explicit native sections.",
      test: (section) =>
        section.title.startsWith("Part IX.")
        || section.title.startsWith("Part X.")
        || section.title.startsWith("Part XI.")
        || section.title === "Category Options"
        || [
          "Exceptional Compounder",
          "Good Predictable Business",
          "Cyclical / Commodity / Asset-Heavy Business",
          "Financial / Insurer",
          "Special Situation",
          "Too Hard",
        ].includes(section.title)
        || section.title === "Hard Gate Summary"
        || section.title === "Quality Summary"
        || section.title === "Final Decision"
        || section.title.startsWith("If It ")
        || section.title.startsWith("One-Page "),
    },
  ],
};

export function ValuationPositionSizeStageSurface(props: StageSurfaceProps) {
  return <StageSurfaceLayout {...props} definition={definition} />;
}
