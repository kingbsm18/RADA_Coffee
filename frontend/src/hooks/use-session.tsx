"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api/endpoints";
import type { MeOut, SiteOut } from "@/lib/api/types";
import { clearSession, getStoredSite, getToken, setStoredSite } from "@/lib/auth";

interface SessionValue {
  user: MeOut;
  sites: SiteOut[];
  site: SiteOut | null;
  selectSite: (siteId: string) => void;
  logout: () => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}

/** Loads the authenticated user and sites; redirects to /login without a valid token. */
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<MeOut | null>(null);
  const [sites, setSites] = useState<SiteOut[]>([]);
  const [siteId, setSiteId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    Promise.all([api.me(), api.listSites()])
      .then(([me, list]) => {
        if (cancelled) return;
        const active = list.filter((s) => s.active);
        const stored = getStoredSite();
        setUser(me);
        setSites(active);
        setSiteId(active.find((s) => s.id === stored)?.id ?? active[0]?.id ?? null);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Erreur inconnue");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  const selectSite = useCallback((id: string) => {
    setStoredSite(id);
    setSiteId(id);
  }, []);

  const logout = useCallback(() => {
    clearSession();
    router.replace("/login");
  }, [router]);

  const value = useMemo<SessionValue | null>(
    () =>
      user ? { user, sites, site: sites.find((s) => s.id === siteId) ?? null, selectSite, logout } : null,
    [user, sites, siteId, selectSite, logout],
  );

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center p-6 text-center text-sm text-muted-foreground" role="alert">
        Impossible de charger la session : {error}
      </div>
    );
  }
  if (!value) {
    return <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">Chargement…</div>;
  }
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
