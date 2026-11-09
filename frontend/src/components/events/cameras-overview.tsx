"use client";

import { useCallback, useMemo } from "react";

import { EmptyState, ErrorBanner, MissingBackend, PageHeader } from "@/components/page-header";
import { usePolling } from "@/hooks/use-polling";
import { api } from "@/lib/api/endpoints";
import { deriveCameras } from "@/lib/domain/cameras";
import { formatDateTime, relativeAge } from "@/lib/domain/format";

export function CamerasOverview({ siteId }: { siteId: string }) {
  const fetchEvents = useCallback((signal: AbortSignal) => api.listEvents(siteId, { limit: 200 }, signal), [siteId]);
  const events = usePolling(fetchEvents, 30_000);
  const cameras = useMemo(() => deriveCameras(events.data?.items ?? []), [events.data]);

  return (
    <>
      <PageHeader
        title="Cameras"
        description="Caméras ayant envoyé des événements de détection récents (200 derniers événements). Ce n'est pas un inventaire : le backend n'expose pas encore la liste des caméras."
      />
      {events.error && <ErrorBanner message={events.error} />}
      {events.data && cameras.length === 0 && <EmptyState>Aucune caméra n&apos;a encore envoyé d&apos;événement.</EmptyState>}

      {cameras.length > 0 && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Caméra</th>
                <th className="px-3 py-2">Dernier événement</th>
                <th className="px-3 py-2 text-right">Événements (échantillon)</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {cameras.map((c) => (
                <tr key={c.cameraId}>
                  <td className="px-3 py-2 font-medium">{c.cameraId}</td>
                  <td className="px-3 py-2">
                    {formatDateTime(c.lastEventAt)} <span className="text-muted-foreground">({relativeAge(c.lastEventAt)})</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{c.eventCount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <MissingBackend title="Inventaire des caméras">
          Il manque GET /sites/{"{site_id}"}/cameras (la table camera existe : nom, actif, dernière activité, sans endpoint de lecture).
        </MissingBackend>
        <MissingBackend title="Diagnostics de flux, FPS, latence, appareil edge">
          Il manque un heartbeat edge (état, FPS, latence, dernière image) et une passerelle de flux sécurisée. Voir docs/frontend_streaming.md.
        </MissingBackend>
      </div>
    </>
  );
}
