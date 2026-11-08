"""app/models/alert.py — TODO: implement (see docs/architecture.md)."""

"""Database model for RADA AI alerts.

An alert represents a visual detection that could not be matched
to a valid POS sale after the configured grace period.

Business rules:
- One alert per detection event.
- Estimated loss is frozen when the alert is created.
- Amounts use Decimal / NUMERIC, never float.
- Alerts can be reviewed as confirmed or false_alarm.
- Cancelled sales after service can produce cancelled_after_service alerts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Alert(Base):
    """Represents a detected discrepancy requiring manager review."""

    __tablename__ = "alerts"

    __table_args__ = (
        UniqueConstraint(
            "detection_event_id",
            name="uq_alerts_detection_event_id",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_alerts_quantity_positive",
        ),
        CheckConstraint(
            "estimated_loss >= 0",
            name="ck_alerts_estimated_loss_non_negative",
        ),
        CheckConstraint(
            "min_estimated_loss >= 0",
            name="ck_alerts_min_loss_non_negative",
        ),
        CheckConstraint(
            "max_estimated_loss >= min_estimated_loss",
            name="ck_alerts_loss_range_valid",
        ),
        CheckConstraint(
            "status IN ('anomaly', 'confirmed', 'false_alarm', 'auto_resolved')",
            name="ck_alerts_valid_status",
        ),
        Index("ix_alerts_site_detected_at", "site_id", "detected_at"),
        Index("ix_alerts_site_status", "site_id", "status"),
        Index("ix_alerts_category_detected_at", "category", "detected_at"),
    )

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    # Detection reference
    # Unique constraint guarantees one alert per detection event.
    detection_event_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Site information
    site_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Detection information
    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(
        nullable=False,
    )

    # Alert classification
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="anomaly",
        server_default="anomaly",
    )

    subtype: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    # Estimated financial impact
    # Values are frozen when the alert is created.
    estimated_loss: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    min_estimated_loss: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    max_estimated_loss: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="MAD",
        server_default="MAD",
    )

    # Manager review
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    reviewed_by: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    review_note: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    # Database creation timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<Alert("
            f"id={self.id}, "
            f"site_id={self.site_id!r}, "
            f"category={self.category!r}, "
            f"status={self.status!r}, "
            f"estimated_loss={self.estimated_loss}"
            f")>"
        )
