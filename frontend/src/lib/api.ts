// Typed client for the RADA backend. Amounts are strings (exact decimals): never parse them as floats.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "rada_token";

export type Role = "admin" | "manager";
export type AlertStatus = "open" | "confirmed" | "false_alarm" | "auto_resolved";

export interface Alert {
  id: string;
  site_id: string;
  detection_id: string;
  category: string;
  subtype: string | null; // e.g. "cancelled_after_service"
  missing_qty: number;
  loss_est: string; // "perte estimée", never an exact amount
  loss_min: string;
  loss_max: string;
  status: AlertStatus;
  strong: boolean;
  review_note: string | null;
  created_at: string;
  resolved_at: string | null;
}
export interface Page<T> { items: T[]; total: number }
export interface Site { id: string; name: string; timezone: string; currency: string; active: boolean; created_at: string }
export interface DailySummary {
  day: string; category: string; pos_qty: number; cv_qty: number; gap_qty: number;
  loss_est: string; loss_min: string; loss_max: string; loss_confirmed: string;
  pending_count: number; false_alarm_count: number; is_final: boolean;
}
export interface HourlyPoint { hour: number; category: string; pos_qty: number; cv_qty: number }
export interface SnapshotItem { event_id: string; timestamp: string; category: string; confidence: number; state: string; url: string }

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// The token lives in sessionStorage (cleared when the tab closes). Any script running on the
// page could read it, so keep the dashboard free of third-party scripts.
let token: string | null = null;
export function getToken(): string | null {
  if (token === null && typeof window !== "undefined") token = window.sessionStorage.getItem(TOKEN_KEY);
  return token;
}
export function setToken(value: string | null): void {
  token = value;
  if (typeof window === "undefined") return;
  if (value === null) window.sessionStorage.removeItem(TOKEN_KEY);
  else window.sessionStorage.setItem(TOKEN_KEY, value);
}

type Query = Record<string, string | number | boolean | undefined>;

function buildUrl(path: string, query?: Query): string {
  const url = new URL(`/api/v1${path}`, API_URL);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined) url.searchParams.set(key, String(value));
  }
  return url.toString();
}

async function request<T>(method: string, path: string, options: { query?: Query; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const current = getToken();
  if (current) headers.Authorization = `Bearer ${current}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(buildUrl(path, options.query), {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (response.status === 401) setToken(null); // expired or revoked: the UI should show the login page
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export async function login(username: string, password: string): Promise<Role> {
  const data = await request<{ access_token: string; role: Role }>("POST", "/auth/login", {
    body: { username, password },
  });
  setToken(data.access_token);
  return data.role;
}
export const logout = (): void => setToken(null);

export const listSites = () => request<Site[]>("GET", "/sites");

export const listAlerts = (
  siteId: string,
  filters: { status_filter?: AlertStatus; category?: string; since?: string; until?: string; limit?: number; offset?: number } = {},
) => request<Page<Alert>>("GET", "/alerts", { query: { site_id: siteId, ...filters } });

export const reviewAlert = (alertId: string, status: "confirmed" | "false_alarm", note?: string) =>
  request<Alert>("PATCH", `/alerts/${alertId}`, { body: { status, note } });

export const dailySummary = (siteId: string, fromDay?: string, toDay?: string) =>
  request<DailySummary[]>("GET", "/analytics/daily", { query: { site_id: siteId, from_day: fromDay, to_day: toDay } });

export const hourlySummary = (siteId: string, day?: string) =>
  request<HourlyPoint[]>("GET", "/analytics/hourly", { query: { site_id: siteId, day } });

// All photos of a category in a period (never present one photo as THE proof).
export const listSnapshots = (siteId: string, category: string, since: string, until: string) =>
  request<SnapshotItem[]>("GET", `/sites/${siteId}/images`, { query: { category, since, until } });

// Snapshots need the Authorization header, so fetch the bytes and use an object URL in <img src>.
export async function fetchSnapshotBlobUrl(snapshotUrl: string): Promise<string> {
  const response = await fetch(new URL(snapshotUrl, API_URL).toString(), {
    headers: { Authorization: `Bearer ${getToken() ?? ""}` },
  });
  if (!response.ok) throw new ApiError(response.status, "snapshot unavailable");
  return URL.createObjectURL(await response.blob());
}

export const dailyCsvUrl = (siteId: string, fromDay: string, toDay: string) =>
  buildUrl("/analytics/daily/export.csv", { site_id: siteId, from_day: fromDay, to_day: toDay });
