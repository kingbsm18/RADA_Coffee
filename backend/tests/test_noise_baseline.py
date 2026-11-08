"""Tests for noise_baseline — TODO."""
"""Tests for engine/noise_baseline.py (business rule R12, noise level per café).

Baseline = median and MAD of the daily anomaly counts of a category.
threshold = median + max(k x 1.4826 x MAD, min_margin); notify only when count > threshold.
"""

from __future__ import annotations

import random
from dataclasses import FrozenInstanceError

import pytest

from app.engine.noise_baseline import (
    MAD_SCALE,
    NoiseBaseline,
    NoisePolicy,
    NotifyDecision,
    compute_baseline,
    compute_baselines,
    should_notify,
)

STABLE = [1, 2, 1, 3, 2, 1, 2]  # median 2, MAD 1 -> threshold 2 + 2 x 1.4826 = 4.9652


# --- compute_baseline --------------------------------------------------------


def test_baseline_of_a_stable_week() -> None:
    baseline = compute_baseline(STABLE)
    assert baseline.days == 7
    assert baseline.median == 2.0
    assert baseline.scaled_mad == pytest.approx(MAD_SCALE)
    assert baseline.threshold == pytest.approx(2 + 2 * MAD_SCALE)
    assert baseline.calibrated is True


def test_empty_history_is_not_calibrated() -> None:
    assert compute_baseline([]) == NoiseBaseline(
        days=0, median=0.0, scaled_mad=0.0, threshold=0.0, calibrated=False
    )


def test_calibration_needs_min_days() -> None:
    assert compute_baseline([1, 2, 3, 1, 2, 3]).calibrated is False  # 6 days < 7
    assert compute_baseline([1, 2, 3, 1, 2, 3, 1]).calibrated is True  # exactly 7


def test_custom_min_days() -> None:
    policy = NoisePolicy(min_days=3)
    assert compute_baseline([1, 2], policy).calibrated is False
    assert compute_baseline([1, 2, 3], policy).calibrated is True


def test_all_zero_history_uses_the_margin_floor() -> None:
    baseline = compute_baseline([0] * 7)
    assert baseline.median == 0.0 and baseline.scaled_mad == 0.0
    assert baseline.threshold == 2.0  # min_margin


def test_constant_history_threshold_is_median_plus_margin() -> None:
    assert compute_baseline([5] * 7).threshold == 7.0


def test_one_odd_day_barely_moves_the_threshold() -> None:
    assert compute_baseline([0, 0, 0, 0, 0, 0, 40]).threshold == 2.0


def test_median_of_an_even_number_of_days() -> None:
    assert compute_baseline([1, 2, 3, 4]).median == 2.5


def test_order_of_days_does_not_matter() -> None:
    shuffled = STABLE.copy()
    random.Random(0).shuffle(shuffled)
    assert compute_baseline(shuffled) == compute_baseline(STABLE)


def test_accepts_any_sequence_and_does_not_mutate_it() -> None:
    history = list(STABLE)
    compute_baseline(history)
    assert history == STABLE
    assert compute_baseline(tuple(STABLE)) == compute_baseline(STABLE)


def test_k_controls_the_distance_above_the_median() -> None:
    assert compute_baseline(STABLE, NoisePolicy(k=0)).threshold == 4.0  # median 2 + margin 2
    low = compute_baseline(STABLE, NoisePolicy(k=1)).threshold
    high = compute_baseline(STABLE, NoisePolicy(k=4)).threshold
    assert low < high
    assert high == pytest.approx(2 + 4 * MAD_SCALE)


def test_min_margin_is_a_floor_not_an_addition() -> None:
    # k x scaled_mad = 2.9652 > margin 2: the larger of the two applies.
    assert compute_baseline(STABLE).threshold == pytest.approx(2 + 2 * MAD_SCALE)
    assert compute_baseline(STABLE, NoisePolicy(min_margin=10)).threshold == 12.0


# --- should_notify -----------------------------------------------------------


def test_count_below_the_threshold_is_noise() -> None:
    decision = should_notify(4, compute_baseline(STABLE))
    assert decision.notify is False
    assert decision.reason == "within_noise"
    assert decision.excess == pytest.approx(4 - (2 + 2 * MAD_SCALE))


