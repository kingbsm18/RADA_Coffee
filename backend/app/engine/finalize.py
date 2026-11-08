"""End-of-service recalculation (business rule R13).

After closing, every open anomaly is checked once more against the final set of
POS credits. If a credit now exists inside the anomaly's window, the anomaly
becomes ``auto_resolved``. Anomalies are never deleted and decisions already
taken by the manager (``confirmed`` / ``false_alarm``) are never touched.

Pure function: no database, no clock, no framework. The caller supplies the
data and ``now``, and persists the returned resolutions. Writing the daily
summaries is the job of ``services/summary_service.py``, not of this module.

Window rule (same as R6): a credit matches an anomaly unit when it has the same
site and category, is not consumed, and its SALE time lies in
``[det.ts - lookback, det.ts + grace]`` (both bounds inclusive). The import time
is never used, and ``now`` is never used as a bound. This corrects a POS sync
delay; a sale that really happened after the grace window stays an anomaly.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.engine.types import Credit, Detection, DetectionState, SiteSettings

AnomalySubtype = Literal["missing_sale", "cancelled_after_service"]
SUPPORTED_SUBTYPES = frozenset({"missing_sale", "cancelled_after_service"})


@dataclass(frozen=True, slots=True)
class AnomalyUnit:
    """One unserved-without-sale unit of a detection (``unit_index`` is 1-based)."""

    detection: Detection
    unit_index: int
    subtype: AnomalySubtype = "missing_sale"
    state: DetectionState = "anomaly"

    def __post_init__(self) -> None:
        if isinstance(self.unit_index, bool) or not isinstance(self.unit_index, int):
            raise TypeError("unit_index must be an integer")
        if not 1 <= self.unit_index <= self.detection.count:
            raise ValueError(
                f"unit_index must be between 1 and {self.detection.count}, "
                f"got {self.unit_index}"
            )
        if self.subtype not in SUPPORTED_SUBTYPES:
            raise ValueError(f"Unsupported anomaly subtype: {self.subtype!r}")

    @property
    def key(self) -> tuple[str, int]:
        return (self.detection.event_id, self.unit_index)


@dataclass(frozen=True, slots=True)
class Resolution:
    """An anomaly unit that must move to ``auto_resolved``, linked to its credit."""

    event_id: str
    unit_index: int
    credit_id: str
    new_state: Literal["auto_resolved"] = "auto_resolved"


@dataclass(frozen=True, slots=True)
class FinalizeResult:
    resolutions: tuple[Resolution, ...]
    remaining: tuple[AnomalyUnit, ...]
    finalized_at: datetime


def _validated_units(
    anomalies: Iterable[AnomalyUnit], site_id: str
) -> list[AnomalyUnit]:
    seen: set[tuple[str, int]] = set()
    units: list[AnomalyUnit] = []
    for unit in anomalies:
        if unit.state != "anomaly":
            raise ValueError(
                "finalize only accepts open anomalies; got state "
                f"{unit.state!r} for {unit.key!r}"
            )
        if unit.detection.site_id != site_id:
            raise ValueError(
                f"Anomaly {unit.key!r} belongs to site "
                f"{unit.detection.site_id!r}, expected {site_id!r}"
            )
        if unit.key in seen:
            raise ValueError(f"Duplicate anomaly unit {unit.key!r}")
        seen.add(unit.key)
        units.append(unit)
    # Oldest first, fully deterministic (same ordering rule as R6).
    units.sort(key=lambda u: (u.detection.timestamp, u.detection.event_id, u.unit_index))
    return units


def _free_credits_by_category(
    credits: Iterable[Credit], consumed_credit_ids: frozenset[str], site_id: str
) -> dict[str, list[Credit]]:
    unique: dict[str, Credit] = {}
    for credit in credits:
        existing = unique.get(credit.credit_id)
        if existing is None:
            unique[credit.credit_id] = credit
        elif existing != credit:
            raise ValueError(f"Conflicting credits share credit_id {credit.credit_id!r}")

    by_category: dict[str, list[Credit]] = {}
    for credit in unique.values():
        if credit.site_id != site_id or credit.credit_id in consumed_credit_ids:
            continue
        by_category.setdefault(credit.category, []).append(credit)
    for pool in by_category.values():
        pool.sort(key=lambda c: (c.timestamp, c.credit_id))  # oldest first
    return by_category


def finalize(
    anomalies: Iterable[AnomalyUnit],
    credits: Iterable[Credit],
    consumed_credit_ids: Iterable[str],
    settings: SiteSettings,
    now: datetime,
) -> FinalizeResult:
    """Resolve open anomalies that a late-synced sale now covers (R13).

    ``anomalies``: open anomaly units of ONE site (state must be ``anomaly``).
    ``credits``: credits built from the final POS data of that day.
    ``consumed_credit_ids``: credits already linked to a matched detection or to
    an earlier resolution; they can never be used twice.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    units = _validated_units(anomalies, settings.site_id)
    pools = _free_credits_by_category(
        credits, frozenset(consumed_credit_ids), settings.site_id
    )

    resolutions: list[Resolution] = []
    remaining: list[AnomalyUnit] = []

    for unit in units:
        det = unit.detection
        windows = settings.windows_for(det.category)  # raises if not configured
        start = det.timestamp - windows.lookback
        end = det.timestamp + windows.grace

        pool = pools.get(det.category, [])
        chosen_index = None
        for index, credit in enumerate(pool):  # sorted oldest first
            if credit.timestamp < start:
                continue
            if credit.timestamp > end:
                break
            chosen_index = index
            break

        if chosen_index is None:
            remaining.append(unit)
        else:
            credit = pool.pop(chosen_index)  # a credit resolves at most one unit
            resolutions.append(Resolution(det.event_id, unit.unit_index, credit.credit_id))

    return FinalizeResult(
        resolutions=tuple(resolutions),
        remaining=tuple(remaining),
        finalized_at=now,
    )
