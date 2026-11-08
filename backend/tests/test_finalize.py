"""Tests for finalize — TODO."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.engine.credits import build_credits
from app.engine.finalize import AnomalyUnit, finalize
from app.engine.types import (
    CategoryWindows,
    Credit,
    Detection,
    SaleRecord,
    SiteSettings,
)

T0 = datetime(2026, 11, 5, 10, 30, tzinfo=UTC)  # detection time used by most tests
NOW = datetime(2026, 11, 5, 23, 0, tzinfo=UTC)

SETTINGS = SiteSettings(
    site_id="cafe-01",
    confidence_threshold=0.7,
    windows={
        "coffee": CategoryWindows(lookback=timedelta(minutes=20), grace=timedelta(minutes=10)),
        "soft_drink": CategoryWindows(lookback=timedelta(minutes=10), grace=timedelta(minutes=5)),
    },
)


def det(
    event_id: str = "ev-1",
    *,
    ts: datetime = T0,
    category: str = "coffee",
    count: int = 1,
    site_id: str = "cafe-01",
) -> Detection:
    return Detection(
        event_id=event_id, site_id=site_id, timestamp=ts,
        category=category, count=count, confidence=0.9,
    )


def anomaly(event_id: str = "ev-1", unit_index: int = 1, **kwargs) -> AnomalyUnit:
    state = kwargs.pop("state", "anomaly")
    subtype = kwargs.pop("subtype", "missing_sale")
    return AnomalyUnit(
        detection=det(event_id, **kwargs), unit_index=unit_index, subtype=subtype, state=state
    )


def credits_at(*offsets_min: int, category="coffee", site_id="cafe-01", prefix="s"):
    """One credit per offset (minutes relative to T0), via the real build_credits."""
    sales = [
        SaleRecord(
            site_id=site_id, external_id=f"{prefix}{i}",
            timestamp=T0 + timedelta(minutes=off), category=category,
            quantity=1, unit_price=Decimal("12.50"), status="paid",
        )
        for i, off in enumerate(offsets_min)
    ]
    return build_credits(sales)


def run(anomalies, credits, consumed=(), now=NOW):
    return finalize(anomalies, credits, consumed, SETTINGS, now)


def test_sale_in_window_resolves_anomaly() -> None:
    credits = credits_at(5)  # synced late but inside [T0-20, T0+10]
    result = run([anomaly()], credits)
    assert [(r.event_id, r.unit_index, r.credit_id) for r in result.resolutions] == [
        ("ev-1", 1, credits[0].credit_id)
    ]
    assert result.resolutions[0].new_state == "auto_resolved"
    assert result.remaining == ()
    assert result.finalized_at == NOW


def test_no_credit_keeps_anomaly() -> None:
    result = run([anomaly()], ())
    assert result.resolutions == ()
    assert [u.key for u in result.remaining] == [("ev-1", 1)]


def test_window_bounds_are_inclusive() -> None:
    assert run([anomaly()], credits_at(-20)).resolutions  # exactly lookback
    assert run([anomaly()], credits_at(10)).resolutions  # exactly grace


def test_sale_just_outside_window_does_not_resolve() -> None:
    assert not run([anomaly()], credits_at(-21)).resolutions  # too old
    assert not run([anomaly()], credits_at(11)).resolutions  # beyond grace


def test_other_category_does_not_resolve() -> None:
    assert not run([anomaly()], credits_at(0, category="soft_drink")).resolutions


def test_other_site_credit_is_ignored() -> None:
    assert not run([anomaly()], credits_at(0, site_id="cafe-02")).resolutions


def test_already_consumed_credit_is_not_reused() -> None:
    credits = credits_at(0)
    result = run([anomaly()], credits, consumed={credits[0].credit_id})
    assert result.resolutions == ()
    assert len(result.remaining) == 1


def test_one_credit_resolves_only_one_anomaly_oldest_first() -> None:
    credits = credits_at(0)
    older = anomaly("ev-old", ts=T0 - timedelta(minutes=2))
    newer = anomaly("ev-new", ts=T0)
    result = run([newer, older], credits)  # given in reverse order on purpose
    assert [r.event_id for r in result.resolutions] == ["ev-old"]
    assert [u.detection.event_id for u in result.remaining] == ["ev-new"]


def test_result_does_not_depend_on_input_order() -> None:
    credits = credits_at(0, 1)
    units = [anomaly("a", ts=T0), anomaly("b", ts=T0 + timedelta(minutes=1)), anomaly("c", ts=T0 + timedelta(minutes=2))]
    forward = run(units, credits)
    backward = run(list(reversed(units)), list(reversed(credits)))
    assert forward == backward


def test_units_of_one_detection_are_resolved_individually() -> None:
    credits = credits_at(0, 1)  # 2 credits for a count=3 detection
    units = [anomaly("ev-1", i, count=3) for i in (1, 2, 3)]
    result = run(units, credits)
    assert [(r.event_id, r.unit_index) for r in result.resolutions] == [("ev-1", 1), ("ev-1", 2)]
    assert [u.key for u in result.remaining] == [("ev-1", 3)]


def test_cancelled_after_service_is_resolved_by_replacement_sale() -> None:
    result = run([anomaly(subtype="cancelled_after_service")], credits_at(3))
    assert len(result.resolutions) == 1


def test_is_idempotent() -> None:
    credits = credits_at(0)
    units = [anomaly("a"), anomaly("b")]
    first = run(units, credits)
    assert first == run(units, credits)  # same input, same output
    consumed = {r.credit_id for r in first.resolutions}
    second = run(first.remaining, credits, consumed=consumed)  # re-run on persisted state
    assert second.resolutions == ()
    assert second.remaining == first.remaining


def test_empty_input() -> None:
    result = run([], ())
    assert result.resolutions == () and result.remaining == ()


@pytest.mark.parametrize("state", ["confirmed", "false_alarm", "auto_resolved", "pending", "matched"])
def test_only_open_anomalies_are_accepted(state: str) -> None:
    with pytest.raises(ValueError, match="state"):
        run([anomaly(state=state)], credits_at(0))


def test_anomaly_from_another_site_is_rejected() -> None:
    with pytest.raises(ValueError, match="site"):
        run([anomaly(site_id="cafe-02")], ())


def test_duplicate_anomaly_unit_is_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        run([anomaly(), anomaly()], ())


@pytest.mark.parametrize("unit_index", [0, 2, -1])
def test_unit_index_must_be_within_detection_count(unit_index: int) -> None:
    with pytest.raises(ValueError, match="unit_index"):
        anomaly(unit_index=unit_index)  # count defaults to 1


def test_unknown_subtype_is_rejected() -> None:
    with pytest.raises(ValueError, match="subtype"):
        anomaly(subtype="theft")


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        run([anomaly()], (), now=datetime(2026, 11, 5, 23, 0))


def test_category_without_windows_fails_loudly() -> None:
    with pytest.raises(ValueError, match="No windows configured"):
        run([anomaly(category="juice")], ())


def test_conflicting_duplicate_credit_ids_are_rejected() -> None:
    good = credits_at(0)[0]
    clash = Credit(
        credit_id=good.credit_id, site_id=good.site_id, sale_id="other", unit_index=1,
        timestamp=good.timestamp + timedelta(minutes=1), category="coffee",
        unit_price=Decimal(10),
    )
    with pytest.raises(ValueError, match="credit_id"):
        run([anomaly()], [good, clash])
