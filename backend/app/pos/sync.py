"""Idempotent persistence of normalized POS sales.

Re-importing the same data changes nothing. A later import of an already known sale
with a different status (e.g. paid -> voided) updates it and is reported in
``status_changes`` so the engine can react (R8).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import utcnow
from app.models.pos_sale import PosImportBatch, PosSale
from app.pos.base import RowError
from app.pos.category_mapping import Mapping, load_mapping, resolve_category
from app.schemas.events import PosSaleIn

_CHUNK = 500
_MAX_REPORTED = 50


@dataclass(slots=True)
class ImportReport:
    batch_id: object
    rows_received: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0
    errors: list[RowError] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    status_changes: list[str] = field(default_factory=list)
    earliest: datetime | None = None  # UTC; lets the user spot a mis-read date format
    latest: datetime | None = None


def _differs(row: PosSale, sale: PosSaleIn, category: str | None) -> bool:
    return (
        row.timestamp != sale.timestamp.astimezone(timezone.utc)
        or row.product_name != sale.product_name
        or row.pos_category != sale.pos_category
        or row.category != category
        or row.quantity != sale.quantity
        or row.unit_price != sale.unit_price
        or row.status != sale.status
    )


def import_sales(
    db: Session,
    site_id: str,
    sales: Sequence[PosSaleIn],
    *,
    source: str,
    rows_received: int | None = None,
    errors: Sequence[RowError] = (),
    checksum: str | None = None,
) -> ImportReport:
    """Upsert ``sales`` for ``site_id`` and record an audit batch (one transaction)."""
    batch = PosImportBatch(site_id=site_id, source=source, checksum=checksum)
    db.add(batch)
    db.flush()

    report = ImportReport(
        batch_id=batch.id,
        rows_received=rows_received if rows_received is not None else len(sales) + len(errors),
        rejected=len(errors),
        errors=list(errors)[:_MAX_REPORTED],
    )
    if any(sale.site_id != site_id for sale in sales):
        raise ValueError("sale does not belong to the target site")

    mapping: Mapping = load_mapping(db, site_id)
    unmapped: set[str] = set()

    # A sale appearing twice in one batch: keep the last version.
    latest = {sale.external_id: sale for sale in sales}
    ids = list(latest)
    existing: dict[str, PosSale] = {}
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start : start + _CHUNK]
        rows = db.execute(
            select(PosSale).where(PosSale.site_id == site_id, PosSale.external_id.in_(chunk))
        ).scalars()
        existing.update({row.external_id: row for row in rows})

    for external_id, sale in latest.items():
        category = resolve_category(
            mapping, product_name=sale.product_name, pos_category=sale.pos_category
        )
        if category is None:
            unmapped.add(sale.pos_category or sale.product_name)
        row = existing.get(external_id)
        if row is None:
            db.add(
                PosSale(
                    site_id=site_id,
                    external_id=external_id,
                    timestamp=sale.timestamp.astimezone(timezone.utc),
                    product_name=sale.product_name,
                    pos_category=sale.pos_category,
                    category=category,
                    quantity=sale.quantity,
                    unit_price=sale.unit_price,
                    status=sale.status,
                    raw=sale.raw,
                )
            )
            report.inserted += 1
        elif _differs(row, sale, category):
            if row.status != sale.status:
                report.status_changes.append(external_id)
            row.timestamp = sale.timestamp.astimezone(timezone.utc)
            row.product_name = sale.product_name
            row.pos_category = sale.pos_category
            row.category = category
            row.quantity = sale.quantity
            row.unit_price = sale.unit_price
            row.status = sale.status
            row.raw = sale.raw
            report.updated += 1
        else:
            report.unchanged += 1

    if latest:
        instants = [sale.timestamp.astimezone(timezone.utc) for sale in latest.values()]
        report.earliest, report.latest = min(instants), max(instants)
    report.unmapped = sorted(unmapped)[:_MAX_REPORTED]
    report.status_changes = report.status_changes[:_MAX_REPORTED]

    batch.rows_received = report.rows_received
    batch.rows_inserted = report.inserted
    batch.rows_updated = report.updated
    batch.rows_unchanged = report.unchanged
    batch.rows_rejected = report.rejected
    batch.status = "completed"
    batch.completed_at = utcnow()
    db.commit()
    return report


def remap_categories(db: Session, site_id: str) -> int:
    """Re-resolve categories of existing sales after the mapping table changed."""
    mapping = load_mapping(db, site_id)
    changed = 0
    rows = db.execute(select(PosSale).where(PosSale.site_id == site_id)).scalars()
    for row in rows:
        category = resolve_category(
            mapping, product_name=row.product_name, pos_category=row.pos_category
        )
        if row.category != category:
            row.category = category
            changed += 1
    db.commit()
    return changed
