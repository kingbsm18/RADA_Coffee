"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AlertCard from "@/components/alerts/AlertCard";
import AlertSummary from "@/components/alerts/AlertSummary";
import { computeTotals } from "@/components/alerts/format";
import { fetchAlerts, reviewAlert } from "@/lib/api";
import { subscribeAlerts } from "@/lib/ws";
import type { Alert, ReviewDecision } from "@/types/alerts";

type Filter = "all" | "anomaly" | "confirmed" | "false_alarm";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Toutes" },
  { key: "anomaly", label: "À vérifier" },
  { key: "confirmed", label: "Validées" },
  { key: "false_alarm", label: "Fausses alertes" },
];

const REFRESH_MS = 30_000;

const today = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Africa/Casablanca" }).format(new Date());

export default function AlertsPage() {
  const [day, setDay] = useState(today);
  const [filter, setFilter] = useState<Filter>("anomaly");
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchAlerts(day);
      setAlerts(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur inconnue");
    } finally {
      setLoading(false);
    }
  }, [day]);

  useEffect(() => {
    setLoading(true);
    void load();
    const poll = setInterval(() => void load(), REFRESH_MS);
    const unsubscribe = subscribeAlerts(() => void load());
    return () => {
      clearInterval(poll);
      unsubscribe();
    };
  }, [load]);

  const onReview = useCallback(async (id: string, decision: ReviewDecision) => {
    const updated = await reviewAlert(id, decision);
    setAlerts((prev) => prev.map((a) => (a.id === id ? updated : a)));
  }, []);

  const totals = useMemo(() => computeTotals(alerts), [alerts]);
  const visible = useMemo(
    () =>
      alerts
        .filter((a) => filter === "all" || a.status === filter)
        .sort((a, b) => b.detected_at.localeCompare(a.detected_at)),
    [alerts, filter],
  );

  return (
    <main className="page">
      <header className="page-head">
        <div>
          <h1>Alertes</h1>
          <p className="muted">
            Écarts à vérifier : articles servis sans vente enregistrée. Un écart est un signal, pas une preuve.
          </p>
        </div>
        <label className="date">
          Jour
          <input type="date" value={day} max={today()} onChange={(e) => e.target.value && setDay(e.target.value)} />
        </label>
      </header>

      <AlertSummary totals={totals} />

      <nav className="filters" aria-label="Filtrer les alertes">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            className={`chip ${filter === f.key ? "chip-active" : ""}`}
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </nav>

      {error && (
        <p role="alert" className="error banner">
          {error}. Nouvelle tentative automatique toutes les 30 secondes.
        </p>
      )}
      {loading && <p className="muted">Chargement…</p>}
      {!loading && !error && visible.length === 0 && <p className="muted">Aucune alerte pour ce filtre.</p>}

      <div className="list">
        {visible.map((a) => (
          <AlertCard key={a.id} alert={a} onReview={onReview} />
        ))}
      </div>
    </main>
  );
}
