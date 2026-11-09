import type { AlertOut, EventOut } from "@/lib/api/types";

export interface LiveEventRow {
  event: EventOut;
  /** Alert created for this detection, if any (alert.detection_id === event.id). */
  alert: AlertOut | null;
}

export function joinEventsWithAlerts(events: readonly EventOut[], alerts: readonly AlertOut[]): LiveEventRow[] {
  const byDetection = new Map(alerts.map((a) => [a.detection_id, a]));
  return events.map((event) => ({ event, alert: byDetection.get(event.id) ?? null }));
}

export interface QuantityView {
  /** null = the backend does not provide this figure for this event. */
  matched: number | null;
  unmatched: number | null;
}

/**
 * POS-matched / unmatched quantities, using ONLY facts the backend states:
 *  - an alert gives the unmatched quantity (missing_qty);
 *  - state "matched" means the whole event was matched;
 *  - anything else (pending, low confidence...) is unknown, shown as "—".
 * No reconciliation is recomputed here. A per-event matched quantity is a missing
 * backend field (see docs/frontend_streaming.md, "Missing backend contracts").
 */
export function quantityView(row: LiveEventRow): QuantityView {
  const { event, alert } = row;
  if (alert) return { matched: null, unmatched: alert.missing_qty };
  if (event.state === "matched") return { matched: event.count, unmatched: 0 };
  return { matched: null, unmatched: null };
}

export function displayQty(value: number | null): string {
  return value === null ? "—" : String(value);
}
