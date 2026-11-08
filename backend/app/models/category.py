"""app/models/category.py — TODO: implement (see docs/architecture.md)."""

"""Database model for product categories and site-specific settings."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Category(Base):
    """A product category used by POS normalization and CV reconciliation."""

    __tablename__ = "categories"

    __table_args__ = (
        UniqueConstraint(
            "code",
            name="uq_categories_code",
        ),
        CheckConstraint(
            "code = lower(code)",
            name="ck_categories_code_lowercase",
        ),
        Index("ix_categories_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    # Stable identifier used by the engine and POS mapping.
    # Examples: coffee, soft_drink.
    code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<Category("
            f"id={self.id}, "
            f"code={self.code!r}, "
            f"name={self.name!r}, "
            f"is_active={self.is_active}"
            f")>"
        )


class SiteCategoryConfig(Base):
    """Per-site reconciliation settings for one product category."""

    __tablename__ = "site_category_configs"

    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "category_id",
            name="uq_site_category_configs_site_category",
        ),
        CheckConstraint(
            "lookback_seconds >= 0 AND lookback_seconds <= 1800",
            name="ck_site_category_lookback_range",
        ),
        CheckConstraint(
            "grace_seconds >= 0 AND grace_seconds <= 1800",
            name="ck_site_category_grace_range",
        ),
        CheckConstraint(
            "confidence_threshold >= 0 AND confidence_threshold <= 1",
            name="ck_site_category_confidence_range",
        ),
        CheckConstraint(
            "min_unit_price >= 0",
            name="ck_site_category_min_price_non_negative",
        ),
        CheckConstraint(
            "max_unit_price >= min_unit_price",
            name="ck_site_category_price_range",
        ),
        Index(
            "ix_site_category_configs_site",
            "site_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    # Site identifier is kept as a string to match the existing contracts.
    # A Site model and its foreign key can be added when that model exists.
    site_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Reconciliation windows are stored in seconds.
    # Maximum: 30 minutes, matching engine/types.py.
    lookback_seconds: Mapped[int] = mapped_column(
        nullable=False,
        default=600,
        server_default="600",
    )

    grace_seconds: Mapped[int] = mapped_column(
        nullable=False,
        default=600,
        server_default="600",
    )

    confidence_threshold: Mapped[float] = mapped_column(
        nullable=False,
        default=0.80,
        server_default="0.80",
    )

    # Optional category-specific price bounds for reporting.
    # The pricing engine remains responsible for calculating estimates.
    min_unit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    max_unit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    @property
    def lookback(self) -> timedelta:
        """Return the configured lookback window."""
        return timedelta(seconds=self.lookback_seconds)

    @property
    def grace(self) -> timedelta:
        """Return the configured grace window."""
        return timedelta(seconds=self.grace_seconds)

    def __repr__(self) -> str:
        return (
            f"<SiteCategoryConfig("
            f"site_id={self.site_id!r}, "
            f"category_id={self.category_id}, "
            f"lookback_seconds={self.lookback_seconds}, "
            f"grace_seconds={self.grace_seconds}"
            f")>"
        )
