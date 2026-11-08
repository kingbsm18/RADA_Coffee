"""Noise baseline of a café (business rule R12).

During shadow mode the system records, per category and per day, how many
anomalies appear even though nothing is wrong (camera misses, very late POS
sales, free items not rung up...). That is the café's normal "noise". A strong
alert (notification) is sent only when the day's anomaly count clearly exceeds
it. Every anomaly stays recorded and visible whatever this module decides.

Method (robust to a few odd days): median and MAD (median absolute deviation)
of the daily counts.

    threshold = median + max(k x 1.4826 x MAD, min_margin)
    notify    = count > threshold

Defaults (k=2, min_margin=2, min_days=7) are STARTING VALUES to be tuned with
real shadow-mode data. Daily counts must be the official ones, i.e. measured
after the end-of-service recalculation (R13).

Until a category has at least ``min_days`` of history it is "not calibrated"
and no notification is sent for it (anomalies are still recorded).

Pure module: no database, no clock, no framework.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

# Makes the MAD comparable to a standard deviation for roughly normal data.
MAD_SCALE = 1.4826

NotifyReason = Literal["above_baseline", "within_noise", "not_calibrated"]


@dataclass(frozen=True, slots=True)
class NoisePolicy:
    min_days: int = 7
    k: float = 2.0
    min_margin: float = 2.0

    def __post_init__(self) -> None:
        if isinstance(self.min_days, bool) or not isinstance(self.min_days, int):
            raise TypeError("min_days must be an integer")
        if self.min_days < 1:
            raise ValueError("min_days must be at least 1")
        if not self.k >= 0:
            raise ValueError("k cannot be negative")
        if not self.min_margin >= 0:
            raise ValueError("min_margin cannot be negative")


@dataclass(frozen=True, slots=True)
class NoiseBaseline:
    days: int
    median: float
    scaled_mad: float
    threshold: float
    calibrated: bool


@dataclass(frozen=True, slots=True)
class NotifyDecision:
    notify: bool
    reason: NotifyReason
    excess: float | None  # how far above the threshold; None if not calibrated


def _require_counts(counts: Sequence[int]) -> None:
    for value in counts:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("daily counts must be integers")
        if value < 0:
            raise ValueError("daily counts cannot be negative")


def compute_baseline(
    daily_counts: Sequence[int], policy: NoisePolicy | None = None
) -> NoiseBaseline:
    """Baseline from the daily anomaly counts of ONE category (one value per day)."""
    policy = policy or NoisePolicy()
    _require_counts(daily_counts)

    days = len(daily_counts)
    if days == 0:
        return NoiseBaseline(days=0, median=0.0, scaled_mad=0.0, threshold=0.0, calibrated=False)

    median = float(statistics.median(daily_counts))
    mad = float(statistics.median(abs(value - median) for value in daily_counts))
    scaled_mad = MAD_SCALE * mad
    threshold = median + max(policy.k * scaled_mad, policy.min_margin)

    return NoiseBaseline(
        days=days,
        median=median,
        scaled_mad=scaled_mad,
        threshold=threshold,
        calibrated=days >= policy.min_days,
    )


def compute_baselines(
    history: Mapping[str, Sequence[int]], policy: NoisePolicy | None = None
) -> dict[str, NoiseBaseline]:
    """One baseline per category."""
    return {category: compute_baseline(counts, policy) for category, counts in history.items()}


def should_notify(count: int, baseline: NoiseBaseline) -> NotifyDecision:
    """Decide whether the day's anomaly count deserves a strong alert (R12)."""
    if isinstance(count, bool) or not isinstance(count, int):
        raise TypeError("count must be an integer")
    if count < 0:
        raise ValueError("count cannot be negative")

    if not baseline.calibrated:
        return NotifyDecision(notify=False, reason="not_calibrated", excess=None)

    excess = count - baseline.threshold
    if excess > 0:
        return NotifyDecision(notify=True, reason="above_baseline", excess=excess)
    return NotifyDecision(notify=False, reason="within_noise", excess=excess)
