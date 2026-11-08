"""Alerts: one per anomalous detection (idempotent), amounts frozen at creation (R10)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, utcnow

ALERT_STATUSES = ("open", "confirmed", "false_alarm", "auto_resolved")
ALERT_SUBTYPES = ("cancelled_after_service",)


class Alert(Base):
    __tablename__ = "alert"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'confirmed', 'false_alarm', 'auto_resolved')", name="status_valid"),
        CheckConstraint("missing_qty > 0", name="missing_qty_positive"),
        CheckConstraint("loss_min <= loss_est AND loss_est <= loss_max", name="loss_range_ordered"),
        Index("ix_alert_site_status_created", "site_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"))
    # Unique: re-running the engine can never create two alerts for one detection.
    detection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("detection.id", ondelete="CASCADE"), unique=True
    )
    category: Mapped[str] = mapped_column(String(64))
    subtype: Mapped[str | None] = mapped_column(String(32), default=None)
    missing_qty: Mapped[int] = mapped_column(Integer)
    loss_est: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    loss_min: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    loss_max: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(16), default="open")
    strong: Mapped[bool] = mapped_column(Boolean, default=False)  # R12: notification-worthy
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), default=None
    )
    review_note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
