"""Reconciliation rules R2, R5-R7, R9 (cancellations R8 and the end-of-service R13
recalculation live in cancellations.py / finalize.py)."""

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.engine.credits import build_credits
from app.engine.reconcile import UnitMatch, reconcile
from app.engine.types import CategoryWindows, Detection, SaleRecord, SiteSettings

UTC = timezone.utc
T0 = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
LOOKBACK, GRACE = timedelta(minutes=25), timedelta(minutes=12)
SETTINGS = SiteSettings(
    "cafe-01",
    0.6,
    {
        "coffee": CategoryWindows(LOOKBACK, GRACE),
        "soft_drink": CategoryWindows(timedelta(minutes=10), timedelta(minutes=7)),
    },
)


def det(event_id="e1", when=T0, category="coffee", count=1, confidence=0.9) -> Detection:
    return Detection(event_id, "cafe-01", when, category, count, confidence)


def credits_at(*offsets_minutes, category="coffee", price="25.00", base=T0, prefix="s"):
    return build_credits(
        SaleRecord("cafe-01", f"{prefix}{i}", base + timedelta(minutes=m), category, 1, Decimal(price), "paid")
        for i, m in enumerate(offsets_minutes)
    )


def run(detections, credits, *, now, links=()):
    return reconcile(detections, credits, links, SETTINGS, now=now)


def only(result):
    assert len(result.outcomes) == 1
    return result.outcomes[0]


# ------------------------------------------------------------------ happy paths
def test_sale_before_the_detection_matches_immediately() -> None:
    outcome = only(run([det()], credits_at(-5), now=T0))
    assert outcome.state == "matched" and outcome.missing_qty == 0
    assert [m.unit_index for m in outcome.new_matches] == [1]


def test_detection_then_sale_inside_the_grace_matches_when_the_sale_arrives() -> None:
    assert only(run([det()], [], now=T0 + timedelta(minutes=5))).state == "pending"
    outcome = only(run([det()], credits_at(8), now=T0 + timedelta(minutes=9)))
    assert outcome.state == "matched"


def test_no_sale_stays_pending_until_the_deadline_then_becomes_an_anomaly() -> None:
    before = only(run([det()], [], now=T0 + GRACE - timedelta(seconds=1)))
    assert before.state == "pending" and before.missing_qty == 1  # R7: absence means nothing yet
    at_deadline = only(run([det()], [], now=T0 + GRACE))
    assert at_deadline.state == "anomaly" and at_deadline.missing_qty == 1


# ------------------------------------------------------------------ window bounds (R5, R6)
@pytest.mark.parametrize(
    "offset,expected",
    [
        (-LOOKBACK, "matched"),  # exact lower bound is inside
        (-LOOKBACK - timedelta(microseconds=1), "anomaly"),  # too old
        (GRACE, "matched"),  # exact upper bound is inside
        (GRACE + timedelta(microseconds=1), "anomaly"),  # too late
        (timedelta(0), "matched"),
    ],
)
def test_window_boundaries(offset, expected) -> None:
    credit = build_credits([SaleRecord("cafe-01", "s", T0 + offset, "coffee", 1, Decimal("25"), "paid")])
    assert only(run([det()], credit, now=T0 + GRACE + timedelta(hours=1))).state == expected


def test_the_upper_bound_is_capped_at_now() -> None:
    """A sale 'in the future' relative to now must not be used (never use now as an open bound)."""
    future_sale = credits_at(10)
    assert only(run([det()], future_sale, now=T0 + timedelta(minutes=2))).state == "pending"


def test_a_sale_arriving_after_the_deadline_is_not_matched_here() -> None:
    """Late-synced sales are handled by the end-of-service recalculation (R13), not by this function."""
    result = only(run([det()], credits_at(5), now=T0 + GRACE))  # sale exists but...
    assert result.state == "matched"
    late = only(run([det()], credits_at(GRACE.total_seconds() / 60 + 5), now=T0 + GRACE + timedelta(minutes=10)))
    assert late.state == "anomaly"


# ------------------------------------------------------------------ categories (R2)
def test_categories_never_cross_match() -> None:
    soda_credit = credits_at(-1, category="soft_drink")
    assert only(run([det(category="coffee")], soda_credit, now=T0 + GRACE)).state == "anomaly"


def test_mixed_orders_are_compared_per_category_not_per_order() -> None:
    credits = credits_at(-20, category="coffee") + credits_at(-1, category="soft_drink", prefix="d")
    detections = [det("c", T0, "coffee"), det("d", T0 + timedelta(minutes=9), "soft_drink")]
    outcomes = {o.event_id: o.state for o in run(detections, credits, now=T0 + timedelta(hours=1)).outcomes}
    assert outcomes == {"c": "matched", "d": "matched"}


def test_the_credit_price_does_not_matter_free_items_match_too() -> None:
    free = credits_at(-2, price="0.00")
    assert only(run([det()], free, now=T0)).state == "matched"


# ------------------------------------------------------------------ one credit, one use
def test_two_detections_one_sale_the_oldest_detection_wins() -> None:
    detections = [det("late", T0 + timedelta(minutes=3)), det("early", T0)]
    outcomes = {o.event_id: o for o in run(detections, credits_at(-1), now=T0 + timedelta(hours=1)).outcomes}
    assert outcomes["early"].state == "matched" and outcomes["late"].state == "anomaly"


