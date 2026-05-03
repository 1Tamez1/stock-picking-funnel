import { StageSurfaceLayout, type StageSurfaceDefinition, type StageSurfaceProps } from "./shared";

const definition: StageSurfaceDefinition = {
  componentKey: "execution-rules-stage",
  label: "Execution Rules",
  summary: "This stage keeps the valuation handoff, entry/add/hold/trim/exit logic, and monitoring triggers explicit on the primary native route.",
  focusPoints: [
    "Preserve the valuation handoff before execution-specific rules are edited.",
    "Keep trade-management and monitoring-trigger sections separate from the final decision output.",
    "Do not hide return-to-underwriting logic behind a generic final result field.",
  ],
  inheritedLabel: "Latest completed Valuation And Position Size report",
  inheritedSource: (report) => report.inherited_valuation_position_size || report.workflow.latest_upstream_report,
  groups: [
    {
      key: "framing",
      title: "Framing, Valuation Handoff, And Company Snapshot",
      description: "Execution keeps the valuation handoff and complete company snapshot visible before entry or trim/exit rules are edited.",
      test: (section) =>
        section.title.includes("Execution Rules Questionnaire")
        || section.title === "Core Rules"
        || section.title === "Evidence, Sources, And Confidence"
        || section.title.startsWith("Part I.")
        || section.title.startsWith("Part II.")
        || section.title === "1. Master Snapshot Table"
        || section.title === "2. One-Paragraph Investment Summary"
        || section.title === "3. Business Snapshot"
        || section.title === "4. Management Snapshot"
        || section.title === "5. Financial Snapshot"
        || section.title === "6. Valuation Snapshot"
        || section.title === "7. Position, Portfolio, And Liquidity Snapshot"
        || section.title === "8. Snapshot Completeness Check",
    },
    {
      key: "rules",
      title: "Entry, Add, Hold, Trim, Exit, And Trigger Rules",
      description: "Execution triggers and trade-management rules remain broken out instead of being collapsed into one generic summary block.",
      test: (section) =>
        section.title.startsWith("Part III.")
        || section.title.startsWith("Part IV.")
        || section.title.startsWith("Part V.")
        || section.title.startsWith("Part VI.")
        || section.title.startsWith("Part VII.")
        || section.title.startsWith("1. Buy Zone Design")
        || section.title.startsWith("2. Order Construction")
        || section.title.startsWith("3. Conditions To Initiate")
        || section.title.startsWith("1. Adds On Weakness")
        || section.title.startsWith("2. Adds On Strength")
        || section.title.startsWith("3. Scale To Full Weight")
        || section.title.startsWith("1. Hold Rules")
        || section.title.startsWith("2. Trim Rules")
        || section.title.startsWith("3. Full Exit Rules")
        || section.title.startsWith("4. Sell-Discipline Recheck")
        || section.title.startsWith("1. Trigger Table")
        || section.title.startsWith("2. Business Triggers")
        || section.title.startsWith("3. Management Triggers")
        || section.title.startsWith("4. Financial Triggers")
        || section.title.startsWith("5. Valuation And Price Triggers")
        || section.title.startsWith("6. Monitoring Cadence"),
    },
    {
      key: "decision",
      title: "Portfolio Interaction, Error Prevention, Pattern Standard, And Decision Output",
      description: "Portfolio interaction, execution-pattern standards, and all final routing outcomes remain native and explicit.",
      test: (section) =>
        section.title.startsWith("Part VIII.")
        || section.title.startsWith("Part IX.")
        || section.title.startsWith("Part X.")
        || section.title.startsWith("Part XI.")
        || section.title === "Category Options"
        || [
          "Immediate Starter",
          "Staged Accumulation",
          "Hold Existing / No Fresh Buying",
          "Watchlist Only",
          "Trim / Harvest",
          "Exit / Broken Thesis",
          "Too Hard To Execute",
        ].includes(section.title)
        || section.title === "Hard Gate Summary"
        || section.title === "Quality Summary"
        || section.title === "Final Decision"
        || section.title.startsWith("If It ")
        || section.title.startsWith("One-Page "),
    },
  ],
};

export function ExecutionRulesStageSurface(props: StageSurfaceProps) {
  return <StageSurfaceLayout {...props} definition={definition} />;
}
