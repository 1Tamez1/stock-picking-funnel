import fs from "node:fs";
import path from "node:path";

type ReportFixture = {
  id: number;
  title?: string;
  stage_key?: string;
  company_id?: number;
  company_name?: string;
  ticker?: string;
};

type CompanyFixture = {
  id: number;
  name?: string;
  ticker?: string;
};

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
    .slice(0, 80) || "item";
}

function loadFixtures() {
  const fixturePath = path.resolve(process.cwd(), "../contracts/fixtures/v1-parity-fixtures.json");
  return JSON.parse(fs.readFileSync(fixturePath, "utf8")) as {
    payloads?: {
      companies?: Record<string, CompanyFixture>;
      reports?: Record<string, ReportFixture>;
    };
    reference_samples?: {
      reports_by_stage?: Record<string, ReportFixture | null>;
    };
  };
}

export function companyRoute(company: CompanyFixture): string {
  return `/companies/${company.id}-${slugify(company.ticker || company.name || `company-${company.id}`)}`;
}

export function reportRoute(report: ReportFixture): string {
  return `/reports/${report.id}-${slugify(report.title || `report-${report.id}`)}`;
}

export function loadSampleCompanyRoute(): { route: string; company: CompanyFixture } {
  const fixtures = loadFixtures();
  const companies = Object.values(fixtures.payloads?.companies || {});
  const company = companies[0];
  if (!company) throw new Error("No sample company found in parity fixtures.");
  return { route: companyRoute(company), company };
}

export function loadStageReportRoutes(): Array<{ stageKey: string; route: string; legacyRoute: string; report: ReportFixture }> {
  const fixtures = loadFixtures();
  return Object.entries(fixtures.reference_samples?.reports_by_stage || {})
    .filter(([, report]) => Boolean(report))
    .map(([stageKey, report]) => {
      const liveReport = report as ReportFixture;
      const route = reportRoute(liveReport);
      return {
        stageKey,
        route,
        legacyRoute: `/__legacy${route}`,
        report: liveReport,
      };
    });
}

export function loadStageReportRoute(stageKey: string): { stageKey: string; route: string; legacyRoute: string; report: ReportFixture } {
  const match = loadStageReportRoutes().find((entry) => entry.stageKey === stageKey);
  if (!match) throw new Error(`No sample report found for stage ${stageKey}.`);
  return match;
}

export function loadPrimaryReportRoute(): { route: string; report: ReportFixture } {
  const stageRoutes = loadStageReportRoutes();
  const screening = stageRoutes.find((entry) => entry.stageKey === "screening");
  const selected = screening || stageRoutes[0];
  if (!selected) throw new Error("No sample report found in parity fixtures.");
  return { route: selected.route, report: selected.report };
}

export function legacyCompanyRoute(company: CompanyFixture): string {
  return `/__legacy${companyRoute(company)}`;
}
