"""CSV exports. Text cells are neutralized against spreadsheet formula injection."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence

from app.services.summary_service import DailyRow

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def _write(header: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([safe_cell(cell) for cell in row])
    return buffer.getvalue()


def daily_summary_csv(rows: Iterable[DailyRow]) -> str:
    return _write(
        (
            "day", "category", "pos_qty", "cv_qty", "gap_qty", "loss_est", "loss_min",
            "loss_max", "loss_confirmed", "pending_count", "false_alarm_count", "is_final",
        ),
        (
            (
                r.day.isoformat(), r.category, r.pos_qty, r.cv_qty, r.gap_qty, r.loss_est,
                r.loss_min, r.loss_max, r.loss_confirmed, r.pending_count,
                r.false_alarm_count, int(r.is_final),
            )
            for r in rows
        ),
    )
