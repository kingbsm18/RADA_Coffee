"""Tests for engine/pricing.py (business rule R10, price statistics).

Weighted average unit price per category over the previous 30 days. Free
(0 MAD) and cancelled (voided/refunded) lines are excluded. All money is
Decimal; the result is deterministic and independent of input order.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.engine.loss import PriceStats, estimate_loss
from app.engine.pricing import (
    PRICE_WINDOW,
    compute_all_price_stats,
    compute_price_stats,
)
from app.engine.types import SaleRecord

UTC = timezone.utc
AS_OF = datetime(2026, 6, 30, 23, 0, tzinfo=UTC)
SITE = "cafe-1"


def sale(
    ext: str,
    *,
    price: str,
    qty: int = 1,
    category: str = "coffee",
    status: str = "paid",
    ts: datetime | None = None,
    site: str = SITE,
) -> SaleRecord:
    return SaleRecord(
        site_id=site,
        external_id=ext,
        timestamp=ts if ts is not None else AS_OF - timedelta(days=1),
        category=category,
        quantity=qty,
        unit_price=Decimal(price),
        status=status,  # type: ignore[arg-type]
    )


def stats(sales, category="coffee", site=SITE, as_of=AS_OF):
    return compute_price_stats(sales, site_id=site, category=category, as_of=as_of)


def test_window_is_thirty_days():
    assert PRICE_WINDOW == timedelta(days=30)


def test_single_sale():
    result = stats([sale("a", price="12.00")])
    assert result == PriceStats(Decimal("12.00"), Decimal("12.00"), Decimal("12.00"))


def test_weighted_average_uses_quantities():
    # (10 x 1 + 20 x 3) / 4 = 17.50 ; a simple mean of unit prices would be 15.00
    result = stats([sale("a", price="10.00", qty=1), sale("b", price="20.00", qty=3)])
    assert result.average == Decimal("17.50")
    assert result.minimum == Decimal("10.00")
    assert result.maximum == Decimal("20.00")


def test_average_rounded_half_up_to_centimes():
    # (10.00 + 10.01) / 2 = 10.005 -> 10.01 (half up, not banker's rounding)
    result = stats([sale("a", price="10.00"), sale("b", price="10.01")])
    assert result.average == Decimal("10.01")
    assert result.minimum <= result.average <= result.maximum


def test_no_float_artifacts():
    prices = ["0.10", "0.20", "0.30"]
    result = stats([sale(str(i), price=p) for i, p in enumerate(prices)])
    assert result.average == Decimal("0.20")
    assert all(isinstance(v, Decimal) for v in (result.average, result.minimum, result.maximum))


def test_free_items_excluded():
    # A 0 MAD line must neither lower the average nor become the minimum.
    result = stats([sale("a", price="0.00", qty=5), sale("b", price="12.00")])
    assert result == PriceStats(Decimal("12.00"), Decimal("12.00"), Decimal("12.00"))


@pytest.mark.parametrize("status", ["voided", "refunded"])
def test_cancelled_sales_excluded(status):
    result = stats([sale("a", price="100.00", status=status), sale("b", price="12.00")])
    assert result.maximum == Decimal("12.00")
    assert result.average == Decimal("12.00")


def test_only_free_or_cancelled_returns_none():
    assert stats([sale("a", price="0.00"), sale("b", price="9.00", status="voided")]) is None


def test_no_sales_returns_none():
    assert stats([]) is None


def test_other_category_ignored():
    assert stats([sale("a", price="50.00", category="pastry")]) is None


def test_other_site_ignored_tenant_isolation():
    sales = [sale("a", price="99.00", site="cafe-2"), sale("b", price="10.00")]
    result = stats(sales)
    assert result.average == Decimal("10.00")
    assert result.maximum == Decimal("10.00")


def test_sale_older_than_thirty_days_excluded():
    old = sale("old", price="99.00", ts=AS_OF - PRICE_WINDOW - timedelta(seconds=1))
    assert stats([old, sale("b", price="10.00")]).maximum == Decimal("10.00")


def test_sale_exactly_at_window_start_included():
    edge = sale("edge", price="30.00", ts=AS_OF - PRICE_WINDOW)
    assert stats([edge]).average == Decimal("30.00")


def test_sale_exactly_at_as_of_included():
    edge = sale("edge", price="30.00", ts=AS_OF)
    assert stats([edge]).average == Decimal("30.00")


def test_future_sale_excluded():
    future = sale("future", price="99.00", ts=AS_OF + timedelta(seconds=1))
    assert stats([future]) is None


def test_uses_pos_event_time_across_timezones():
    # 2026-06-01 01:00 at UTC+2 == 2026-05-31 23:00 UTC: 30 days + 0 s before AS_OF? No:
    # AS_OF - 30d == 2026-05-31 23:00 UTC, so it sits exactly on the included edge.
    tz = timezone(timedelta(hours=2))
    edge = sale("edge", price="7.00", ts=datetime(2026, 6, 1, 1, 0, tzinfo=tz))
    assert stats([edge]).average == Decimal("7.00")


def test_as_of_must_be_timezone_aware():
    with pytest.raises(ValueError):
        stats([sale("a", price="10.00")], as_of=datetime(2026, 6, 30, 23, 0))


def test_deterministic_regardless_of_input_order():
    sales = [sale(str(i), price=f"{5 + i}.{i:02d}", qty=1 + i % 3) for i in range(20)]
    expected = stats(sales)
    for seed in range(5):
        shuffled = sales[:]
        random.Random(seed).shuffle(shuffled)
        assert stats(shuffled) == expected


def test_accepts_generator_input():
    assert stats(s for s in [sale("a", price="8.00")]).average == Decimal("8.00")


def test_stats_always_satisfy_min_avg_max():
    sales = [sale("a", price="3.33", qty=7), sale("b", price="3.34", qty=11)]
    result = stats(sales)
    assert result.minimum <= result.average <= result.maximum


def test_compute_all_groups_by_category():
    sales = [
        sale("a", price="10.00", category="coffee"),
        sale("b", price="30.00", category="coffee"),
        sale("c", price="6.00", category="pastry"),
        sale("d", price="0.00", category="water"),  # only free: no entry
        sale("e", price="50.00", category="coffee", site="cafe-2"),
    ]
    result = compute_all_price_stats(sales, site_id=SITE, as_of=AS_OF)
    assert set(result) == {"coffee", "pastry"}
    assert result["coffee"].average == Decimal("20.00")
    assert result["pastry"].minimum == Decimal("6.00")


def test_feeds_loss_estimate_with_range():
    price_stats = stats([sale("a", price="10.00"), sale("b", price="20.00")])
    loss = estimate_loss(3, price_stats)
    assert loss.estimated == Decimal("45.00")
    assert loss.minimum == Decimal("30.00")
    assert loss.maximum == Decimal("60.00")


def test_input_sales_not_mutated():
    sales = [sale("a", price="10.00"), sale("b", price="20.00")]
    snapshot = list(sales)
    stats(sales)
    assert sales == snapshot
