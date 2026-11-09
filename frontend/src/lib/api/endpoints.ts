import { request, requestBlob } from "@/lib/api/client";
import type {
  AlertOut,
  AlertStatus,
  DailySummaryOut,
  EventOut,
  HealthReady,
  HourlyPointOut,
  ImportBatchOut,
  MeOut,
  Page,
  SiteOut,
  SiteSettingsOut,
  SnapshotItem,
  TokenOut,
} from "@/lib/api/types";

export const api = {
  login: (username: string, password: string) =>
    request<TokenOut>("/auth/login", { method: "POST", body: { username, password }, auth: false }),
  me: () => request<MeOut>("/auth/me"),
  healthReady: (signal?: AbortSignal) =>
    request<HealthReady>("/health/ready", { auth: false, signal }),

  listSites: () => request<SiteOut[]>("/sites"),
  siteSettings: (siteId: string) => request<SiteSettingsOut>(`/sites/${siteId}/settings`),
  posImports: (siteId: string) => request<ImportBatchOut[]>(`/sites/${siteId}/pos/imports`),

  listEvents: (
    siteId: string,
    query: { state?: string; category?: string; since?: string; until?: string; limit?: number; offset?: number } = {},
    signal?: AbortSignal,
  ) => request<Page<EventOut>>("/events", { query: { site_id: siteId, ...query }, signal }),

  listAlerts: (
    siteId: string,
    query: { status_filter?: AlertStatus; category?: string; since?: string; until?: string; limit?: number; offset?: number } = {},
    signal?: AbortSignal,
  ) => request<Page<AlertOut>>("/alerts", { query: { site_id: siteId, ...query }, signal }),
  reviewAlert: (alertId: string, status: "confirmed" | "false_alarm", note?: string) =>
    request<AlertOut>(`/alerts/${alertId}`, { method: "PATCH", body: { status, note: note || null } }),

  dailySummary: (siteId: string, fromDay?: string, toDay?: string) =>
    request<DailySummaryOut[]>("/analytics/daily", { query: { site_id: siteId, from_day: fromDay, to_day: toDay } }),
  hourly: (siteId: string, day?: string) =>
    request<HourlyPointOut[]>("/analytics/hourly", { query: { site_id: siteId, day } }),

  /** All photos of a category in a period (R11): never one photo as "the" proof. */
  listSnapshots: (siteId: string, category: string, since: string, until: string, limit = 100) =>
    request<SnapshotItem[]>(`/sites/${siteId}/images`, { query: { category, since, until, limit } }),
  /** `url` comes from SnapshotItem ("/api/v1/images/..."); fetched with the bearer token. */
  snapshotBlob: (siteId: string, ref: string, signal?: AbortSignal) =>
    requestBlob(`/images/${siteId}/${ref}`, signal),
};
