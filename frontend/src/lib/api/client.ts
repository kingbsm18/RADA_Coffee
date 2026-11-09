import { apiUrl } from "@/lib/config";
import { clearSession, getToken } from "@/lib/auth";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
    }
  } catch {
    /* non-JSON error body */
  }
  return `Erreur ${res.status}`;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH";
  query?: Query;
  body?: unknown;
  auth?: boolean;
  signal?: AbortSignal;
}

async function rawRequest(path: string, opts: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.auth !== false) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  let res: Response;
  try {
    res = await fetch(apiUrl(withQuery(path, opts.query)), {
      method: opts.method ?? "GET",
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: opts.signal,
      cache: "no-store",
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "Serveur injoignable");
  }
  if (res.status === 401 && opts.auth !== false) {
    clearSession();
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.location.assign("/login");
    }
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  return res;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await rawRequest(path, opts);
  return (await res.json()) as T;
}

/** Authenticated binary fetch (snapshots): <img src> cannot send the bearer header. */
export async function requestBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const res = await rawRequest(path, { signal });
  return res.blob();
}
