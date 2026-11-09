"use client";

import { useCallback, useMemo, useState } from "react";

import { CategoryPhotos } from "@/components/live/category-photos";
import { EmptyState, ErrorBanner, MissingBackend, PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useAlertsSocket } from "@/hooks/use-alerts-socket";
import { usePolling } from "@/hooks/use-polling";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import type { AlertOut, AlertStatus } from "@/lib/api/types";
import { formatDateTime, formatMoney } from "@/lib/domain/format";
import { ALERT_SUBTYPE_LABEL, alertStatusLabel, alertStatusTone } from "@/lib/domain/labels";
import { sumMoney } from "@/lib/domain/money";
import { cn } from "@/lib/utils";

type Filter = "all" | AlertStatus;
const FILTERS: { key: Filter; label: string }[] = [
  { key: "open", label: "Écarts à vérifier" },
  { key: "confirmed", label: "Confirmées" },
  { key: "false_alarm", label: "Fausses alertes" },
  { key: "auto_resolved", label: "Résolues automatiquement" },
  { key: "all", label: "Toutes" },
];

export function AlertsReview({ siteId, currency }: { siteId: string; currency: string }) {
  const [filter, setFilter] = useState<Filter>("open");
  const [detail, setDetail] = useState<AlertOut | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const fetchAlerts = useCallback(
    (signal: AbortSignal) =>
      api.listAlerts(siteId, { status_filter: filter === "all" ? undefined : filter, limit: 200 }, signal),
    [siteId, filter],
  );
  const alerts = usePolling(fetchAlerts, 30_000);
  useAlertsSocket(siteId, () => alerts.refresh());

  const items = useMemo(() => alerts.data?.items ?? [], [alerts.data]);
  const detectedTotal = useMemo(() => sumMoney(items.map((a) => a.loss_est)), [items]);
  const confirmedTotal = useMemo(
    () => sumMoney(items.filter((a) => a.status === "confirmed").map((a) => a.loss_est)),
    [items],
  );

  async function review(alert: AlertOut, decision: "confirmed" | "false_alarm") {
    setBusyId(alert.id);
    setActionError(null);
    try {
      await api.reviewAlert(alert.id, decision);
      alerts.refresh();
    } catch (e) {
      setActionError(
        e instanceof ApiError && e.status === 409
          ? "Cette alerte a déjà été traitée ou n'est plus modifiable."
          : e instanceof Error
            ? e.message
            : "Erreur inconnue",
      );
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Alerts & Review"
        description="Écarts à vérifier : articles servis sans vente enregistrée. Un écart est un signal, jamais une preuve de vol ou de fraude."
      />

      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <Total label="Perte estimée détectée" value={formatMoney(detectedTotal, currency)} hint="Somme des pertes estimées de la liste affichée" />
        <Total label="Perte estimée confirmée" value={formatMoney(confirmedTotal, currency)} hint="Alertes confirmées par le gérant (liste affichée)" />
      </div>

      <nav aria-label="Filtrer les alertes" className="mb-3 flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <Button key={f.key} size="sm" variant={filter === f.key ? "default" : "outline"} aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
            {f.label}
          </Button>
        ))}
      </nav>

      {alerts.error && <ErrorBanner message={`${alerts.error}. Nouvelle tentative automatique.`} />}
      {actionError && <ErrorBanner message={actionError} />}
      {alerts.loading && !alerts.data && <p className="text-sm text-muted-foreground">Chargement…</p>}
      {alerts.data && items.length === 0 && <EmptyState>Aucune alerte pour ce filtre.</EmptyState>}

      <ul className="space-y-2">
        {items.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border bg-card p-3">
            <div className="min-w-40">
              <div className="flex items-center gap-2">
                <span className="font-medium">{a.category}</span>
                <Badge tone={alertStatusTone(a.status)}>{alertStatusLabel(a.status)}</Badge>
                {a.strong && <Badge tone="warning">Écart marqué</Badge>}
              </div>
              <time dateTime={a.created_at} className="text-xs text-muted-foreground">
                {formatDateTime(a.created_at)}
              </time>
              {a.subtype && <p className="text-xs text-muted-foreground">{ALERT_SUBTYPE_LABEL[a.subtype] ?? a.subtype}</p>}
            </div>
            <div className="text-sm">
              <span className="text-muted-foreground">Quantité sans vente : </span>
              <strong>{a.missing_qty}</strong>
            </div>
            <div className="text-sm">
              <span className="text-muted-foreground">Perte estimée : </span>
              <strong>{formatMoney(a.loss_est, currency)}</strong>{" "}
              <span className="text-xs text-muted-foreground">
                ({formatMoney(a.loss_min, currency)} – {formatMoney(a.loss_max, currency)})
              </span>
            </div>
            <div className="ml-auto flex items-center gap-2">
              <Button size="sm" variant="ghost" onClick={() => setDetail(a)}>
                Photos
              </Button>
              {a.status === "open" && (
                <>
                  <Button size="sm" variant="outline" disabled={busyId === a.id} onClick={() => void review(a, "false_alarm")}>
                    Fausse alerte
                  </Button>
                  <Button size="sm" disabled={busyId === a.id} onClick={() => void review(a, "confirmed")}>
                    Confirmer
                  </Button>
                </>
              )}
            </div>
          </li>
        ))}
      </ul>

      <div className={cn("mt-4")}>
        <MissingBackend title="Historique d'audit">
          L&apos;API n&apos;expose pas encore l&apos;historique d&apos;audit d&apos;une alerte (journal enregistré côté serveur, sans
          endpoint de lecture). Il sera affiché ici lorsque l&apos;endpoint existera.
        </MissingBackend>
      </div>

      <Dialog open={detail !== null} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent>
          {detail && (
            <>
              <DialogHeader>
                <DialogTitle>
                  {detail.category} — {formatDateTime(detail.created_at)}
                </DialogTitle>
                <DialogDescription>
                  Toutes les photos de la catégorie sur la période. Aucune photo isolée ne constitue une preuve.
                </DialogDescription>
              </DialogHeader>
              <CategoryPhotos siteId={siteId} category={detail.category} around={detail.created_at} windowMinutes={30} />
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

function Total({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-lg border bg-card p-3" title={hint}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}
