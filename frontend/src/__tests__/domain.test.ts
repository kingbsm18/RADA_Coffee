import { describe, expect, it } from "vitest";

import type { AlertOut, DailySummaryOut, EventOut } from "@/lib/api/types";
import { deriveCameras } from "@/lib/domain/cameras";
import { displayQty, joinEventsWithAlerts, quantityView } from "@/lib/domain/events";
import { formatMoney, relativeAge } from "@/lib/domain/format";
import { alertStatusLabel, eventStateLabel } from "@/lib/domain/labels";
import { sumMoney } from "@/lib/domain/money";
import { totalsByCategory, totalsByDay } from "@/lib/domain/summary";
import { nextPlayerState } from "@/lib/streaming/player-state";

const event = (over: Partial<EventOut> = {}): EventOut => ({
  id: "d1",
  event_id: "e1",
  site_id: "s",
  camera_id: "cam-1",
  timestamp: "2026-11-08T10:00:00Z",
  category: "coffee",
  count: 3,
  confidence: 0.9,
  snapshot_ref: null,
  model_version: "m1",
  state: "pending",
  ...over,
});

const alert = (over: Partial<AlertOut> = {}): AlertOut => ({
  id: "a1",
  site_id: "s",
  detection_id: "d1",
  category: "coffee",
  subtype: null,
  missing_qty: 1,
  loss_est: "12.50",
  loss_min: "10.00",
  loss_max: "15.00",
  status: "open",
  strong: false,
  review_note: null,
  created_at: "2026-11-08T10:20:00Z",
  resolved_at: null,
  ...over,
});

describe("money", () => {
  it("adds decimal strings exactly (no float drift)", () => {
    expect(sumMoney(["0.10", "0.20"])).toBe("0.30");
    expect(sumMoney(["12.50", "7.5", "1000"])).toBe("1020.00");
    expect(sumMoney([])).toBe("0.00");
  });
  it("rejects malformed amounts", () => {
    expect(() => sumMoney(["1.234"])).toThrow();
    expect(() => sumMoney(["abc"])).toThrow();
  });
  it("formats from the string without converting to float", () => {
    expect(formatMoney("1234567.5")).toBe("1\u202f234\u202f567,50\u00a0MAD");
    expect(formatMoney("0.00", "MAD")).toBe("0,00\u00a0MAD");
  });
});

describe("events join and quantities", () => {
  it("links an alert to its detection by detection_id", () => {
    const rows = joinEventsWithAlerts([event()], [alert()]);
    expect(rows[0]?.alert?.id).toBe("a1");
  });
  it("unmatched quantity comes from the alert, matched stays unknown", () => {
    expect(quantityView({ event: event(), alert: alert({ missing_qty: 2 }) })).toEqual({ matched: null, unmatched: 2 });
  });
  it("state matched means the whole event was matched", () => {
    expect(quantityView({ event: event({ state: "matched" }), alert: null })).toEqual({ matched: 3, unmatched: 0 });
  });
  it("pending event: both unknown (never invented)", () => {
    const q = quantityView({ event: event(), alert: null });
    expect(q).toEqual({ matched: null, unmatched: null });
    expect(displayQty(q.matched)).toBe("—");
  });
});

describe("cameras derived from events", () => {
  it("groups by camera_id with the latest event time", () => {
    const cams = deriveCameras([
      event({ camera_id: "cam-2", timestamp: "2026-11-08T09:00:00Z" }),
      event({ camera_id: "cam-1", timestamp: "2026-11-08T08:00:00Z" }),
      event({ camera_id: "cam-1", timestamp: "2026-11-08T10:00:00Z" }),
    ]);
    expect(cams.map((c) => c.cameraId)).toEqual(["cam-1", "cam-2"]);
    expect(cams[0]).toMatchObject({ lastEventAt: "2026-11-08T10:00:00Z", eventCount: 2 });
  });
  it("no events: no cameras (nothing invented)", () => {
    expect(deriveCameras([])).toEqual([]);
  });
});

describe("business vocabulary", () => {
  it("uses the exact French terms", () => {
    expect(alertStatusLabel("open")).toBe("Écart à vérifier");
    expect(alertStatusLabel("confirmed")).toBe("Confirmée");
    expect(alertStatusLabel("false_alarm")).toBe("Fausse alerte");
    expect(alertStatusLabel("auto_resolved")).toBe("Résolue automatiquement");
    expect(eventStateLabel("anomaly")).toBe("Écart à vérifier");
  });
  it("never uses accusatory wording", () => {
    const all = ["pending", "matched", "low_confidence", "anomaly", "confirmed", "false_alarm", "auto_resolved"].map(eventStateLabel);
    for (const label of all) expect(label.toLowerCase()).not.toMatch(/vol|fraude|preuve/);
  });
});

describe("relativeAge", () => {
  const now = new Date("2026-11-08T10:00:00Z");
  it("formats seconds, minutes, hours, days", () => {
    expect(relativeAge("2026-11-08T09:59:30Z", now)).toBe("il y a 30 s");
    expect(relativeAge("2026-11-08T09:50:00Z", now)).toBe("il y a 10 min");
    expect(relativeAge("2026-11-08T07:00:00Z", now)).toBe("il y a 3 h");
    expect(relativeAge("2026-11-01T10:00:00Z", now)).toBe("il y a 7 j");
  });
});

describe("daily summaries aggregation", () => {
  const row = (over: Partial<DailySummaryOut>): DailySummaryOut => ({
    day: "2026-11-07",
    category: "coffee",
    pos_qty: 10,
    cv_qty: 12,
    gap_qty: 2,
    loss_est: "20.00",
    loss_min: "18.00",
    loss_max: "22.00",
    loss_confirmed: "10.00",
    pending_count: 1,
    false_alarm_count: 0,
    is_final: true,
    ...over,
  });
  it("totals per category", () => {
    const t = totalsByCategory([row({}), row({ day: "2026-11-08", loss_est: "5.50", is_final: false })]);
    expect(t).toHaveLength(1);
    expect(t[0]).toMatchObject({ category: "coffee", cvQty: 24, posQty: 20, gapQty: 4, lossEst: "25.50" });
  });
  it("a day is final only if every category is final", () => {
    const t = totalsByDay([row({}), row({ category: "tea", is_final: false })]);
    expect(t[0]?.isFinal).toBe(false);
  });
});

describe("player state machine", () => {
  it("connects then goes live", () => {
    expect(nextPlayerState("unavailable", "loadstart")).toBe("connecting");
    expect(nextPlayerState("connecting", "playing")).toBe("live");
  });
  it("a stall while live is a reconnection, not an error", () => {
    expect(nextPlayerState("live", "waiting")).toBe("reconnecting");
    expect(nextPlayerState("reconnecting", "playing")).toBe("live");
  });
  it("errors and end of stream are surfaced", () => {
    expect(nextPlayerState("live", "error")).toBe("error");
    expect(nextPlayerState("live", "ended")).toBe("offline");
  });
});
