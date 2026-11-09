/**
 * Business vocabulary (French) and status mapping. Presentation only: no reconciliation,
 * no loss calculation (the backend is the source of truth).
 * A discrepancy is a signal to verify, never proof of theft or fraud.
 */
import type { AlertStatus, DetectionState } from "@/lib/api/types";

export type Tone = "neutral" | "success" | "warning" | "danger" | "info";

export const EVENT_STATE_LABEL: Record<DetectionState, string> = {
  pending: "En attente",
  matched: "Rapproché",
  low_confidence: "Confiance faible",
  anomaly: "Écart à vérifier",
  confirmed: "Confirmée",
  false_alarm: "Fausse alerte",
  auto_resolved: "Résolue automatiquement",
};

export const EVENT_STATE_TONE: Record<DetectionState, Tone> = {
  pending: "neutral",
  matched: "success",
  low_confidence: "warning",
  anomaly: "danger",
  confirmed: "danger",
  false_alarm: "neutral",
  auto_resolved: "info",
};

export const ALERT_STATUS_LABEL: Record<AlertStatus, string> = {
  open: "Écart à vérifier",
  confirmed: "Confirmée",
  false_alarm: "Fausse alerte",
  auto_resolved: "Résolue automatiquement",
};

export const ALERT_STATUS_TONE: Record<AlertStatus, Tone> = {
  open: "danger",
  confirmed: "danger",
  false_alarm: "neutral",
  auto_resolved: "info",
};

export const ALERT_SUBTYPE_LABEL: Record<string, string> = {
  cancelled_after_service: "Annulée après service",
};

export function eventStateLabel(state: string): string {
  return (EVENT_STATE_LABEL as Record<string, string>)[state] ?? state;
}
export function eventStateTone(state: string): Tone {
  return (EVENT_STATE_TONE as Record<string, Tone>)[state] ?? "neutral";
}
export function alertStatusLabel(status: string): string {
  return (ALERT_STATUS_LABEL as Record<string, string>)[status] ?? status;
}
export function alertStatusTone(status: string): Tone {
  return (ALERT_STATUS_TONE as Record<string, Tone>)[status] ?? "neutral";
}
