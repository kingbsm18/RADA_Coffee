/** Runtime configuration. Only NEXT_PUBLIC_* values; nothing here is secret. */

const DEFAULT_API_URL = "http://localhost:8000";

export function apiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim() || DEFAULT_API_URL;
  return raw.replace(/\/+$/, "");
}

export const API_PREFIX = "/api/v1";

export function apiUrl(path: string): string {
  return `${apiBaseUrl()}${API_PREFIX}${path}`;
}

/** http(s):// -> ws(s):// for the alerts WebSocket. */
export function wsUrl(path: string): string {
  return apiUrl(path).replace(/^http/, "ws");
}

/** Optional stream gateway base URL. Empty = no gateway (nothing is faked). */
export function streamGatewayUrl(): string | null {
  const raw = process.env.NEXT_PUBLIC_STREAM_GATEWAY_URL?.trim();
  return raw ? raw.replace(/\/+$/, "") : null;
}
