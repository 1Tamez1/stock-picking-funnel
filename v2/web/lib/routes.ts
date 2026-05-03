import type { Route } from "next";

import { legacyRoutePath } from "./legacy";

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "")
    .slice(0, 80) || "item";
}

export function companyHref(company: { id: number; public_id?: string; ticker?: string; name?: string }): Route {
  const handle = company.public_id || String(company.id);
  const label = company.ticker || company.name || `company-${company.id}`;
  return `/companies/${handle}-${slugify(label)}` as Route;
}

export function reportHref(report: { id: number; public_id?: string; title?: string }): Route {
  const handle = report.public_id || String(report.id);
  const label = report.title || `report-${report.id}`;
  return `/reports/${handle}-${slugify(label)}` as Route;
}

export function legacyCompanyHref(company: { id: number; public_id?: string; ticker?: string; name?: string }): Route {
  return legacyRoutePath(companyHref(company)) as Route;
}

export function legacyReportHref(report: { id: number; public_id?: string; title?: string }): Route {
  return legacyRoutePath(reportHref(report)) as Route;
}

export function parseHandle(value: string): string {
  return value.split("-", 1)[0] || value;
}
