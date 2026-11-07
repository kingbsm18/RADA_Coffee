"""Pure POS credit generation for the RADA reconciliation engine.

A credit represents one paid POS unit that may be consumed by at most one
visual serving during reconciliation. This module only creates credits; it
does not match, consume, expire, or persist them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import timezone
from uuid import NAMESPACE_URL, uuid5

from app.engine.types import Credit, SaleRecord


def _credit_id(site_id: str, sale_id: str, unit_index: int) -> str:
    """Return a stable ID so replaying the same POS input is idempotent.

    The identity is serialized as a JSON array rather than joined with a
    separator, so ids that contain ``:`` can never collide
    (``"a"`` + ``"b:1"`` vs ``"a:b"`` + ``"1"``).
    """
    identity = json.dumps(
        ["rada-credit", site_id, sale_id, unit_index], separators=(",", ":")
    )
    return str(uuid5(NAMESPACE_URL, identity))


def build_credits(sales: Iterable[SaleRecord]) -> tuple[Credit, ...]:
    """Create one deterministic credit per unit of every paid POS sale.

    Only paid lines create credits. Paid complimentary items at Decimal('0')
    remain valid credits. Voided and refunded lines create no credits.
    Timestamps use the original sale event time and are normalized to UTC.

    Identical duplicate deliveries are ignored. Conflicting records sharing
    (site_id, external_id) raise ValueError rather than being silently chosen.
    Credits are sorted deterministically. Matching and consumption belong to
    reconcile.py.
    """
    unique_sales: dict[tuple[str, str], SaleRecord] = {}

    for sale in sales:
        key = (sale.site_id, sale.external_id)
        existing = unique_sales.get(key)
        if existing is None:
            unique_sales[key] = sale
        elif existing != sale:
            raise ValueError(
                "Conflicting POS sale records share "
                f"(site_id, external_id)={key!r}"
            )

    paid_sales = (
        sale for sale in unique_sales.values() if sale.status == "paid"
    )
    ordered_sales = sorted(
        paid_sales,
        key=lambda item: (
            item.timestamp.astimezone(timezone.utc),
            item.site_id,
            item.category,
            item.external_id,
        ),
    )

    credits: list[Credit] = []
    for sale in ordered_sales:
        timestamp_utc = sale.timestamp.astimezone(timezone.utc)
        for unit_index in range(1, sale.quantity + 1):
            credits.append(
                Credit(
                    credit_id=_credit_id(
                        sale.site_id, sale.external_id, unit_index
                    ),
                    site_id=sale.site_id,
                    sale_id=sale.external_id,
                    unit_index=unit_index,
                    timestamp=timestamp_utc,
                    category=sale.category,
                    unit_price=sale.unit_price,
                )
            )

    return tuple(credits)
