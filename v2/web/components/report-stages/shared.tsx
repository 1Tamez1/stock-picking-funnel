import { Fragment, type ReactNode } from "react";

import type { ReportRecord, TemplateSection, UpstreamReportReference } from "../../lib/types";

export type SectionMatcher = {
  key: string;
  title: string;
  description: string;
  test: (section: TemplateSection) => boolean;
};

export type StageSurfaceDefinition = {
  componentKey: string;
  label: string;
  summary: string;
  focusPoints: string[];
  inheritedLabel?: string;
  inheritedSource: (report: ReportRecord) => UpstreamReportReference | null | undefined;
  groups: SectionMatcher[];
};

export type StageSurfaceProps = {
  report: ReportRecord;
  renderSection: (section: TemplateSection) => ReactNode;
};

export function titleStartsWith(prefix: string) {
  return (section: TemplateSection) => section.title.startsWith(prefix);
}

export function titleEquals(value: string) {
  return (section: TemplateSection) => section.title === value;
}

export function titleIncludes(value: string) {
  return (section: TemplateSection) => section.title.includes(value);
}

export function anyTitle(...tests: Array<(section: TemplateSection) => boolean>) {
  return (section: TemplateSection) => tests.some((test) => test(section));
}

function groupSections(sections: TemplateSection[], groups: SectionMatcher[]) {
  const used = new Set<string>();
  const grouped = groups
    .map((group) => {
      const matched = sections.filter((section) => !used.has(section.id) && group.test(section));
      matched.forEach((section) => used.add(section.id));
      return { ...group, sections: matched };
    })
    .filter((group) => group.sections.length);
  const remaining = sections.filter((section) => !used.has(section.id));
  if (remaining.length) {
    grouped.push({
      key: "remaining",
      title: "Remaining Stage Sections",
      description: "These sections remain live in the schema and stay editable, even if they do not fit a named native cluster yet.",
      test: () => true,
      sections: remaining,
    });
  }
  return grouped;
}

export function StageSurfaceLayout({
  report,
  renderSection,
  definition,
}: StageSurfaceProps & {
  definition: StageSurfaceDefinition;
}) {
  const groups = groupSections(report.template.schema.sections, definition.groups);

  return (
    <div className="stack-gap" data-stage-component={definition.componentKey} data-stage-root={report.stage_key}>
      {groups.map((group) => (
        <Fragment key={`${report.stage_key}-${group.key}`}>
          {group.sections.map((section) => renderSection(section))}
        </Fragment>
      ))}
    </div>
  );
}
