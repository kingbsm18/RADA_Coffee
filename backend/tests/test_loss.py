"""Tests for engine/loss.py (business rule R10, estimated loss).

loss = quantity x weighted average price; range = quantity x min .. quantity x max.
All money is Decimal in MAD, rounded to 2 places (ROUND_HALF_UP).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from app.engine.loss import CENTIME, LossEstimate, PriceStats, estimate_loss

D = Decimal
PRICES = PriceStats(average=D("12.50"), minimum=D("10.00"), maximum=D("20.00"))


def test_single_unit() -> None:
    assert estimate_loss(1, PRICES) == LossEstimate(
        quantity=1, estimated=D("12.50"), minimum=D("10.00"), maximum=D("20.00")
    )


def test_several_units_multiply_every_figure() -> None:
    result = estimate_loss(3, PRICES)
    assert result.quantity == 3
    assert result.estimated == D("37.50")
    assert result.minimum == D("30.00")
    assert result.maximum == D("60.00")


@pytest.mark.parametrize("quantity", [1, 2, 3, 7, 50])
def test_range_always_brackets_the_estimate(quantity: int) -> None:
    result = estimate_loss(quantity, PRICES)
    assert result.minimum <= result.estimated <= result.maximum


def test_estimate_is_proportional_to_quantity() -> None:
    one = estimate_loss(1, PRICES)
    four = estimate_loss(4, PRICES)
    assert four.estimated == one.estimated * 4
    assert four.minimum == one.minimum * 4
    assert four.maximum == one.maximum * 4


def test_rounding_is_half_up_not_bankers() -> None:
    prices = PriceStats(average=D("0.125"), minimum=D("0.125"), maximum=D("0.125"))
    assert estimate_loss(1, prices).estimated == D("0.13")  # banker's rounding would give 0.12


def test_rounding_applies_after_multiplication() -> None:
    prices = PriceStats(average=D("12.345"), minimum=D("12.345"), maximum=D("12.345"))
    assert estimate_loss(1, prices).estimated == D("12.35")
    assert estimate_loss(2, prices).estimated == D("24.69")  # 24.690, not 2 x 12.35


def test_results_are_quantized_to_centimes() -> None:
    result = estimate_loss(3, PRICES)
    for value in (result.estimated, result.minimum, result.maximum):
        assert value == value.quantize(CENTIME)
        assert value.as_tuple().exponent == -2


def test_no_float_drift() -> None:
    prices = PriceStats(average=D("0.10"), minimum=D("0.10"), maximum=D("0.10"))
    assert estimate_loss(3, prices).estimated == D("0.30")  # 0.1 * 3 in float is 0.30000000000000004


def test_zero_prices_give_zero_loss() -> None:
    zero = PriceStats(average=D("0"), minimum=D("0"), maximum=D("0"))
    result = estimate_loss(5, zero)
    assert result.estimated == result.minimum == result.maximum == D("0.00")


def test_single_price_gives_a_degenerate_range() -> None:
    flat = PriceStats(average=D("8.00"), minimum=D("8.00"), maximum=D("8.00"))
    result = estimate_loss(2, flat)
    assert result.minimum == result.estimated == result.maximum == D("16.00")


def test_is_deterministic() -> None:
    assert estimate_loss(3, PRICES) == estimate_loss(3, PRICES)


def test_results_are_immutable() -> None:
    result = estimate_loss(1, PRICES)
    with pytest.raises(FrozenInstanceError):
        result.estimated = D("1")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        PRICES.average = D("1")  # type: ignore[misc]


@pytest.mark.parametrize("quantity", [0, -1, -10])
def test_non_positive_quantity_is_rejected(quantity: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        estimate_loss(quantity, PRICES)


@pytest.mark.parametrize("quantity", [1.0, "2", None, True])
def test_non_integer_quantity_is_rejected(quantity: object) -> None:
    with pytest.raises(TypeError, match="integer"):
        estimate_loss(quantity, PRICES)  # type: ignore[arg-type]


def test_float_prices_are_rejected() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        PriceStats(average=12.5, minimum=D("10"), maximum=D("20"))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Decimal"):
        PriceStats(average=D("12.5"), minimum=10, maximum=D("20"))  # type: ignore[arg-type]


def test_negative_price_is_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        PriceStats(average=D("-1"), minimum=D("-2"), maximum=D("0"))


@pytest.mark.parametrize("bad", [D("NaN"), D("Infinity"), D("-Infinity")])
def test_non_finite_price_is_rejected(bad: Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        PriceStats(average=bad, minimum=D("1"), maximum=D("2"))


@pytest.mark.parametrize(
    ("average", "minimum", "maximum"),
    [
        (D("5"), D("6"), D("7")),  # average below minimum
        (D("8"), D("6"), D("7")),  # average above maximum
        (D("5"), D("9"), D("4")),  # minimum above maximum
    ],
)
def test_inconsistent_price_stats_are_rejected(
    average: Decimal, minimum: Decimal, maximum: Decimal
) -> None:
    with pytest.raises(ValueError, match="minimum <= average <= maximum"):
        PriceStats(average=average, minimum=minimum, maximum=maximum)