def test_count_above_the_threshold_notifies() -> None:
    decision = should_notify(5, compute_baseline(STABLE))
    assert decision.notify is True
    assert decision.reason == "above_baseline"
    assert decision.excess is not None and decision.excess > 0


def test_count_exactly_on_the_threshold_does_not_notify() -> None:
    baseline = compute_baseline([0] * 7)  # threshold 2.0
    assert should_notify(2, baseline) == NotifyDecision(False, "within_noise", 0.0)
    assert should_notify(3, baseline).notify is True


def test_zero_anomalies_never_notify() -> None:
    assert should_notify(0, compute_baseline(STABLE)).notify is False


def test_uncalibrated_baseline_never_notifies() -> None:
    decision = should_notify(500, compute_baseline([1, 2, 3]))
    assert decision == NotifyDecision(notify=False, reason="not_calibrated", excess=None)


def test_empty_baseline_never_notifies() -> None:
    assert should_notify(10, compute_baseline([])).reason == "not_calibrated"


def test_decision_is_monotonic_in_the_count() -> None:
    baseline = compute_baseline(STABLE)
    decisions = [should_notify(count, baseline).notify for count in range(0, 15)]
    assert decisions == sorted(decisions)  # once True, stays True


# --- compute_baselines -------------------------------------------------------


def test_one_baseline_per_category_and_independent() -> None:
    history = {"coffee": STABLE, "soft_drink": [0] * 7}
    baselines = compute_baselines(history)
    assert set(baselines) == {"coffee", "soft_drink"}
    assert baselines["coffee"] == compute_baseline(STABLE)
    assert baselines["soft_drink"] == compute_baseline([0] * 7)
    assert baselines["coffee"].threshold > baselines["soft_drink"].threshold


def test_policy_is_shared_by_all_categories() -> None:
    baselines = compute_baselines({"a": [1] * 3, "b": [2] * 3}, NoisePolicy(min_days=3))
    assert all(b.calibrated for b in baselines.values())


def test_empty_history_mapping() -> None:
    assert compute_baselines({}) == {}


# --- validation --------------------------------------------------------------


def test_negative_daily_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        compute_baseline([1, -1, 2])


@pytest.mark.parametrize("bad", [1.5, "2", None, True])
def test_non_integer_daily_count_is_rejected(bad: object) -> None:
    with pytest.raises(TypeError, match="integers"):
        compute_baseline([1, bad, 2])  # type: ignore[list-item]


def test_should_notify_validates_the_count() -> None:
    baseline = compute_baseline(STABLE)
    with pytest.raises(ValueError, match="negative"):
        should_notify(-1, baseline)
    for bad in (1.5, "3", True):
        with pytest.raises(TypeError, match="integer"):
            should_notify(bad, baseline)  # type: ignore[arg-type]


@pytest.mark.parametrize("min_days", [0, -3])
def test_policy_min_days_must_be_positive(min_days: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        NoisePolicy(min_days=min_days)


@pytest.mark.parametrize("min_days", [7.0, "7", True])
def test_policy_min_days_must_be_an_integer(min_days: object) -> None:
    with pytest.raises(TypeError, match="integer"):
        NoisePolicy(min_days=min_days)  # type: ignore[arg-type]


def test_policy_k_and_margin_cannot_be_negative_or_nan() -> None:
    for bad in (-0.1, float("nan")):
        with pytest.raises(ValueError, match="k cannot be negative"):
            NoisePolicy(k=bad)
        with pytest.raises(ValueError, match="min_margin cannot be negative"):
            NoisePolicy(min_margin=bad)


def test_default_policy_values() -> None:
    policy = NoisePolicy()
    assert (policy.min_days, policy.k, policy.min_margin) == (7, 2.0, 2.0)


def test_results_are_immutable() -> None:
    baseline = compute_baseline(STABLE)
    with pytest.raises(FrozenInstanceError):
        baseline.threshold = 0.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        NoisePolicy().k = 1.0  # type: ignore[misc]
