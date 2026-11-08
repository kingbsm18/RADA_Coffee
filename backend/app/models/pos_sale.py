"""app/models/pos_sale.py — TODO: implement (see docs/architecture.md)."""
"""Database model for normalized POS sale records."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class POSSale(Base):
    """A normalized sale line imported from a café POS system.

    One POS sale line can generate multiple reconciliation credits.

    Important business rules:
    - external_id is unique per site.
    - timestamp is the original POS sale event time, never import time.
    - unit_price uses Decimal / NUMERIC, never float.
    - A zero-priced paid item is valid.
    - Voided and refunded sales must not generate credits.
    - category contains the normalized RADA category.
    - pos_category preserves the original POS category.
    - raw preserves the original POS payload for traceability.
    """

    __tablename__ = "pos_sales"

    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "external_id",
            name="uq_pos_sales_site_external_id",
        ),
        CheckConstraint(
            "quantity > 0 AND quantity <= 100",
            name="ck_pos_sales_quantity_range",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="ck_pos_sales_unit_price_non_negative",
        ),
        CheckConstraint(
            "status IN ('paid', 'voided', 'refunded')",
            name="ck_pos_sales_valid_status",
        ),
        Index(
            "ix_pos_sales_site_timestamp",
            "site_id",
            "timestamp",
        ),
        Index(
            "ix_pos_sales_site_category_timestamp",
            "site_id",
            "category",
            "timestamp",
        ),
        Index(
            "ix_pos_sales_site_status_timestamp",
            "site_id",
            "status",
            "timestamp",
        ),
        Index(
            "ix_pos_sales_imported_at",
            "imported_at",
        ),
    )

    # Unique internal database identifier.
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    # Café / establishment identifier.
    # Must match the site_id used by detections and credits.
    site_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Original POS transaction identifier.
    # Unique only within one site.
    # Corresponds to SaleRecord.external_id.
    external_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    # Original POS sale event timestamp.
    # IMPORTANT: This is NOT the import timestamp.
    # The application must normalize it to UTC before persistence.
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Original product name received from the POS.
    # Example: Espresso, Cappuccino, Coca-Cola.
    product_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # Original category received from the POS.
    # Example: Boissons chaudes, Soft drinks.
    # Nullable because some POS systems do not provide categories.
    pos_category: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    # Normalized RADA AI category.
    # Examples: coffee, soft_drink.
    # Nullable when the POS product has not yet been mapped.
    category: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    # Number of products sold in this POS line.
    # Maximum 100, matching engine/types.py.
    quantity: Mapped[int] = mapped_column(
        nullable=False,
    )

    # Unit selling price.
    # Decimal is mandatory; zero is valid for complimentary items.
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    # POS transaction status.
    # Supported values: paid, voided, refunded.
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="paid",
        server_default="paid",
    )

    # Original POS payload.
    # PostgreSQL uses JSONB; other databases can use JSON.
    raw: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )

    # Time when RADA AI imported this POS record.
    # This must never replace the original sale timestamp.
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Database record creation timestamp.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Last database update timestamp.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    @property
    def is_paid(self) -> bool:
        """Return True when the POS sale is paid."""
        return self.status == "paid"

    @property
    def is_reconcilable(self) -> bool:
        """Return True when the sale can generate reconciliation credits.

        A normalized category is required before reconciliation.
        """
        return self.status == "paid" and self.category is not None

    def __repr__(self) -> str:
        return (
            f"<POSSale("
            f"id={self.id}, "
            f"site_id={self.site_id!r}, "
            f"external_id={self.external_id!r}, "
            f"product_name={self.product_name!r}, "
            f"category={self.category!r}, "
            f"quantity={self.quantity}, "
            f"unit_price={self.unit_price}, "
            f"status={self.status!r}"
            f")>"
        )
