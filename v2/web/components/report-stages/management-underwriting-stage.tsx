import { StageSurfaceLayout, type StageSurfaceDefinition, type StageSurfaceProps } from "./shared";

const definition: StageSurfaceDefinition = {
  componentKey: "management-underwriting-stage",
  label: "Management Underwriting",
  summary: "This stage preserves the business-underwriting handoff while exposing management evidence, capital allocation, governance, culture, and decision routing.",
  focusPoints: [
    "Keep inherited business context visible before management scoring begins.",
    "Do not compress capital-allocation and governance sections into one generic note area.",
    "Preserve management-category standards and routing sections.",
  ],
  inheritedLabel: "Latest completed Business Underwriting report",
  inheritedSource: (report) => report.inherited_business_underwriting || report.workflow.latest_upstream_report,
  groups: [
    {
      key: "framing",
      title: "Framing, Inheritance, And Management Evidence",
      description: "Inherited business-underwriting handoff, management evidence, and interaction logs remain grouped at the top.",
      test: (section) =>
        section.title.includes("Management Underwriting Questionnaire")
        || section.title === "Core Rules"
        || section.title === "Evidence, Sources, And Confidence"
        || section.title === "Inherited From Business Underwriting"
        || section.title.startsWith("Part I.")
        || section.title.startsWith("Part II.")
        || section.title.startsWith("Part III.")
        || section.title === "1. Evidence Coverage Check"
        || section.title === "2. Evidence Log"
        || section.title === "3. Interaction Read",
    },
    {
      key: "analysis",
      title: "Hard Gates, Capital Allocation, Incentives, And Culture",
      description: "All management-quality gates, capital allocation case file work, and governance/culture sections remain explicit.",
      test: (section) =>
        section.title.startsWith("Part IV.")
        || section.title.startsWith("Part V.")
        || section.title.startsWith("Part VI.")
        || section.title.startsWith("Part VII.")
        || section.title === "Management Hypothesis",
    },
    {
      key: "decision",
      title: "Verification, Category Standard, And Decision Output",
      description: "Verification, error-prevention checks, management category standards, and final routing remain native and visible.",
      test: (section) =>
        section.title.startsWith("Part VIII.")
        || section.title.startsWith("Part IX.")
        || section.title.startsWith("Part X.")
        || section.title.startsWith("Part XI.")
        || section.title === "Category Options"
        || [
          "Exceptional Owner-Operators",
          "Rational Stewards",
          "Capable But Agency-Risky",
          "Promotional / Empire-Building",
          "Control / Governance Risk",
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

export function ManagementUnderwritingStageSurface(props: StageSurfaceProps) {
  return <StageSurfaceLayout {...props} definition={definition} />;
}
