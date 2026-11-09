"use client";

import { Radio } from "lucide-react";

import { EventStateBadge } from "@/components/live/event-state-badge";
import { SnapshotImage } from "@/components/live/snapshot-image";
import { Skeleton } from "@/components/ui/skeleton";
import { displayQty, quantityView, type LiveEventRow } from "@/lib/domain/events";
import { formatConfidence, formatTime } from "@/lib/domain/format";
import { cn } from "@/lib/utils";

interface LiveEventFeedProps {
  siteId: string;
  rows: LiveEventRow[];
  loading: boolean;
  error: string | null;
  selectedEventId: string | null;
  onSelect: (row: LiveEventRow) => void;
}

export function LiveEventFeed({ siteId, rows, loading, error, selectedEventId, onSelect }: LiveEventFeedProps) {
  return (
    <section aria-label="Flux d'événements" className="flex h-full min-h-0 flex-col rounded-lg border bg-card">
      <header className="flex items-center gap-2 border-b px-3 py-2">
        <Radio className="h-4 w-4 text-primary" aria-hidden />
        <h2 className="text-sm font-semibold">Événements récents</h2>
        <span className="ml-auto text-xs text-muted-foreground">{rows.length}</span>
      </header>

      {error && (
        <p role="alert" className="border-b bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}. Nouvelle tentative automatique.
        </p>
      )}

      <ul className="min-h-0 flex-1 divide-y overflow-y-auto" data-testid="event-feed">
        {loading && rows.length === 0 &&
          Array.from({ length: 5 }, (_, i) => (
            <li key={i} className="flex gap-3 p-3">
              <Skeleton className="h-12 w-16" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-3 w-1/2" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            </li>
          ))}

        {!loading && !error && rows.length === 0 && (
          <li className="p-6 text-center text-sm text-muted-foreground">Aucun événement pour le moment.</li>
        )}

        {rows.map((row) => {
          const { event } = row;
          const qty = quantityView(row);
          return (
            <li key={event.id}>
              <button
                type="button"
                onClick={() => onSelect(row)}
                aria-pressed={selectedEventId === event.id}
                className={cn(
                  "flex w-full gap-3 p-3 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  selectedEventId === event.id && "bg-primary/10",
                )}
              >
                <SnapshotImage
                  siteId={siteId}
                  snapshotRef={event.snapshot_ref}
                  alt={`Photo ${event.category}`}
                  className="h-12 w-16 shrink-0"
                />
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <time dateTime={event.timestamp} className="text-xs tabular-nums text-muted-foreground">
                      {formatTime(event.timestamp)}
                    </time>
                    <span className="truncate text-sm font-medium">{event.category}</span>
                    <span className="text-sm tabular-nums">×{event.count}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <EventStateBadge state={event.state} />
                    <span>Confiance {formatConfidence(event.confidence)}</span>
                    <span title="Quantité rapprochée avec la caisse">Rapprochée {displayQty(qty.matched)}</span>
                    <span title="Quantité sans vente enregistrée">Écart {displayQty(qty.unmatched)}</span>
                  </div>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