def test_each_detection_takes_the_oldest_free_credit() -> None:
    credits = credits_at(-10, -3)
    first, second = run([det("a", T0), det("b", T0 + timedelta(minutes=1))], credits, now=T0 + timedelta(hours=1)).outcomes
    assert first.new_matches[0].credit_id == credits[0].credit_id
    assert second.new_matches[0].credit_id == credits[1].credit_id


def test_credits_already_linked_are_not_reused() -> None:
    credits = credits_at(-5)
    links = [UnitMatch("other", 1, credits[0].credit_id)]
    assert only(run([det()], credits, now=T0 + GRACE, links=links)).state == "anomaly"


def test_an_unused_credit_creates_no_outcome_and_no_loss() -> None:
    """R1: a sale without a detected item is ignored."""
    result = run([], credits_at(0, 1, 2), now=T0 + timedelta(hours=1))
    assert result.outcomes == () and result.skipped == ()


# ------------------------------------------------------------------ count > 1 (units)
def test_count_three_with_two_credits_matches_two_units_and_reports_one_missing() -> None:
    waiting = only(run([det(count=3)], credits_at(-3, -2), now=T0))
    assert waiting.state == "pending" and len(waiting.new_matches) == 2 and waiting.missing_qty == 1
    done = only(run([det(count=3)], credits_at(-3, -2), now=T0 + GRACE))
    assert done.state == "anomaly" and done.missing_qty == 1 and done.matched_qty == 2


def test_count_three_with_three_credits_is_matched() -> None:
    outcome = only(run([det(count=3)], credits_at(-3, -2, -1), now=T0))
    assert outcome.state == "matched" and [m.unit_index for m in outcome.new_matches] == [1, 2, 3]


def test_a_partially_matched_detection_continues_with_the_remaining_units() -> None:
    credits = credits_at(-3, -2, -1)
    links = [UnitMatch("e1", 1, credits[0].credit_id)]
    outcome = only(run([det(count=3)], credits, now=T0, links=links))
    assert [m.unit_index for m in outcome.new_matches] == [2, 3] and outcome.state == "matched"
    assert outcome.matched_qty == 3


# ------------------------------------------------------------------ low confidence (R9)
@pytest.mark.parametrize(
    "confidence,expected", [(0.59, "low_confidence"), (0.6, "anomaly"), (0.61, "anomaly")]
)
def test_confidence_threshold(confidence, expected) -> None:
    assert only(run([det(confidence=confidence)], [], now=T0 + GRACE)).state == expected


def test_low_confidence_is_never_pending_forever_and_never_an_anomaly() -> None:
    assert only(run([det(confidence=0.1)], [], now=T0 + timedelta(minutes=1))).state == "pending"
    assert only(run([det(confidence=0.1)], [], now=T0 + GRACE)).state == "low_confidence"


def test_low_confidence_with_a_matching_sale_is_simply_matched() -> None:
    assert only(run([det(confidence=0.1)], credits_at(-1), now=T0)).state == "matched"


# ------------------------------------------------------------------ determinism & idempotence
def test_result_does_not_depend_on_input_order() -> None:
    detections = [det(f"e{i}", T0 + timedelta(minutes=i), count=1 + i % 2) for i in range(8)]
    credits = credits_at(*range(-10, 6, 2))
    expected = run(detections, credits, now=T0 + timedelta(hours=1))
    for seed in range(5):
        shuffled_d, shuffled_c = detections[:], list(credits)
        random.Random(seed).shuffle(shuffled_d)
        random.Random(seed).shuffle(shuffled_c)
        assert run(shuffled_d, shuffled_c, now=T0 + timedelta(hours=1)) == expected


def test_running_again_with_the_links_applied_changes_nothing() -> None:
    detections = [det("a", T0, count=2), det("b", T0 + timedelta(minutes=2))]
    credits = credits_at(-4, -1)
    now = T0 + timedelta(hours=1)
    first = run(detections, credits, now=now)
    links = [m for o in first.outcomes for m in o.new_matches]
    second = run(detections, credits, now=now, links=links)
    assert all(not o.new_matches for o in second.outcomes)
    assert [(o.event_id, o.state, o.missing_qty) for o in second.outcomes] == [
        (o.event_id, o.state, o.missing_qty) for o in first.outcomes
    ]


def test_same_inputs_same_outputs_repeatedly() -> None:
    args = ([det()], credits_at(-1))
    assert run(*args, now=T0) == run(*args, now=T0)


# ------------------------------------------------------------------ guards
def test_unknown_category_is_skipped_not_fatal() -> None:
    result = run([det("x", category="tea"), det("ok")], credits_at(-1), now=T0)
    assert result.skipped == ("x",) and [o.event_id for o in result.outcomes] == ["ok"]


def test_other_sites_are_rejected_or_ignored() -> None:
    foreign_detection = Detection("e", "cafe-02", T0, "coffee", 1, 0.9)
    with pytest.raises(ValueError, match="site"):
        run([foreign_detection], [], now=T0)
    foreign_credit = build_credits([SaleRecord("cafe-02", "s", T0, "coffee", 1, Decimal("25"), "paid")])
    assert only(run([det()], foreign_credit, now=T0 + GRACE)).state == "anomaly"


def test_now_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        run([det()], [], now=datetime(2026, 11, 5, 10, 0))


def test_detection_times_with_other_utc_offsets_compare_by_instant() -> None:
    plus_one = timezone(timedelta(hours=1))
    local = det(when=datetime(2026, 11, 5, 11, 0, tzinfo=plus_one))  # == 10:00 UTC
    assert only(run([local], credits_at(-5), now=T0)).state == "matched"
