from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.engine.types import (
    MAX_WINDOW,
    CategoryWindows,
    Detection,
    SaleRecord,
    SiteSettings,
)

UTC = timezone.utc
TS = datetime(2026, 11, 5, 10, 0, tzinfo=UTC)


def detection(**overrides) -> Detection:
    data = dict(
        event_id="evt-1",
        site_id="cafe-01",
        timestamp=TS,
        category="coffee",
        count=1,
        confidence=0.9,
    )
    data.update(overrides)
    return Detection(**data)


def test_valid_detection_defaults_snapshot_to_none() -> None:
    assert detection().snapshot_ref is None


@pytest.mark.parametrize("count", [0, -1])
def test_detection_count_must_be_positive(count: int) -> None:
    with pytest.raises(ValueError, match="count must be positive"):
        detection(count=count)


def test_detection_count_rejects_bool_and_float() -> None:
    with pytest.raises(TypeError):
        detection(count=True)
    with pytest.raises(TypeError):
        detection(count=1.0)


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan"), float("inf")])
def test_detection_confidence_must_be_between_0_and_1(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        detection(confidence=confidence)


def test_detection_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        detection(timestamp=datetime(2026, 11, 5, 10, 0))


def test_windows_are_bounded_by_the_absolute_ceiling() -> None:
    assert CategoryWindows(lookback=MAX_WINDOW, grace=timedelta(0))
    with pytest.raises(ValueError, match="cannot exceed"):
        CategoryWindows(lookback=MAX_WINDOW + timedelta(seconds=1), grace=timedelta(0))
    with pytest.raises(ValueError, match="cannot be negative"):
        CategoryWindows(lookback=timedelta(0), grace=timedelta(minutes=-1))


def test_site_settings_lookup_and_unknown_category() -> None:
    windows = CategoryWindows(timedelta(minutes=20), timedelta(minutes=10))
    settings = SiteSettings("cafe-01", 0.6, {"coffee": windows})

    assert settings.windows_for("coffee") == windows
    with pytest.raises(ValueError, match="No windows configured"):
        settings.windows_for("soft_drink")


def test_site_settings_mapping_is_frozen() -> None:
    windows = CategoryWindows(timedelta(minutes=20), timedelta(minutes=10))
    source = {"coffee": windows}
    settings = SiteSettings("cafe-01", 0.6, source)

    source["soft_drink"] = windows  # mutating the original must not leak in
    assert "soft_drink" not in settings.windows
    with pytest.raises(TypeError):
        settings.windows["soft_drink"] = windows  # type: ignore[index]


def test_sale_record_still_rejects_float_price() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        SaleRecord("cafe-01", "s1", TS, "coffee", 1, 25.0, "paid")  # type: ignore[arg-type]
