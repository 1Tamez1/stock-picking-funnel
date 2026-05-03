import type { DocumentRecord, SourceRecord } from "./types";

export const SOURCE_DURABILITY_STATES = ["ready", "limited", "pending", "link_only", "failed"] as const;

export type SourceDurabilityState = (typeof SOURCE_DURABILITY_STATES)[number];

export function sourceDurabilityStatus(source: SourceRecord): SourceDurabilityState {
  const raw = String(source.capture_state || source.reusability_status || (source.document_id ? source.normalized_status || "pending" : "link_only"));
  if (raw === "ready" || raw === "limited" || raw === "pending" || raw === "link_only" || raw === "failed") return raw;
  return source.document_id ? "pending" : "link_only";
}

export function sourceDurabilityTone(status: string): string {
  if (status === "ready") return "green";
  if (status === "limited" || status === "link_only" || status === "pending") return "amber";
  if (status === "failed") return "red";
  return "";
}

export function sourceDurabilityLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: "Ready",
    limited: "Limited",
    pending: "Pending",
    link_only: "Link Only",
    failed: "Failed",
  };
  return labels[status] || "Pending";
}

export function sourceDurabilityReason(source: SourceRecord): string {
  if (source.reusability_reason) return source.reusability_reason;
  const status = sourceDurabilityStatus(source);
  if (status === "ready") return "Snapshot and normalized view are available for reuse across later stages.";
  if (status === "limited") return "A stored artifact exists, but the normalized text or extract is limited and should be cross-checked.";
  if (status === "pending") return "A snapshot exists but normalized extraction is still processing.";
  if (status === "link_only") {
    return source.link_only_reason
      ? `Why link-only: ${source.link_only_reason}`
      : "The URL is saved without a durable snapshot yet. Upload an HTML, Markdown, text, CSV, spreadsheet, or other stored artifact.";
  }
  return source.capture_error || "Normalization or snapshot capture failed and this source does not count as durable evidence yet.";
}

export function sourceStageContext(source: SourceRecord): string {
  return [source.stage_name, source.report_title].filter(Boolean).join(" · ");
}

export function documentStatusTone(document: DocumentRecord): string {
  const status = String(document.normalized_status || "pending");
  if (status === "ready") return "green";
  if (status === "limited" || status === "pending") return "amber";
  if (status === "failed") return "red";
  return "";
}

export function documentStatusLabel(document: DocumentRecord): string {
  return document.normalized_format || String(document.normalized_status || "pending").replace(/_/g, " ");
}
