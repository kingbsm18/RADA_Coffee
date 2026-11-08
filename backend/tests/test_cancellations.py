"""Tests for engine/cancellations.py (business rule R8).

When a POS sale that served as a credit becomes voided or refunded, the credit is
unlinked and every detection unit it covered becomes an anomaly with subtype
``cancelled_after_service``. Pure function: the caller persists the result.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.engine.cancellations import CancellationMatch, CancellationResult, handle_cancellation
from app.engine.credits import build_credits
from app.engine.finalize import AnomalyUnit, finalize
from app.engine.types import CategoryWindows, Detection, SaleRecord, SiteSettings

UTC = timezone.utc
T0 = datetime(2026, 11, 5, 10, 30, tzinfo=UTC)
SITE = "cafe-01"


def make_sale(
    external_id: str = "s1",
    *,
    status: str = "paid",
    quantity: int = 1,
    site_id: str = SITE,
    category: str = "coffee",
    offset_min: int = 0,
) -> SaleRecord:
    return SaleRecord(
        site_id=site_id,
        external_id=external_id,
        timestamp=T0 + timedelta(minutes=offset_min),
        category=category,
        quantity=quantity,
        unit_price=Decimal("12.50"),
        status=status,  # type: ignore[arg-type]
    )


def make_detection(
    event_id: str = "ev-1",
    *,
    offset_min: int = 0,
    count: int = 1,
    site_id: str = SITE,
    category: str = "coffee",
) -> Detection:
    return Detection(
        event_id=event_id,
        site_id=site_id,
        timestamp=T0 + timedelta(minutes=offset_min),
        category=category,
        count=count,
        confidence=0.9,
    )


def make_matches(sale: SaleRecord, detection: Detection) -> list[CancellationMatch]:
    """Link each unit of ``detection`` to one credit of the (originally paid) ``sale``."""
    paid = replace(sale, status="paid")
    credits = build_credits([paid])
    return [
        CancellationMatch(detection=detection, unit_index=i + 1, credit=credit)
        for i, credit in enumerate(credits[: detection.count])
    ]


def cancelled(sale_id: str = "s1", status: str = "voided", **kwargs) -> SaleRecord:
    return make_sale(sale_id, status=status, **kwargs)


# --- the nominal case --------------------------------------------------------


def test_voided_sale_unlinks_its_credit_and_creates_an_anomaly() -> None:
    sale, det = make_sale(), make_detection()
    matches = make_matches(sale, det)

    result = handle_cancellation(cancelled(), matches)

    assert result.unlinked_credit_ids == (matches[0].credit.credit_id,)
    assert result.anomalies == (
        AnomalyUnit(detection=det, unit_index=1, subtype="cancelled_after_service", state="anomaly"),
    )


def test_refunded_sale_behaves_like_a_voided_one() -> None:
    matches = make_matches(make_sale(), make_detection())
    result = handle_cancellation(cancelled(status="refunded"), matches)
    assert len(result.anomalies) == 1
    assert result.anomalies[0].subtype == "cancelled_after_service"


def test_anomalies_are_open_and_keep_the_original_detection() -> None:
    det = make_detection()
    result = handle_cancellation(cancelled(), make_matches(make_sale(), det))
    unit = result.anomalies[0]
    assert unit.state == "anomaly"
    assert unit.detection is det
    assert unit.key == ("ev-1", 1)


def test_unlinked_credit_ids_line_up_with_the_anomalies() -> None:
    sale = make_sale(quantity=2)
    det = make_detection(count=2)
    matches = make_matches(sale, det)
    result = handle_cancellation(cancelled(quantity=2), matches)
    assert [a.unit_index for a in result.anomalies] == [1, 2]
    assert result.unlinked_credit_ids == tuple(m.credit.credit_id for m in matches)


# --- only the cancelled sale is affected ---------------------------------------


def test_only_matches_of_the_cancelled_sale_are_affected() -> None:
    d1, d2 = make_detection("ev-1"), make_detection("ev-2", offset_min=1)
    m1 = make_matches(make_sale("s1"), d1)
    m2 = make_matches(make_sale("s2", offset_min=1), d2)

    result = handle_cancellation(cancelled("s1"), m1 + m2)

    assert [a.detection.event_id for a in result.anomalies] == ["ev-1"]
    assert result.unlinked_credit_ids == (m1[0].credit.credit_id,)


def test_same_sale_id_on_another_site_is_untouched() -> None:
    other_site = make_matches(
        make_sale("s1", site_id="cafe-02"), make_detection("ev-x", site_id="cafe-02")
    )
    result = handle_cancellation(cancelled("s1"), other_site)  # cancelled sale is on cafe-01
    assert result == CancellationResult(unlinked_credit_ids=(), anomalies=())


def test_no_match_for_the_cancelled_sale_gives_an_empty_result() -> None:
    matches = make_matches(make_sale("s2"), make_detection())
    assert handle_cancellation(cancelled("s1"), matches) == CancellationResult((), ())


def test_empty_matches_give_an_empty_result() -> None:
    assert handle_cancellation(cancelled(), []) == CancellationResult((), ())


def test_multi_unit_sale_creates_one_anomaly_per_unit() -> None:
    sale, det = make_sale(quantity=3), make_detection(count=3)
    result = handle_cancellation(cancelled(quantity=3), make_matches(sale, det))
    assert [(a.detection.event_id, a.unit_index) for a in result.anomalies] == [
        ("ev-1", 1),
        ("ev-1", 2),
        ("ev-1", 3),
    ]
    assert len(set(result.unlinked_credit_ids)) == 3


def test_a_sale_spread_over_two_detections() -> None:
    sale = make_sale(quantity=2)
    credits = build_credits([sale])
    d1, d2 = make_detection("ev-1"), make_detection("ev-2", offset_min=2)
    matches = [
        CancellationMatch(d1, 1, credits[0]),
        CancellationMatch(d2, 1, credits[1]),
    ]
    result = handle_cancellation(cancelled(quantity=2), matches)
    assert [a.detection.event_id for a in result.anomalies] == ["ev-1", "ev-2"]


# --- determinism ---------------------------------------------------------------


def test_anomalies_are_sorted_oldest_detection_first_whatever_the_input_order() -> None:
    old, new = make_detection("ev-old", offset_min=-5), make_detection("ev-new", offset_min=0)
    sale = make_sale(quantity=2)
    credits = build_credits([sale])
    matches = [CancellationMatch(new, 1, credits[0]), CancellationMatch(old, 1, credits[1])]

    result = handle_cancellation(cancelled(quantity=2), matches)

    assert [a.detection.event_id for a in result.anomalies] == ["ev-old", "ev-new"]
    assert result.unlinked_credit_ids == (credits[1].credit_id, credits[0].credit_id)


def test_result_does_not_depend_on_input_order() -> None:
    sale, det = make_sale(quantity=3), make_detection(count=3)
    matches = make_matches(sale, det)
    forward = handle_cancellation(cancelled(quantity=3), matches)
    backward = handle_cancellation(cancelled(quantity=3), list(reversed(matches)))
    assert forward == backward


def test_ties_on_time_are_broken_by_event_id_then_unit_index() -> None:
    sale = make_sale(quantity=3)
    credits = build_credits([sale])
    b, a = make_detection("ev-b"), make_detection("ev-a")
    matches = [
        CancellationMatch(b, 1, credits[0]),
        CancellationMatch(a, 1, credits[1]),
    ]
    result = handle_cancellation(cancelled(quantity=3), matches)
    assert [x.detection.event_id for x in result.anomalies] == ["ev-a", "ev-b"]


def test_is_repeatable_and_accepts_any_iterable() -> None:
    matches = make_matches(make_sale(), make_detection())
    first = handle_cancellation(cancelled(), matches)
    assert first == handle_cancellation(cancelled(), matches)
    assert first == handle_cancellation(cancelled(), (m for m in matches))


def test_does_not_mutate_its_input() -> None:
    matches = make_matches(make_sale(), make_detection())
    snapshot = list(matches)
    handle_cancellation(cancelled(), matches)
    assert matches == snapshot


# --- input validation ----------------------------------------------------------


def test_a_paid_sale_is_rejected() -> None:
    with pytest.raises(ValueError, match="Cancellation requires"):
        handle_cancellation(make_sale(status="paid"), [])


def test_duplicate_detection_unit_is_rejected() -> None:
    matches = make_matches(make_sale(quantity=2), make_detection(count=2))
    clash = CancellationMatch(matches[0].detection, 1, matches[1].credit)
    with pytest.raises(ValueError, match="Duplicate detection unit"):
        handle_cancellation(cancelled(quantity=2), [matches[0], clash])


def test_a_credit_linked_twice_is_rejected() -> None:
    sale = make_sale()
    credit = build_credits([sale])[0]
    d1, d2 = make_detection("ev-1"), make_detection("ev-2")
    with pytest.raises(ValueError, match="linked more than once"):
        handle_cancellation(
            cancelled(), [CancellationMatch(d1, 1, credit), CancellationMatch(d2, 1, credit)]
        )


def test_inconsistent_unrelated_matches_are_also_rejected() -> None:
    other = make_matches(make_sale("s2", offset_min=1), make_detection("ev-2", offset_min=1))
    with pytest.raises(ValueError, match="Duplicate detection unit"):
        handle_cancellation(cancelled("s1"), other + other)


# --- CancellationMatch validation ------------------------------------------------


@pytest.mark.parametrize("unit_index", [0, -1, 2])
def test_unit_index_must_be_within_the_detection_count(unit_index: int) -> None:
    credit = build_credits([make_sale()])[0]
    with pytest.raises(ValueError, match="unit_index must be between"):
        CancellationMatch(make_detection(count=1), unit_index, credit)


@pytest.mark.parametrize("unit_index", [1.0, "1", True])
def test_unit_index_must_be_an_integer(unit_index: object) -> None:
    credit = build_credits([make_sale()])[0]
    with pytest.raises(TypeError, match="integer"):
        CancellationMatch(make_detection(), unit_index, credit)  # type: ignore[arg-type]


def test_detection_and_credit_must_share_the_site() -> None:
    credit = build_credits([make_sale(site_id="cafe-02")])[0]
    with pytest.raises(ValueError, match="same site"):
        CancellationMatch(make_detection(site_id=SITE), 1, credit)


def test_detection_and_credit_must_share_the_category() -> None:
    credit = build_credits([make_sale(category="soft_drink")])[0]
    with pytest.raises(ValueError, match="same category"):
        CancellationMatch(make_detection(category="coffee"), 1, credit)


def test_results_are_immutable() -> None:
    result = handle_cancellation(cancelled(), make_matches(make_sale(), make_detection()))
    with pytest.raises(FrozenInstanceError):
        result.anomalies = ()  # type: ignore[misc]


# --- hand-off to finalize (end of service) ---------------------------------------

SETTINGS = SiteSettings(
    site_id=SITE,
    confidence_threshold=0.7,
    windows={"coffee": CategoryWindows(timedelta(minutes=20), timedelta(minutes=10))},
)
END_OF_SERVICE = datetime(2026, 11, 5, 23, 0, tzinfo=UTC)


def test_a_replacement_sale_resolves_the_cancellation_anomaly_at_finalize() -> None:
    """Cashier cancels then re-rings the coffee: the false anomaly closes itself (R13)."""
    det = make_detection()
    anomalies = handle_cancellation(cancelled("s1"), make_matches(make_sale("s1"), det)).anomalies
    replacement = build_credits([make_sale("s2", offset_min=3)])

    result = finalize(anomalies, replacement, [], SETTINGS, END_OF_SERVICE)

    assert [(r.event_id, r.unit_index) for r in result.resolutions] == [("ev-1", 1)]
    assert result.remaining == ()


def test_without_a_replacement_the_cancellation_anomaly_stays_open() -> None:
    det = make_detection()
    anomalies = handle_cancellation(cancelled("s1"), make_matches(make_sale("s1"), det)).anomalies

    result = finalize(anomalies, [], [], SETTINGS, END_OF_SERVICE)

    assert result.resolutions == ()
    assert [u.subtype for u in result.remaining] == ["cancelled_after_service"]


def test_the_cancelled_credit_cannot_resolve_its_own_anomaly() -> None:
    det = make_detection()
    matches = make_matches(make_sale("s1"), det)
    anomalies = handle_cancellation(cancelled("s1"), matches).anomalies
    cancelled_credit = matches[0].credit

    # The cancelled sale yields no credit when rebuilt from the voided record.
    assert build_credits([cancelled("s1")]) == ()
    result = finalize(anomalies, build_credits([cancelled("s1")]), [], SETTINGS, END_OF_SERVICE)

    assert result.resolutions == ()
    assert cancelled_credit.credit_id not in {r.credit_id for r in result.resolutions}
