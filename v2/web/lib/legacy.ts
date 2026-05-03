function legacyUrl(params: URLSearchParams): string {
  return `/legacy/index.html?${params.toString()}`;
}

export function legacyRoutePath(path: string): string {
  return `/__legacy${path}`;
}

export function legacyViewSrc(view: string): string {
  const params = new URLSearchParams({
    embedded: "1",
    view,
  });
  return legacyUrl(params);
}

export function legacyCompanySrc(companyId: string): string {
  const params = new URLSearchParams({
    embedded: "1",
    company: companyId,
  });
  return legacyUrl(params);
}

export function legacyReportSrc(reportId: string): string {
  const params = new URLSearchParams({
    embedded: "1",
    report: reportId,
  });
  return legacyUrl(params);
}
