import type { DailySummaryOut } from "@/lib/api/types";
import { sumMoney } from "@/lib/domain/money";

export interface CategoryTotals {
  category: string;
  cvQty: number;
  posQty: number;
  gapQty: number;
  lossEst: string;
  lossConfirmed: string;
  pendingCount: number;
}

export interface DayTotals {
  day: string;
  cvQty: number;
  posQty: number;
  gapQty: number;
  lossEst: string;
  lossConfirmed: string;
  isFinal: boolean;
}

/** Display aggregation of backend daily summaries (no loss recomputation). */
export function totalsByCategory(rows: readonly DailySummaryOut[]): CategoryTotals[] {
  const groups = new Map<string, DailySummaryOut[]>();
  for (const r of rows) groups.set(r.category, [...(groups.get(r.category) ?? []), r]);
  return [...groups.entries()]
    .map(([category, list]) => ({
      category,
      cvQty: list.reduce((n, r) => n + r.cv_qty, 0),
      posQty: list.reduce((n, r) => n + r.pos_qty, 0),
      gapQty: list.reduce((n, r) => n + r.gap_qty, 0),
      lossEst: sumMoney(list.map((r) => r.loss_est)),
      lossConfirmed: sumMoney(list.map((r) => r.loss_confirmed)),
      pendingCount: list.reduce((n, r) => n + r.pending_count, 0),
    }))
    .sort((a, b) => a.category.localeCompare(b.category));
}

export function totalsByDay(rows: readonly DailySummaryOut[]): DayTotals[] {
  const groups = new Map<string, DailySummaryOut[]>();
  for (const r of rows) groups.set(r.day, [...(groups.get(r.day) ?? []), r]);
  return [...groups.entries()]
    .map(([day, list]) => ({
      day,
      cvQty: list.reduce((n, r) => n + r.cv_qty, 0),
      posQty: list.reduce((n, r) => n + r.pos_qty, 0),
      gapQty: list.reduce((n, r) => n + r.gap_qty, 0),
      lossEst: sumMoney(list.map((r) => r.loss_est)),
      lossConfirmed: sumMoney(list.map((r) => r.loss_confirmed)),
      isFinal: list.every((r) => r.is_final),
    }))
    .sort((a, b) => b.day.localeCompare(a.day));
}
