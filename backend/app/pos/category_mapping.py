"""POS product/category -> detector category (the single mapping table)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.category import CategoryMapping

Mapping = dict[tuple[str, str], str]


def normalize_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def load_mapping(db: Session, site_id: str) -> Mapping:
    rows = db.execute(
        select(CategoryMapping).where(CategoryMapping.site_id == site_id)
    ).scalars()
    return {(row.match_field, row.match_value): row.category for row in rows}


def resolve_category(
    mapping: Mapping, *, product_name: str, pos_category: str | None
) -> str | None:
    """The product name wins over the POS category; None means unmapped."""
    by_product = mapping.get(("product_name", normalize_key(product_name)))
    if by_product is not None:
        return by_product
    if pos_category:
        return mapping.get(("pos_category", normalize_key(pos_category)))
    return None
