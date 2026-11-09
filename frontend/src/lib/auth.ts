/**
 * Access-token storage. sessionStorage: cleared when the tab closes, never sent by the
 * browser automatically (no CSRF surface). The backend issues a bearer token only; moving
 * to an httpOnly cookie would need a backend change and is out of scope.
 */

const TOKEN_KEY = "rada.token";
const SITE_KEY = "rada.site";

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return storage()?.getItem(TOKEN_KEY) ?? null;
}

export function setToken(token: string): void {
  storage()?.setItem(TOKEN_KEY, token);
}

export function clearSession(): void {
  storage()?.removeItem(TOKEN_KEY);
}

export function getStoredSite(): string | null {
  return storage()?.getItem(SITE_KEY) ?? null;
}

export function setStoredSite(siteId: string): void {
  storage()?.setItem(SITE_KEY, siteId);
}
