export type SearchParamValue = string | string[] | undefined;
export type SearchParamRecord = Record<string, SearchParamValue>;

type QueryValue = string | number | boolean | null | undefined;

export function firstQueryValue(value: SearchParamValue): string {
  return Array.isArray(value) ? value[0] || "" : value || "";
}

export function parseStringParam(params: SearchParamRecord, key: string, fallback = ""): string {
  const value = firstQueryValue(params[key]).trim();
  return value || fallback;
}

export function parseIntegerParam(
  params: SearchParamRecord,
  key: string,
  fallback: number,
  { min = Number.MIN_SAFE_INTEGER, max = Number.MAX_SAFE_INTEGER }: { min?: number; max?: number } = {},
): number {
  const value = Number.parseInt(firstQueryValue(params[key]), 10);
  if (!Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}

export function parseBooleanParam(params: SearchParamRecord, key: string, fallback = false): boolean {
  const value = firstQueryValue(params[key]).toLowerCase();
  if (!value) return fallback;
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

export function buildQueryPath(path: string, query: Record<string, QueryValue>): string {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    if (typeof value === "boolean") {
      if (value) params.set(key, "true");
      return;
    }
    params.set(key, String(value));
  });
  const serialized = params.toString();
  return serialized ? `${path}?${serialized}` : path;
}
