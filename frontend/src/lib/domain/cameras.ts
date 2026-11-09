import type { EventOut } from "@/lib/api/types";

/**
 * The backend has NO camera listing endpoint yet (the `camera` table exists, but nothing
 * exposes it). Until GET /sites/{site_id}/cameras exists, cameras are derived from the
 * camera_id of recent detection events. This is a real observation ("this camera sent
 * events"), not an inventory: name, enabled flag and connectivity are unknown.
 */
export interface DerivedCamera {
  cameraId: string;
  lastEventAt: string;
  eventCount: number;
}

export function deriveCameras(events: readonly EventOut[]): DerivedCamera[] {
  const byId = new Map<string, DerivedCamera>();
  for (const event of events) {
    const known = byId.get(event.camera_id);
    if (!known) {
      byId.set(event.camera_id, { cameraId: event.camera_id, lastEventAt: event.timestamp, eventCount: 1 });
    } else {
      known.eventCount += 1;
      if (event.timestamp > known.lastEventAt) known.lastEventAt = event.timestamp;
    }
  }
  return [...byId.values()].sort((a, b) => a.cameraId.localeCompare(b.cameraId));
}
