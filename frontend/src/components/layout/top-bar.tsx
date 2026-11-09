"use client";

import { Bell, LogOut, ScanEye } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { usePolling } from "@/hooks/use-polling";
import { useSession } from "@/hooks/use-session";
import { api } from "@/lib/api/endpoints";

const POLL_MS = 30_000;

export function TopBar() {
  const { user, sites, site, selectSite, logout } = useSession();
  const siteId = site?.id ?? null;

  const fetchOpen = useCallback(
    (signal: AbortSignal) => api.listAlerts(siteId ?? "", { status_filter: "open", limit: 1 }, signal),
    [siteId],
  );
  const openAlerts = usePolling(fetchOpen, POLL_MS, siteId !== null);

  const fetchHealth = useCallback((signal: AbortSignal) => api.healthReady(signal), []);
  const health = usePolling(fetchHealth, POLL_MS);
  const apiOk = health.data?.status === "ready";

  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b bg-card px-4">
      <Link href="/live" className="flex items-center gap-2 font-semibold tracking-tight">
        <ScanEye className="h-5 w-5 text-primary" aria-hidden />
        RADA_COFFEE
      </Link>

      <div className="ml-2 flex items-center gap-2">
        {sites.length > 0 ? (
          <Select value={site?.id ?? ""} onValueChange={selectSite}>
            <SelectTrigger aria-label="Café / site" className="w-48">
              <SelectValue placeholder="Choisir un café" />
            </SelectTrigger>
            <SelectContent>
              {sites.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <span className="text-sm text-muted-foreground">Aucun café</span>
        )}
      </div>

      <div className="ml-auto flex items-center gap-3">
        <span
          className="flex items-center gap-1.5 text-xs text-muted-foreground"
          title="État de l'API backend (/health/ready)"
        >
          <span
            className={`h-2 w-2 rounded-full ${health.data ? (apiOk ? "bg-success" : "bg-destructive") : health.error ? "bg-destructive" : "bg-muted-foreground"}`}
          />
          {health.data ? (apiOk ? "API opérationnelle" : "API dégradée") : health.error ? "API injoignable" : "API…"}
        </span>

        <Button asChild variant="ghost" size="icon" title="Écarts à vérifier">
          <Link href="/alerts" aria-label={`Écarts à vérifier : ${openAlerts.data?.total ?? 0}`}>
            <span className="relative">
              <Bell className="h-4 w-4" />
              {(openAlerts.data?.total ?? 0) > 0 && (
                <span className="absolute -right-2 -top-2 min-w-4 rounded-full bg-primary px-1 text-center text-[10px] leading-4 text-primary-foreground">
                  {openAlerts.data?.total}
                </span>
              )}
            </span>
          </Link>
        </Button>

        <span className="hidden text-xs text-muted-foreground sm:inline" title={`Rôle : ${user.role}`}>
          {user.username}
        </span>
        <Button variant="ghost" size="icon" onClick={logout} title="Se déconnecter" aria-label="Se déconnecter">
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </header>
  );
}
