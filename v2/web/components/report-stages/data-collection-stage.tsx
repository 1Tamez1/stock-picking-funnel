import { StageSurfaceLayout, anyTitle, titleEquals, type StageSurfaceDefinition, type StageSurfaceProps } from "./shared";

const definition: StageSurfaceDefinition = {
  componentKey: "data-collection-stage",
  label: "Data Collection",
  summary: "This stage is the source-packet and screening-handoff surface. Durable source coverage and LLM-readiness stay visible before screening work starts.",
  focusPoints: [
    "Keep durable evidence coverage explicit before moving into screening.",
    "Do not hide degraded URL-only or pending sources behind a generic upload success state.",
    "Preserve the screening handoff as a first-class stage artifact.",
  ],
  inheritedSource: () => null,
  groups: [
    {
      key: "framing",
      title: "Collection Scope",
      description: "Stage framing, basic inputs, and collection scope stay visible before any screening handoff is created.",
      test: anyTitle(titleEquals("Data Collection Template"), titleEquals("Basic Inputs"), titleEquals("Collection Scope")),
    },
    {
      key: "durability",
      title: "Source Durability And LLM Packet",
      description: "Durable source coverage and normalized-text readiness remain explicit at this stage.",
      test: anyTitle(titleEquals("Required Source Coverage"), titleEquals("Source Quality And Readiness"), titleEquals("LLM-Ready Packet")),
    },
    {
      key: "handoff",
      title: "Screening Handoff",
      description: "The native route keeps the forward handoff context visible instead of flattening it into generic fields.",
      test: titleEquals("Screening Handoff"),
    },
  ],
};

export function DataCollectionStageSurface(props: StageSurfaceProps) {
  return <StageSurfaceLayout {...props} definition={definition} />;
}
