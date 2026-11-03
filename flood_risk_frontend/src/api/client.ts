/**
 * The single API client module. Every backend call goes through `request()`.
 * Base URL: VITE_API_BASE_URL (see .env.example), default http://127.0.0.1:8000.
 */
import type {
  Assessment,
  District,
  RecentRainfallResponse,
  FloodImpactRecord,
  FloodImpactResult,
  ModelMetadata,
  ModelMetadataResult,
  MLExperimentSummary,
  ScenarioRequest,
  WindowsResponse,
} from "./types";

export const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

export function apiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL;
  return (raw && raw.trim() ? raw.trim() : DEFAULT_API_BASE_URL).replace(/\/+$/, "");
}

/**
 * kind "network": the backend could not be reached (not running, wrong URL, CORS).
 * kind "http":    the backend answered with a non-2xx status; `detail` is its message.
 */
export class ApiError extends Error {
  readonly kind: "network" | "http";
  readonly status: number | null;
  readonly detail: string;

  constructor(kind: "network" | "http", status: number | null, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

/** FastAPI errors: {detail: string} or {detail: [{loc, msg, ...}]} (422). */
function detailFrom(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      const msgs = d
        .map((e) => (e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : null))
        .filter(Boolean);
      if (msgs.length) return msgs.join("; ");
    }
  }
  return fallback;
}

type Query = Record<string, string | number | null | undefined>;

async function request<T>(path: string, opts: { query?: Query; method?: "GET" | "POST"; body?: unknown } = {}): Promise<T> {
  const url = new URL(apiBaseUrl() + path);
  for (const [k, v] of Object.entries(opts.query ?? {})) {
    if (v !== null && v !== undefined && v !== "") url.searchParams.set(k, String(v));
  }
  let res: Response;
  try {
    res = await fetch(url.toString(), {
      method: opts.method ?? "GET",
      headers: opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    throw new ApiError("network", null, e instanceof Error ? e.message : "Network error");
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    throw new ApiError("http", res.status, detailFrom(body, `Backend returned HTTP ${res.status}`));
  }
  return body as T;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  mlExperiment: () => request<MLExperimentSummary>("/ml-experiment/summary"),
  windows: () => request<WindowsResponse>("/windows"),
  districts: () => request<District[]>("/districts"),
  /** 404 when nothing is computed for that window/date. Omit `date` for the latest. */
  assessments: (windowDays: number, date?: string | null) =>
    request<Assessment[]>("/assessments", { query: { window_days: windowDays, date } }),
  districtAssessment: (districtId: number, windowDays: number, date?: string | null) =>
    request<Assessment>(`/districts/${districtId}/assessment`, { query: { window_days: windowDays, date } }),
  history: (districtId: number, windowDays: number, start?: string | null, end?: string | null) =>
    request<Assessment[]>(`/districts/${districtId}/history`, { query: { window_days: windowDays, start, end } }),
  /**
   * PROPOSED endpoint. A 404/405/501 means "this backend does not provide yearly flood labels":
   * a normal state, returned as {kind:"unavailable"}. Other errors throw.
   */
  async floodImpact(districtId: number): Promise<FloodImpactResult> {
    try {
      const body = await request<unknown>(`/districts/${districtId}/flood-impact`);
      return { kind: "ok", records: Array.isArray(body) ? (body as FloodImpactRecord[]) : [] };
    } catch (e) {
      if (e instanceof ApiError && e.kind === "http" && [404, 405, 501].includes(e.status ?? 0)) {
        return { kind: "unavailable", detail: e.detail };
      }
      throw e;
    }
  },
  recentRainfall: (limit = 10000) =>
    request<RecentRainfallResponse>("/rainfall/recent", { query: { limit } }),
  scenario: (body: ScenarioRequest) => request<Assessment>("/assess", { method: "POST", body }),
  /** 503 (model not trained) is a normal state, returned as {kind:"untrained"}. Other errors throw. */
  async modelMetadata(): Promise<ModelMetadataResult> {
    try {
      const data = await request<ModelMetadata>("/model/metadata");
      return { kind: "ok", data };
    } catch (e) {
      if (e instanceof ApiError && e.kind === "http" && e.status === 503) {
        return { kind: "untrained", detail: e.detail };
      }
      throw e;
    }
  },
};

export type Api = typeof api;
