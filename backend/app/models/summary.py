"""Daily and hourly aggregates (one row per site, day, category)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, utcnow


class DailySummary(Base):
    __tablename__ = "daily_summary"
    __table_args__ = (UniqueConstraint("site_id", "day", "category", name="uq_daily_summary_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date)  # local day of the site
    category: Mapped[str] = mapped_column(String(64))
    pos_qty: Mapped[int] = mapped_column(Integer, default=0)
    cv_qty: Mapped[int] = mapped_column(Integer, default=0)
    gap_qty: Mapped[int] = mapped_column(Integer, default=0)  # units in open/confirmed alerts
    loss_est: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    loss_min: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    loss_max: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    loss_confirmed: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    pending_count: Mapped[int] = mapped_column(Integer, default=0)
    false_alarm_count: Mapped[int] = mapped_column(Integer, default=0)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)  # after the R13 recalculation
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class HourlySummary(Base):
    __tablename__ = "hourly_summary"
    __table_args__ = (
        UniqueConstraint("site_id", "day", "hour", "category", name="uq_hourly_summary_key"),
        CheckConstraint("hour >= 0 AND hour <= 23", name="hour_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date)
    hour: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(64))
    pos_qty: Mapped[int] = mapped_column(Integer, default=0)
    cv_qty: Mapped[int] = mapped_column(Integer, default=0)
