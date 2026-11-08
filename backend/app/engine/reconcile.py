"""Reconcile detected items with POS credits (rules R2, R5, R6, R7, R9).

Pure and deterministic: no clock, no database. The caller passes ``now`` and the
site settings, and persists the returned matches/states.

- R2: matching is per category, never per order.
- R5/R6: each detected unit takes the OLDEST free credit of its category whose SALE
  time is inside ``[det.ts - lookback, min(now, det.ts + grace)]`` (both ends
  inclusive). Detections are processed oldest first.
- R7: no verdict before ``det.ts + grace``. At that instant, units still unmatched
  make an anomaly (R9: ``low_confidence`` instead when below the site threshold).
- A credit is consumed once; unused credits are ignored (R1).

R8 (cancelled sales) and R13 (late sales) are handled in cancellations.py / finalize.py.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.engine.types import Credit, Detection, SiteSettings

OutcomeState = Literal["pending", "matched", "anomaly", "low_confidence"]


@dataclass(frozen=True, slots=True)
class UnitMatch:
    """One detected unit linked to one credit."""

    event_id: str
    unit_index: int  # 1..count
    credit_id: str


@dataclass(frozen=True, slots=True)
class DetectionOutcome:
    event_id: str
    state: OutcomeState
    new_matches: tuple[UnitMatch, ...]  # created by THIS call (persist them)
    matched_qty: int  # units matched so far, earlier links included
    missing_qty: int  # units without a credit (> 0 for pending/anomaly/low_confidence)


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    outcomes: tuple[DetectionOutcome, ...]
    skipped: tuple[str, ...]  # event ids whose category has no configured windows


def reconcile(
    detections: Iterable[Detection],
    credits: Iterable[Credit],
    links: Sequence[UnitMatch],
    settings: SiteSettings,
    *,
    now: datetime,
) -> ReconcileResult:
    """Evaluate open detections of ``settings.site_id``.

    ``links`` are the matches already persisted (any detection): their credits are
    not free, and their units are not matched again. Credits of other sites are ignored.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    consumed = {link.credit_id for link in links}
    matched_units: dict[str, set[int]] = defaultdict(set)
    for link in links:
        matched_units[link.event_id].add(link.unit_index)

    pool: dict[str, list[Credit]] = defaultdict(list)
    for credit in sorted(
        (c for c in credits if c.site_id == settings.site_id and c.credit_id not in consumed),
        key=lambda c: (c.timestamp, c.sale_id, c.unit_index),
    ):
        pool[credit.category].append(credit)
    pool_times = {category: [c.timestamp for c in items] for category, items in pool.items()}

    used: set[str] = set()
    outcomes: list[DetectionOutcome] = []
    skipped: list[str] = []

    for detection in sorted(detections, key=lambda d: (d.timestamp, d.event_id)):
        if detection.site_id != settings.site_id:
            raise ValueError(
                f"detection {detection.event_id!r} belongs to site {detection.site_id!r}, "
                f"not {settings.site_id!r}"
            )
        try:
            windows = settings.windows_for(detection.category)
        except ValueError:
            skipped.append(detection.event_id)  # stays pending, visible to the caller
            continue

        deadline = detection.timestamp + windows.grace
        start = detection.timestamp - windows.lookback
        end = min(now, deadline)  # never an open upper bound

        already = matched_units.get(detection.event_id, set())
        new_matches: list[UnitMatch] = []
        candidates = pool.get(detection.category, [])
        times = pool_times.get(detection.category, [])

        for unit_index in range(1, detection.count + 1):
            if unit_index in already:
                continue
            credit = _oldest_free(candidates, times, used, start, end)
            if credit is None:
                break  # same window for every remaining unit: nothing more to find
            used.add(credit.credit_id)
            new_matches.append(UnitMatch(detection.event_id, unit_index, credit.credit_id))

        matched_qty = len(already) + len(new_matches)
        missing_qty = detection.count - matched_qty
        if missing_qty == 0:
            state: OutcomeState = "matched"
        elif now < deadline:
            state = "pending"
        elif detection.confidence >= settings.confidence_threshold:
            state = "anomaly"
        else:
            state = "low_confidence"
        outcomes.append(
            DetectionOutcome(detection.event_id, state, tuple(new_matches), matched_qty, missing_qty)
        )

    return ReconcileResult(tuple(outcomes), tuple(skipped))


def _oldest_free(
    candidates: list[Credit],
    times: list[datetime],
    used: set[str],
    start: datetime,
    end: datetime,
) -> Credit | None:
    index = bisect_left(times, start)
    while index < len(candidates) and times[index] <= end:
        if candidates[index].credit_id not in used:
            return candidates[index]
        index += 1
    return None
