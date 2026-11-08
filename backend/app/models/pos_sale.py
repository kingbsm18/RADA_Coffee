"""POS sales (one row per (site_id, external_id)) and import audit batches."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, JSONType, UTCDateTime, utcnow

SALE_STATUSES = ("paid", "voided", "refunded")


class PosSale(Base):
    __tablename__ = "pos_sale"
    __table_args__ = (
        UniqueConstraint("site_id", "external_id", name="uq_pos_sale_site_external"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("status IN ('paid', 'voided', 'refunded')", name="status_valid"),
        Index("ix_pos_sale_site_timestamp", "site_id", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(128))
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime)  # sale event time, never import time
    product_name: Mapped[str] = mapped_column(String(200))
    pos_category: Mapped[str | None] = mapped_column(String(200), default=None)
    # Resolved through category_mapping; NULL = unmapped (cannot create credits yet).
    category: Mapped[str | None] = mapped_column(String(64), default=None)
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(16))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=None)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class PosImportBatch(Base):
    __tablename__ = "pos_import_batch"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    checksum: Mapped[str | None] = mapped_column(String(64), default=None)
    status: Mapped[str] = mapped_column(String(16), default="running")
    rows_received: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0)
    rows_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
