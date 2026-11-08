"""Price statistics per category (business rule R10).

Weighted average unit price of a category over the previous 30 days, plus the
minimum and maximum unit price observed. Feeds ``loss.estimate_loss``.

Pure module: no database, no clock, no framework. The caller passes the sales
and the evaluation instant (``as_of``), so a nightly job and a test get exactly
the same deterministic result.

Inclusion rules (a line counts only if ALL hold):
  * same ``site_id`` (tenant isolation) and same ``category``;
  * ``status == "paid"`` (voided and refunded lines are cancelled: excluded);
  * ``unit_price > 0`` (free items create credits but never price the category);
  * POS event time within ``[as_of - 30 days, as_of]``, both bounds inclusive.
    The POS event timestamp is used, never the import time.

Average = sum(unit_price x quantity) / sum(quantity), rounded to 0.01 MAD with
ROUND_HALF_UP. Since min and max sit on the same 0.01 grid, rounding keeps
``minimum <= average <= maximum``. All money is ``Decimal``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from app.engine.loss import PriceStats
from app.engine.types import SaleRecord

PRICE_WINDOW = timedelta(days=30)
_CENTIME = Decimal("0.01")
_ZERO = Decimal(0)


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _is_priceable(sale: SaleRecord, site_id: str, start: datetime, end: datetime) -> bool:
    return (
        sale.site_id == site_id
        and sale.status == "paid"
        and sale.unit_price > _ZERO
        and start <= sale.timestamp <= end
    )


def _build_stats(lines: list[SaleRecord]) -> PriceStats | None:
    if not lines:
        return None
    total_units = sum(line.quantity for line in lines)
    total_amount = sum((line.unit_price * line.quantity for line in lines), _ZERO)
    average = (total_amount / total_units).quantize(_CENTIME, rounding=ROUND_HALF_UP)
    return PriceStats(
        average=average,
        minimum=min(line.unit_price for line in lines),
        maximum=max(line.unit_price for line in lines),
    )


def compute_all_price_stats(
    sales: Iterable[SaleRecord], *, site_id: str, as_of: datetime
) -> dict[str, PriceStats]:
    """Price statistics of every category that has at least one priceable line."""
    _require_aware("as_of", as_of)
    start = as_of - PRICE_WINDOW
    by_category: dict[str, list[SaleRecord]] = defaultdict(list)
    for sale in sales:
        if _is_priceable(sale, site_id, start, as_of):
            by_category[sale.category].append(sale)
    return {
        category: stats
        for category in sorted(by_category)
        if (stats := _build_stats(by_category[category])) is not None
    }


def compute_price_stats(
    sales: Iterable[SaleRecord], *, site_id: str, category: str, as_of: datetime
) -> PriceStats | None:
    """Price statistics of one category, or ``None`` when no priceable sale exists.

    ``None`` means "no price reference": the caller must not invent a price.
    """
    return compute_all_price_stats(sales, site_id=site_id, as_of=as_of).get(category)
