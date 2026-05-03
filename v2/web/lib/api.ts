import type {
  BootstrapPayload,
  CompaniesPayload,
  CompanyPayload,
  DocumentsPayload,
  SessionPayload,
  MonitoringPayload,
  MonitoringRulePayload,
  PreviewPayload,
  ReportPayload,
  ReportsPayload,
  ReportSectionPayload,
  ReportSectionsPayload,
  SaveReportPayload,
  SourcePayload,
  StagesPayload,
  TemplatePayload,
  TemplatesPayload,
} from "./types";

const API_BASE =
  process.env.FUNNEL_V2_API_BASE_URL ||
  process.env.FUNNEL_V2_API_PROXY_TARGET ||
  "http://127.0.0.1:8211";

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

function resolveUrl(path: string): string {
  return typeof window === "undefined" ? `${API_BASE}${path}` : path;
}

async function serverCookieHeader(): Promise<string> {
  if (typeof window !== "undefined") return "";
  const mod = await import("next/headers");
  const store = await mod.cookies();
  return store
    .getAll()
    .map((item) => `${item.name}=${item.value}`)
    .join("; ");
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as unknown;
  }
  return await response.text();
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const cookieHeader = await serverCookieHeader();
  const headers =
    init.body instanceof FormData
      ? init.headers
      : {
          "Content-Type": "application/json",
          ...(init.headers || {}),
        };
  const response = await fetch(resolveUrl(path), {
    ...init,
    headers,
    credentials: "include",
    ...(cookieHeader ? { headers: { ...(headers || {}), Cookie: cookieHeader } } : {}),
    cache: init.cache ?? "no-store",
  });
  const payload = await parseResponseBody(response);
  if (!response.ok) {
    if (response.status === 401) {
      if (typeof window !== "undefined") {
        window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}&expired=1`);
      } else {
        const navigation = await import("next/navigation");
        navigation.redirect("/login?expired=1" as never);
      }
    }
    const message =
      typeof payload === "object" && payload !== null && "error" in payload && typeof payload.error === "string"
        ? payload.error
        : `Request failed for ${path}: ${response.status}`;
    throw new ApiError(message, response.status, payload);
  }
  return payload as T;
}

export function getBootstrap() {
  return request<BootstrapPayload>("/api/bootstrap");
}

export function getSession() {
  return request<SessionPayload>("/api/session");
}

export function loginSession(payload: { email: string; password: string }) {
  return request<SessionPayload>("/api/session/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function logoutSession() {
  return request<{ ok: boolean }>("/api/session/logout", {
    method: "POST",
  });
}

export function getStages() {
  return request<StagesPayload>("/api/stages");
}

export function getCompanies(path = "/api/companies?per_page=50") {
  return request<CompaniesPayload>(path);
}

export function getCompany(companyId: string | number) {
  return request<CompanyPayload>(`/api/companies/${companyId}`);
}

export function createCompany(payload: Record<string, FormDataEntryValue | string>) {
  return request<CompanyPayload>("/api/companies", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getReports(path = "/api/reports?per_page=50") {
  return request<ReportsPayload>(path);
}

export function getReport(reportId: string | number) {
  return request<ReportPayload>(`/api/reports/${reportId}`);
}

export function getReportSections(reportId: string | number) {
  return request<ReportSectionsPayload>(`/api/reports/${reportId}/sections`);
}

export function getReportSection(reportId: string | number, sectionId: string) {
  return request<ReportSectionPayload>(`/api/reports/${reportId}/sections/${sectionId}`);
}

export function previewReportSection(reportId: number, sectionId: string, payload: Record<string, unknown>) {
  return request<ReportSectionPayload>(`/api/reports/${reportId}/sections/${sectionId}/preview`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateReportSection(reportId: number, sectionId: string, payload: Record<string, unknown>) {
  return request<ReportSectionPayload>(`/api/reports/${reportId}/sections/${sectionId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function createReport(payload: Record<string, FormDataEntryValue | string | number>) {
  return request<ReportPayload>("/api/reports", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function previewReport(reportId: number, payload: SaveReportPayload) {
  return request<PreviewPayload>(`/api/reports/${reportId}/preview`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateReport(reportId: number, payload: SaveReportPayload) {
  return request<ReportPayload>(`/api/reports/${reportId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteReport(reportId: number) {
  return request<CompanyPayload>(`/api/reports/${reportId}`, {
    method: "DELETE",
  });
}

export function getMonitoring() {
  return request<MonitoringPayload>("/api/monitoring");
}

export function updateMonitoringRule(ruleId: number, payload: Record<string, FormDataEntryValue | string>) {
  return request<MonitoringRulePayload>(`/api/monitoring-rules/${ruleId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getTemplates() {
  return request<TemplatesPayload>("/api/templates");
}

export function getTemplate(templateId: number) {
  return request<TemplatePayload>(`/api/templates/${templateId}`);
}

export function saveTemplate(templateId: number | null, payload: Record<string, FormDataEntryValue | string>) {
  return request<TemplatePayload>(templateId ? `/api/templates/${templateId}` : "/api/templates", {
    method: templateId ? "PATCH" : "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteTemplate(templateId: number) {
  return request<{ ok: boolean }>(`/api/templates/${templateId}`, {
    method: "DELETE",
  });
}

export function uploadDocuments(formData: FormData) {
  return request<DocumentsPayload>("/api/documents", {
    method: "POST",
    body: formData,
  });
}

export function createReportSource(formData: FormData) {
  return request<SourcePayload>("/api/report-sources", {
    method: "POST",
    body: formData,
  });
}

export function updateReportSource(sourceId: number, formData: FormData) {
  return request<SourcePayload>(`/api/report-sources/${sourceId}`, {
    method: "PATCH",
    body: formData,
  });
}

export function deleteReportSource(sourceId: number) {
  return request<{ ok: boolean }>(`/api/report-sources/${sourceId}`, {
    method: "DELETE",
  });
}
