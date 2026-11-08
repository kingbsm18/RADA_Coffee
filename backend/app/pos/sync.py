"""app/pos/sync.py — TODO: implement (see docs/architecture.md)."""
"""POS synchronization and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.credits import build_credits
from app.engine.types import Credit as EngineCredit
from app.models.credit import Credit
from app.models.pos_sale import POSSale
from app.pos.base import POSAdapter, POSAdapterError
from app.pos.category_mapping import CategoryMapper
from app.pos.normalizer import (
    NormalizedPOSSale,
    normalize_pos_record,
    to_sale_record,
)


class POSSynchronizationError(Exception):
    """Base exception for POS synchronization errors."""


class POSPaginationError(POSSynchronizationError):
    """Raised when POS pagination is invalid or does not terminate."""


@dataclass(frozen=True, slots=True)
class POSSynchronizationResult:
    """Summary of one POS synchronization run."""

    pages_fetched: int
    records_received: int
    sales_inserted: int
    sales_updated: int
    credits_created: int
    credits_deactivated: int


async def _fetch_all_records(
    adapter: POSAdapter,
    start_time: datetime,
    end_time: datetime,
    *,
    max_pages: int,
) -> tuple[tuple[dict[str, Any], ...], int]:
    """Fetch every page while protecting against pagination loops."""

    records: list[dict[str, Any]] = []
    seen_cursors: set[str] = set()
    cursor: str | None = None
    pages_fetched = 0

    while True:
        if pages_fetched >= max_pages:
            raise POSPaginationError(
                f"POS pagination exceeded max_pages={max_pages}"
            )

        page = await adapter.fetch_sales(
            start_time=start_time,
            end_time=end_time,
            cursor=cursor,
        )

        pages_fetched += 1

        for record in page.records:
            records.append(dict(record))

        next_cursor = page.next_cursor

        if next_cursor is None:
            break

        if next_cursor in seen_cursors:
            raise POSPaginationError(
                f"POS adapter repeated pagination cursor {next_cursor!r}"
            )

        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return tuple(records), pages_fetched


def _deduplicate_sales(
    sales: tuple[NormalizedPOSSale, ...],
) -> tuple[NormalizedPOSSale, ...]:
    """Ignore identical duplicate deliveries and reject conflicting ones."""

    unique: dict[tuple[str, str], NormalizedPOSSale] = {}

    for sale in sales:
        key = (sale.site_id, sale.external_id)
        existing = unique.get(key)

        if existing is None:
            unique[key] = sale
        elif existing != sale:
            raise POSSynchronizationError(
                "Conflicting POS records share "
                f"(site_id, external_id)={key!r}"
            )

    return tuple(
        unique[key]
        for key in sorted(unique)
    )


def _upsert_sale(
    db: Session,
    sale: NormalizedPOSSale,
) -> bool:
    """Insert or update one POS sale.

    Returns True for an insert and False for an update.
    """

    existing = db.scalar(
        select(POSSale).where(
            POSSale.site_id == sale.site_id,
            POSSale.external_id == sale.external_id,
        )
    )

    if existing is None:
        db.add(
            POSSale(
                site_id=sale.site_id,
                external_id=sale.external_id,
                timestamp=sale.timestamp,
                product_name=sale.product_name,
                pos_category=sale.pos_category,
                category=sale.category,
                quantity=sale.quantity,
                unit_price=sale.unit_price,
                status=sale.status,
                raw=sale.raw,
            )
        )
        db.flush()
        return True

    existing.timestamp = sale.timestamp
    existing.product_name = sale.product_name
    existing.pos_category = sale.pos_category
    existing.category = sale.category
    existing.quantity = sale.quantity
    existing.unit_price = sale.unit_price
    existing.status = sale.status
    existing.raw = sale.raw

    db.flush()
    return False


def _upsert_credits(
    db: Session,
    sale: NormalizedPOSSale,
) -> tuple[int, int]:
    """Synchronize deterministic credits for one POS sale.

    Paid sales create one credit per unit.
    Voided/refunded sales deactivate their existing credits.
    """

    existing_credits = list(
        db.scalars(
            select(Credit).where(
                Credit.site_id == sale.site_id,
                Credit.sale_id == sale.external_id,
            )
        ).all()
    )

    existing_by_id = {
        credit.id: credit
        for credit in existing_credits
    }

    if sale.status != "paid":
        deactivated = 0

        for credit in existing_credits:
            if credit.is_active:
                credit.is_active = False
                credit.deactivated_at = datetime.now().astimezone()
                credit.deactivation_reason = sale.status
                deactivated += 1

        db.flush()
        return 0, deactivated

    engine_sale = to_sale_record(sale)
    generated_credits = build_credits([engine_sale])

    expected_ids = {
        generated.credit_id
        for generated in generated_credits
    }

    created = 0
    deactivated = 0

    for generated in generated_credits:
        existing = existing_by_id.get(generated.credit_id)

        if existing is None:
            db.add(_to_db_credit(generated))
            created += 1
            continue

        # Keep the credit identity stable while synchronizing its data.
        existing.timestamp = generated.timestamp
        existing.category = generated.category
        existing.unit_price = generated.unit_price

        if not existing.is_active:
            existing.is_active = True
            existing.deactivated_at = None
            existing.deactivation_reason = None

    # If the POS quantity was reduced, deactivate excess credits.
    for existing in existing_credits:
        if existing.id not in expected_ids and existing.is_active:
            existing.is_active = False
            existing.deactivated_at = datetime.now().astimezone()
            existing.deactivation_reason = "quantity_updated"
            deactivated += 1

    db.flush()
    return created, deactivated


def _to_db_credit(credit: EngineCredit) -> Credit:
    """Convert a pure engine credit into a SQLAlchemy model."""

    return Credit(
        id=credit.credit_id,
        site_id=credit.site_id,
        sale_id=credit.sale_id,
        unit_index=credit.unit_index,
        timestamp=credit.timestamp,
        category=credit.category,
        unit_price=credit.unit_price,
        is_active=True,
    )


async def sync_pos_sales(
    adapter: POSAdapter,
    db: Session,
    start_time: datetime,
    end_time: datetime,
    *,
    mapper: CategoryMapper | None = None,
    max_pages: int = 1000,
) -> POSSynchronizationResult:
    """Fetch, normalize and persist POS sales for one site.

    The caller owns the SQLAlchemy Session. This function commits once
    after all pages have been processed and rolls back on failure.

    The POS adapter must preserve each sale's original event timestamp.
    """

    if start_time.tzinfo is None or start_time.utcoffset() is None:
        raise ValueError("start_time must be timezone-aware")

    if end_time.tzinfo is None or end_time.utcoffset() is None:
        raise ValueError("end_time must be timezone-aware")

    if start_time >= end_time:
        raise ValueError("start_time must be earlier than end_time")

    if isinstance(max_pages, bool) or not isinstance(max_pages, int):
        raise TypeError("max_pages must be an integer")

    if max_pages <= 0:
        raise ValueError("max_pages must be positive")

    try:
        raw_records, pages_fetched = await _fetch_all_records(
            adapter,
            start_time,
            end_time,
            max_pages=max_pages,
        )

        normalized_sales = tuple(
            normalize_pos_record(
                record=record,
                site_id=adapter.site_id,
                mapper=mapper,
            )
            for record in raw_records
        )

        unique_sales = _deduplicate_sales(normalized_sales)

        inserted = 0
        updated = 0
        credits_created = 0
        credits_deactivated = 0

        for sale in unique_sales:
            was_inserted = _upsert_sale(db, sale)

            if was_inserted:
                inserted += 1
            else:
                updated += 1

            created, deactivated = _upsert_credits(db, sale)

            credits_created += created
            credits_deactivated += deactivated

        db.commit()

        return POSSynchronizationResult(
            pages_fetched=pages_fetched,
            records_received=len(raw_records),
            sales_inserted=inserted,
            sales_updated=updated,
            credits_created=credits_created,
            credits_deactivated=credits_deactivated,
        )

    except Exception as exc:
        db.rollback()

        if isinstance(exc, (POSSynchronizationError, POSAdapterError)):
            raise

        raise POSSynchronizationError(
            f"POS synchronization failed: {exc}"
        ) from exc
