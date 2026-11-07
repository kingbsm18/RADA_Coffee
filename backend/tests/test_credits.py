from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.engine.credits import build_credits
from app.engine.types import SaleRecord

UTC = timezone.utc


def sale(
    *,
    site_id: str = "cafe-01",
    external_id: str = "sale-001",
    timestamp: datetime | None = None,
    category: str = "coffee",
    quantity: int = 1,
    unit_price: Decimal = Decimal("25.00"),
    status: str = "paid",
) -> SaleRecord:
    return SaleRecord(
        site_id=site_id,
        external_id=external_id,
        timestamp=timestamp or datetime(2026, 11, 5, 10, 0, tzinfo=UTC),
        category=category,
        quantity=quantity,
        unit_price=unit_price,
        status=status,  # type: ignore[arg-type]
    )


def test_paid_sale_creates_one_credit_per_unit() -> None:
    credits = build_credits([sale(quantity=3)])
    assert len(credits) == 3
    assert [credit.unit_index for credit in credits] == [1, 2, 3]
    assert {credit.sale_id for credit in credits} == {"sale-001"}
    assert {credit.unit_price for credit in credits} == {Decimal("25.00")}


def test_paid_sale_with_quantity_one_creates_one_credit() -> None:
    credits = build_credits([sale()])
    assert len(credits) == 1
    assert credits[0].category == "coffee"


def test_paid_free_item_creates_a_zero_value_credit() -> None:
    credits = build_credits([sale(unit_price=Decimal("0.00"))])
    assert len(credits) == 1
    assert credits[0].unit_price == Decimal("0.00")


@pytest.mark.parametrize("status", ["voided", "refunded"])
def test_voided_or_refunded_sale_creates_no_credit(status: str) -> None:
    assert build_credits([sale(status=status)]) == ()


def test_credits_are_isolated_by_site_and_category() -> None:
    credits = build_credits([
        sale(external_id="a", site_id="cafe-01", category="coffee"),
        sale(external_id="b", site_id="cafe-02", category="coffee"),
        sale(external_id="c", site_id="cafe-01", category="soft_drink"),
    ])
    assert {(c.site_id, c.category) for c in credits} == {
        ("cafe-01", "coffee"), ("cafe-02", "coffee"), ("cafe-01", "soft_drink")
    }


def test_credit_timestamp_is_normalized_to_utc() -> None:
    local_timestamp = datetime(
        2026, 11, 5, 11, 0, tzinfo=timezone(timedelta(hours=1))
    )
    credits = build_credits([sale(timestamp=local_timestamp)])
    assert credits[0].timestamp == datetime(2026, 11, 5, 10, 0, tzinfo=UTC)
    assert credits[0].timestamp.utcoffset() == timedelta(0)


def test_credits_have_deterministic_order() -> None:
    later = sale(
        external_id="later",
        timestamp=datetime(2026, 11, 5, 10, 5, tzinfo=UTC),
    )
    earlier = sale(
        external_id="earlier",
        timestamp=datetime(2026, 11, 5, 10, 1, tzinfo=UTC),
    )
    first_result = build_credits([later, earlier])
    second_result = build_credits([earlier, later])
    assert first_result == second_result
    assert [c.sale_id for c in first_result] == ["earlier", "later"]


def test_duplicate_delivery_is_idempotent() -> None:
    repeated_sale = sale(quantity=2)
    credits = build_credits([repeated_sale, repeated_sale])
    assert len(credits) == 2
    assert len({credit.credit_id for credit in credits}) == 2


def test_conflicting_duplicate_sale_id_is_rejected() -> None:
    original = sale(external_id="same-id", quantity=1)
    conflicting = sale(external_id="same-id", quantity=2)
    with pytest.raises(ValueError, match="Conflicting POS sale"):
        build_credits([original, conflicting])


def test_each_unit_has_a_stable_unique_credit_id() -> None:
    first = build_credits([sale(quantity=3)])
    second = build_credits([sale(quantity=3)])
    assert [c.credit_id for c in first] == [c.credit_id for c in second]
    assert len({c.credit_id for c in first}) == 3


def test_empty_input_returns_empty_tuple() -> None:
    assert build_credits([]) == ()


def test_mixed_paid_and_cancelled_sales_only_create_paid_credits() -> None:
    credits = build_credits([
        sale(external_id="paid", quantity=2),
        sale(external_id="voided", status="voided"),
        sale(external_id="refunded", status="refunded"),
    ])
    assert len(credits) == 2
    assert {credit.sale_id for credit in credits} == {"paid"}
