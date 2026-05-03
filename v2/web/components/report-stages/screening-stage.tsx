import { StageSurfaceLayout, anyTitle, titleEquals, titleIncludes, type StageSurfaceDefinition, type StageSurfaceProps } from "./shared";

const definition: StageSurfaceDefinition = {
  componentKey: "screening-stage",
  label: "Screening",
  summary: "This stage decides whether the company advances, waits on watchlist, or is archived. Hard gates and decision routing stay separated from generic notes.",
  focusPoints: [
    "Show all hard gates and quality summaries before the final decision.",
    "Keep pass/watchlist/archive follow-up sections visible rather than folding them into one summary box.",
    "Keep the agent contract and completion blockers visible because screening is runbook-critical.",
  ],
  inheritedSource: (report) => report.workflow.latest_upstream_report,
  groups: [
    {
      key: "framing",
      title: "Framing, Rules, And Evidence",
      description: "Core rules, evidence expectations, and the desk-level framing stay grouped ahead of the hard gates.",
      test: anyTitle(
        titleIncludes("Screening Questionnaire"),
        titleEquals("Core Rules"),
        titleEquals("Evidence, Sources, And Confidence"),
        titleEquals("Basic Inputs"),
        titleEquals("Part I. Fast Kill Screen"),
        titleEquals("Part II. Screening Snapshot"),
        titleEquals("1. Business In Plain English"),
        titleEquals("2. Why Is This Stock On The Desk?"),
      ),
    },
    {
      key: "gates",
      title: "Hard Gates, Quality, And Financial Snapshot",
      description: "All screening gates, business-quality checks, economics, and valuation sanity checks remain explicit rather than compressed.",
      test: (section) =>
        section.title.startsWith("Part III.")
        || section.title.startsWith("Part IV.")
        || section.title.startsWith("Part V.")
        || section.title.startsWith("Part VI.")
        || section.title === "Moat Hypothesis",
    },
    {
      key: "verify",
      title: "Verification, Bias Audit, And Category Standard",
      description: "Verification tasks, Munger checks, and the next-underwriting standard remain on the main path.",
      test: (section) =>
        section.title.startsWith("Part VII.")
        || section.title.startsWith("Part VIII.")
        || section.title.startsWith("Part IX.")
        || section.title === "Category Options"
        || [
          "Exceptional Compounder",
          "Good Predictable Business",
          "Cyclical / Commodity / Asset-Heavy Business",
          "Financial / Insurer",
          "Special Situation",
          "Too Hard",
        ].includes(section.title),
    },
    {
      key: "decision",
      title: "Decision Output",
      description: "Final decision, pass/watchlist/archive follow-up sections, and the one-page conclusion remain first-class sections.",
      test: (section) =>
        section.title.startsWith("Part X.")
        || section.title === "Hard Gate Summary"
        || section.title === "Quality Summary"
        || section.title === "Final Decision"
        || section.title.startsWith("If It ")
        || section.title.startsWith("One-Page "),
    },
  ],
};

export function ScreeningStageSurface(props: StageSurfaceProps) {
  return <StageSurfaceLayout {...props} definition={definition} />;
}
