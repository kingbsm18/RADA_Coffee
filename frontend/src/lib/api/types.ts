/**
 * Mirrors the FastAPI response schemas (backend/app/schemas/*.py).
 * Decimal amounts are serialized as strings by FastAPI: they stay strings here and are
 * never used in floating-point arithmetic (loss figures are computed by the backend).
 */

export type Role = string;

export interface TokenOut {
  access_token: string;
  token_type: string;
  expires_in: number;
  role: Role;
}

export interface MeOut {
  id: string;
  username: string;
  role: Role;
  org_id: string;
}

export interface SiteOut {
  id: string;
  name: string;
  timezone: string;
  currency: string;
  active: boolean;
  created_at: string;
}

export const DETECTION_STATES = [
  "pending",
  "matched",
  "low_confidence",
  "anomaly",
  "confirmed",
  "false_alarm",
  "auto_resolved",
] as const;
export type DetectionState = (typeof DETECTION_STATES)[number];

export interface EventOut {
  id: string;
  event_id: string;
  site_id: string;
  camera_id: string;
  timestamp: string;
  category: string;
  count: number;
  confidence: number;
  snapshot_ref: string | null;
  model_version: string;
  state: DetectionState;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export const ALERT_STATUSES = ["open", "confirmed", "false_alarm", "auto_resolved"] as const;
export type AlertStatus = (typeof ALERT_STATUSES)[number];

export interface AlertOut {
  id: string;
  site_id: string;
  detection_id: string;
  category: string;
  subtype: string | null;
  missing_qty: number;
  loss_est: string;
  loss_min: string;
  loss_max: string;
  status: AlertStatus;
  strong: boolean;
  review_note: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface DailySummaryOut {
  day: string;
  category: string;
  pos_qty: number;
  cv_qty: number;
  gap_qty: number;
  loss_est: string;
  loss_min: string;
  loss_max: string;
  loss_confirmed: string;
  pending_count: number;
  false_alarm_count: number;
  is_final: boolean;
}

export interface HourlyPointOut {
  hour: number;
  category: string;
  pos_qty: number;
  cv_qty: number;
}

export interface WindowsOut {
  lookback: number;
  grace: number;
}

export interface SiteSettingsOut {
  site_id: string;
  confidence_threshold: number;
  windows: Record<string, WindowsOut>;
  snapshot_retention_days: number;
  snapshot_upload_policy: string;
  updated_at: string;
}

export interface ImportBatchOut {
  id: string;
  source: string;
  status: string;
  rows_received: number;
  rows_inserted: number;
  rows_updated: number;
  rows_unchanged: number;
  rows_rejected: number;
  started_at: string;
  completed_at: string | null;
}

export interface SnapshotItem {
  event_id: string;
  timestamp: string;
  category: string;
  confidence: number;
  state: DetectionState;
  url: string;
}

export interface HealthReady {
  status: string;
}

/** Message pushed on /ws/alerts (backend/app/services/notification.py). */
export type AlertSocketMessage =
  | { type: "ready" }
  | {
      type: "alert_created" | "alert_updated";
      alert: {
        id: string;
        site_id: string;
        category: string;
        subtype: string | null;
        missing_qty: number;
        loss_est: string;
        status: AlertStatus;
        strong: boolean;
        created_at: string;
      };
    };
