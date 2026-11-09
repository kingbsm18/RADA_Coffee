"use client";

import { useCallback, useMemo, useState } from "react";

import { CameraPlayer } from "@/components/live/camera-player";
import { EventDetailDialog } from "@/components/live/event-detail-dialog";
import { LiveEventFeed } from "@/components/live/live-event-feed";
import { buildStatusItems, OperationalStatusBar } from "@/components/live/operational-status-bar";
import { useAlertsSocket } from "@/hooks/use-alerts-socket";
import { usePolling } from "@/hooks/use-polling";
import { api } from "@/lib/api/endpoints";
import { deriveCameras } from "@/lib/domain/cameras";
import { joinEventsWithAlerts, type LiveEventRow } from "@/lib/domain/events";

const EVENTS_POLL_MS = 5_000;
const ALERTS_POLL_MS = 15_000;
const STATUS_POLL_MS = 30_000;
const FEED_SIZE = 50;
const ALERT_LOOKBACK_MS = 24 * 3_600_000;

export function LiveOperations({ siteId, currency }: { siteId: string; currency: string }) {
  const [cameraId, setCameraId] = useState<string | null>(null);
  const [selected, setSelected] = useState<LiveEventRow | null>(null);

  const fetchEvents = useCallback(
    (signal: AbortSignal) => api.listEvents(siteId, { limit: FEED_SIZE }, signal),
    [siteId],
  );
  const events = usePolling(fetchEvents, EVENTS_POLL_MS);

  const fetchAlerts = useCallback(
    (signal: AbortSignal) =>
      api.listAlerts(siteId, { since: new Date(Date.now() - ALERT_LOOKBACK_MS).toISOString(), limit: 200 }, signal),
    [siteId],
  );
  const alerts = usePolling(fetchAlerts, ALERTS_POLL_MS);

  const fetchHealth = useCallback((signal: AbortSignal) => api.healthReady(signal), []);
  const health = usePolling(fetchHealth, STATUS_POLL_MS);

  const fetchImports = useCallback(() => api.posImports(siteId), [siteId]);
  const imports = usePolling(fetchImports, STATUS_POLL_MS);

  // The socket only pushes alert_created / alert_updated (no detection events): use it to
  // refresh immediately instead of waiting for the next poll.
  const socket = useAlertsSocket(siteId, () => {
    alerts.refresh();
    events.refresh();
  });

  const items = events.data?.items;
  const cameras = useMemo(() => deriveCameras(items ?? []), [items]);
  const effectiveCameraId = cameras.some((c) => c.cameraId === cameraId) ? cameraId : (cameras[0]?.cameraId ?? null);

  const rows = useMemo(
    () => joinEventsWithAlerts(items ?? [], alerts.data?.items ?? []),
    [items, alerts.data],
  );

  const lastPosSyncAt = useMemo(() => {
    const done = (imports.data ?? []).map((b) => b.completed_at).filter((t): t is string => t !== null);
    return done.length ? done.reduce((a, b) => (a > b ? a : b)) : null;
  }, [imports.data]);

  const statusItems = buildStatusItems({
    apiReady: health.data ? health.data.status === "ready" : health.error ? false : null,
    socket,
    lastEventAt: items?.[0]?.timestamp ?? null,
    lastPosSyncAt,
    posSyncKnown: imports.data !== null || imports.error !== null,
  });

  return (
    <div className="flex h-full flex-col gap-3">
      <OperationalStatusBar items={statusItems} />
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <CameraPlayer
          siteId={siteId}
          cameras={cameras}
          selectedCameraId={effectiveCameraId}
          onSelectCamera={setCameraId}
        />
        <div className="min-h-[24rem] xl:min-h-0">
          <LiveEventFeed
            siteId={siteId}
            rows={rows}
            loading={events.loading}
            error={events.error}
            selectedEventId={selected?.event.id ?? null}
            onSelect={setSelected}
          />
        </div>
      </div>
      <EventDetailDialog siteId={siteId} currency={currency} row={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
