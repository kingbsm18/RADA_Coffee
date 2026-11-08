"""app/models/summary.py — TODO: implement (see docs/architecture.md)."""
"""Database model for daily RADA AI reconciliation summaries."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DailySummary(Base):
    """Daily reconciliation statistics for one site and category.

    One row represents one site's daily statistics for one
    normalized category, such as coffee or soft_drink.

    These are aggregated reporting values, not individual events.

    Important:
    - POS sales without a CV detection are not automatically losses.
    - Anomaly units refer to unmatched detections after the grace period.
    - Financial values must use Decimal / NUMERIC, never float.
    - Category statistics remain independent.
    """

    __tablename__ = "daily_summaries"

    __table_args__ = (
        UniqueConstraint(
            "site_id",
            "summary_date",
            "category",
            name="uq_daily_summaries_site_date_category",
        ),
        CheckConstraint(
            "pos_units >= 0",
            name="ck_daily_summaries_pos_units_non_negative",
        ),
        CheckConstraint(
            "detected_units >= 0",
            name="ck_daily_summaries_detected_units_non_negative",
        ),
        CheckConstraint(
            "matched_units >= 0",
            name="ck_daily_summaries_matched_units_non_negative",
        ),
        CheckConstraint(
            "anomaly_units >= 0",
            name="ck_daily_summaries_anomaly_units_non_negative",
        ),
        CheckConstraint(
            "alerts_count >= 0",
            name="ck_daily_summaries_alerts_non_negative",
        ),
        CheckConstraint(
            "pos_revenue >= 0",
            name="ck_daily_summaries_revenue_non_negative",
        ),
        CheckConstraint(
            "estimated_loss >= 0",
            name="ck_daily_summaries_loss_non_negative",
        ),
        CheckConstraint(
            "matched_units <= detected_units",
            name="ck_daily_summaries_matched_not_above_detected",
        ),
        Index(
            "ix_daily_summaries_site_date",
            "site_id",
            "summary_date",
        ),
        Index(
            "ix_daily_summaries_category_date",
            "category",
            "summary_date",
        ),
        Index(
            "ix_daily_summaries_calculated_at",
            "calculated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    # Site associated with this summary.
    site_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Local business date for this summary.
    # The application must calculate this using the site's timezone
    # and business_day_start setting.
    summary_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    # Normalized category.
    # Examples: coffee, soft_drink.
    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Number of POS units sold in this category.
    # This is a sales metric, not a loss metric.
    pos_units: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )

    # Total number of units represented by CV detections.
    detected_units: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )

    # Number of detected units successfully matched to POS credits.
    matched_units: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )

    # Number of unmatched detected units that passed the grace period.
    # This is an anomaly indicator, not proof of theft.
    anomaly_units: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )

    # Number of alerts created for this site/category/day.
    alerts_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )

    # Total POS revenue for this category and business date.
    pos_revenue: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )

    # Estimated financial impact associated with anomalies.
    # This is an estimate for review, not a confirmed loss.
    estimated_loss: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )

    # ISO currency code, normally MAD for Moroccan sites.
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="MAD",
        server_default="MAD",
    )

    # Timestamp of the last aggregation/recalculation.
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
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
    def unmatched_detected_units(self) -> int:
        """Return detected units not yet matched.

        This value may include detections still inside their grace
        period, so it must not automatically be treated as anomalies.
        """
        return max(
            self.detected_units - self.matched_units,
            0,
        )

    @property
    def match_rate(self) -> float:
        """Return the matching rate as a value between 0 and 1."""
        if self.detected_units == 0:
            return 0.0

        return self.matched_units / self.detected_units

    def __repr__(self) -> str:
        return (
            f"<DailySummary("
            f"site_id={self.site_id!r}, "
            f"summary_date={self.summary_date}, "
            f"category={self.category!r}, "
            f"pos_units={self.pos_units}, "
            f"detected_units={self.detected_units}, "
            f"matched_units={self.matched_units}, "
            f"anomaly_units={self.anomaly_units}"
            f")>"
        )
