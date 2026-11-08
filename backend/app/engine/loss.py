"""Estimated loss of an anomaly (business rule R10).

estimated loss = missing quantity x weighted average price of the category
range          = quantity x minimum price  ...  quantity x maximum price

Pure module: no database, no clock, no framework. The price statistics are
computed elsewhere (``pricing.py``: paid sales of the last 30 days, with free
and cancelled lines excluded) and passed in. The result is meant to be FROZEN
in the alert at creation time, so later price changes never rewrite history.

All money is ``Decimal`` in MAD, rounded to 2 places (ROUND_HALF_UP). The
output is always an estimate; never present it as an exact amount.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENTIME = Decimal("0.01")


def _require_money(name: str, value: Decimal) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal; float is not accepted")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value < Decimal(0):
        raise ValueError(f"{name} cannot be negative")


def _round_mad(value: Decimal) -> Decimal:
    return value.quantize(CENTIME, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class PriceStats:
    """Unit price statistics of one category (weighted average, min, max)."""

    average: Decimal
    minimum: Decimal
    maximum: Decimal

    def __post_init__(self) -> None:
        _require_money("average", self.average)
        _require_money("minimum", self.minimum)
        _require_money("maximum", self.maximum)
        if not self.minimum <= self.average <= self.maximum:
            raise ValueError("price stats must satisfy minimum <= average <= maximum")


@dataclass(frozen=True, slots=True)
class LossEstimate:
    """Frozen loss figures stored in the alert."""

    quantity: int
    estimated: Decimal
    minimum: Decimal
    maximum: Decimal


def estimate_loss(quantity: int, prices: PriceStats) -> LossEstimate:
    """Estimate the loss of ``quantity`` units served without a registered sale."""
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise TypeError("quantity must be an integer")
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    return LossEstimate(
        quantity=quantity,
        estimated=_round_mad(prices.average * quantity),
        minimum=_round_mad(prices.minimum * quantity),
        maximum=_round_mad(prices.maximum * quantity),
    )
