"use client";

import { useCallback, useState } from "react";

import { EventStateBadge } from "@/components/live/event-state-badge";
import { EmptyState, ErrorBanner, PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { usePolling } from "@/hooks/use-polling";
import { api } from "@/lib/api/endpoints";
import { DETECTION_STATES } from "@/lib/api/types";
import { formatConfidence, formatDateTime } from "@/lib/domain/format";
import { eventStateLabel } from "@/lib/domain/labels";

const PAGE_SIZE = 50;

export function EventsTable({ siteId }: { siteId: string }) {
  const [state, setState] = useState<string>("");
  const [offset, setOffset] = useState(0);

  const fetchEvents = useCallback(
    (signal: AbortSignal) => api.listEvents(siteId, { state: state || undefined, limit: PAGE_SIZE, offset }, signal),
    [siteId, state, offset],
  );
  const events = usePolling(fetchEvents, 15_000);
  const total = events.data?.total ?? 0;

  return (
    <>
      <PageHeader title="Events" description="Événements de détection caméra et leur statut de rapprochement avec la caisse." />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm">
          Statut
          <select
            className="h-8 rounded-md border border-input bg-card px-2 text-sm"
            value={state}
            onChange={(e) => {
              setState(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">Tous</option>
            {DETECTION_STATES.map((s) => (
              <option key={s} value={s}>
                {eventStateLabel(s)}
              </option>
            ))}
          </select>
        </label>
        <span className="ml-auto text-xs text-muted-foreground">{total} événement(s)</span>
      </div>

      {events.error && <ErrorBanner message={events.error} />}
      {events.data && events.data.items.length === 0 && <EmptyState>Aucun événement.</EmptyState>}

      {events.data && events.data.items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Heure</th>
                <th className="px-3 py-2">Caméra</th>
                <th className="px-3 py-2">Catégorie</th>
                <th className="px-3 py-2 text-right">Qté</th>
                <th className="px-3 py-2 text-right">Confiance</th>
                <th className="px-3 py-2">Statut</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {events.data.items.map((e) => (
                <tr key={e.id}>
                  <td className="px-3 py-2 tabular-nums">{formatDateTime(e.timestamp)}</td>
                  <td className="px-3 py-2">{e.camera_id}</td>
                  <td className="px-3 py-2">{e.category}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{e.count}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatConfidence(e.confidence)}</td>
                  <td className="px-3 py-2">
                    <EventStateBadge state={e.state} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-3 flex items-center justify-end gap-2">
        <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
          Précédent
        </Button>
        <Button size="sm" variant="outline" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
          Suivant
        </Button>
      </div>
    </>
  );
}
