"use client";

import { Download } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { EmptyState, ErrorBanner, PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePolling } from "@/hooks/use-polling";
import { requestBlob } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { dayInZone, formatMoney } from "@/lib/domain/format";
import { totalsByDay } from "@/lib/domain/summary";

const RANGES = [
  { days: 7, label: "7 jours" },
  { days: 30, label: "30 jours" },
];

export function ReportsView({ siteId, currency, timezone }: { siteId: string; currency: string; timezone: string }) {
  const [days, setDays] = useState(7);
  const [exportError, setExportError] = useState<string | null>(null);

  const range = useCallback(() => {
    const end = new Date();
    const start = new Date(end.getTime() - (days - 1) * 86_400_000);
    return { from: dayInZone(start, timezone), to: dayInZone(end, timezone) };
  }, [days, timezone]);

  const fetchDaily = useCallback(() => {
    const { from, to } = range();
    return api.dailySummary(siteId, from, to);
  }, [siteId, range]);
  const daily = usePolling(fetchDaily, 120_000);
  const rows = useMemo(() => totalsByDay(daily.data ?? []), [daily.data]);

  async function exportCsv() {
    setExportError(null);
    try {
      const { from, to } = range();
      const blob = await requestBlob(`/analytics/daily/export.csv?site_id=${encodeURIComponent(siteId)}&from_day=${from}&to_day=${to}`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `rada-daily-${siteId}-${from}-${to}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "Erreur inconnue");
    }
  }

  return (
    <>
      <PageHeader
        title="Reports"
        description="Synthèses journalières. Une journée est « Provisoire » tant que le recalcul de fin de service n'a pas eu lieu."
        actions={
          <div className="flex items-center gap-2">
            {RANGES.map((r) => (
              <Button key={r.days} size="sm" variant={days === r.days ? "default" : "outline"} aria-pressed={days === r.days} onClick={() => setDays(r.days)}>
                {r.label}
              </Button>
            ))}
            <Button size="sm" variant="secondary" onClick={() => void exportCsv()}>
              <Download className="h-4 w-4" aria-hidden /> Export CSV
            </Button>
          </div>
        }
      />
      {daily.error && <ErrorBanner message={daily.error} />}
      {exportError && <ErrorBanner message={`Export impossible : ${exportError}`} />}
      {daily.data && rows.length === 0 && <EmptyState>Aucune donnée sur la période.</EmptyState>}

      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Jour</th>
                <th className="px-3 py-2 text-right">Détecté</th>
                <th className="px-3 py-2 text-right">Payé</th>
                <th className="px-3 py-2 text-right">Écart</th>
                <th className="px-3 py-2 text-right">Perte estimée</th>
                <th className="px-3 py-2 text-right">Confirmée</th>
                <th className="px-3 py-2">État</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((r) => (
                <tr key={r.day}>
                  <td className="px-3 py-2 tabular-nums">{r.day}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.cvQty}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.posQty}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.gapQty}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatMoney(r.lossEst, currency)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatMoney(r.lossConfirmed, currency)}</td>
                  <td className="px-3 py-2">
                    <Badge tone={r.isFinal ? "success" : "warning"}>{r.isFinal ? "Définitif" : "Provisoire"}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
