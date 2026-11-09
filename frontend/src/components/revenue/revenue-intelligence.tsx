"use client";

import { useCallback, useMemo } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState, ErrorBanner, PageHeader } from "@/components/page-header";
import { usePolling } from "@/hooks/use-polling";
import { api } from "@/lib/api/endpoints";
import { dayInZone, formatMoney } from "@/lib/domain/format";
import { sumMoney } from "@/lib/domain/money";
import { totalsByCategory } from "@/lib/domain/summary";

const RANGE_DAYS = 7;

export function RevenueIntelligence({ siteId, currency, timezone }: { siteId: string; currency: string; timezone: string }) {
  const fetchDaily = useCallback(() => {
    const end = new Date();
    const start = new Date(end.getTime() - (RANGE_DAYS - 1) * 86_400_000);
    return api.dailySummary(siteId, dayInZone(start, timezone), dayInZone(end, timezone));
  }, [siteId, timezone]);
  const daily = usePolling(fetchDaily, 60_000);

  const categories = useMemo(() => totalsByCategory(daily.data ?? []), [daily.data]);
  const lossEst = useMemo(() => sumMoney(categories.map((c) => c.lossEst)), [categories]);
  const lossConfirmed = useMemo(() => sumMoney(categories.map((c) => c.lossConfirmed)), [categories]);
  const gap = categories.reduce((n, c) => n + c.gapQty, 0);

  return (
    <>
      <PageHeader
        title="Revenue Intelligence"
        description={`${RANGE_DAYS} derniers jours. Quantités vues par les caméras comparées aux ventes payées en caisse. Les montants sont des estimations calculées par le serveur, jamais des montants exacts.`}
      />
      {daily.error && <ErrorBanner message={daily.error} />}
      {daily.loading && !daily.data && <p className="text-sm text-muted-foreground">Chargement…</p>}
      {daily.data && categories.length === 0 && <EmptyState>Aucune donnée sur la période.</EmptyState>}

      {categories.length > 0 && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Kpi label="Écart à vérifier (quantité)" value={String(gap)} />
            <Kpi label="Perte estimée détectée" value={formatMoney(lossEst, currency)} />
            <Kpi label="Perte estimée confirmée" value={formatMoney(lossConfirmed, currency)} />
          </div>

          <section className="rounded-lg border bg-card p-4" aria-label="Comparaison par catégorie">
            <h2 className="mb-3 text-sm font-semibold">Détecté (caméra) vs payé (caisse), par catégorie</h2>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={categories}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(240 4% 20%)" />
                  <XAxis dataKey="category" stroke="hsl(240 5% 65%)" fontSize={12} />
                  <YAxis allowDecimals={false} stroke="hsl(240 5% 65%)" fontSize={12} />
                  <Tooltip contentStyle={{ background: "hsl(240 5% 11%)", border: "1px solid hsl(240 4% 20%)" }} />
                  <Legend />
                  <Bar dataKey="cvQty" name="Détecté (caméra)" fill="#9333EA" />
                  <Bar dataKey="posQty" name="Payé (caisse)" fill="#64748b" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">Catégorie</th>
                  <th className="px-3 py-2 text-right">Détecté</th>
                  <th className="px-3 py-2 text-right">Payé</th>
                  <th className="px-3 py-2 text-right">Écart</th>
                  <th className="px-3 py-2 text-right">Perte estimée</th>
                  <th className="px-3 py-2 text-right">Confirmée</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {categories.map((c) => (
                  <tr key={c.category}>
                    <td className="px-3 py-2 font-medium">{c.category}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{c.cvQty}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{c.posQty}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{c.gapQty}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatMoney(c.lossEst, currency)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatMoney(c.lossConfirmed, currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}
