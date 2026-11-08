"""Visual events received from the edge (rule R4)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, UTCDateTime, utcnow

DETECTION_STATES = (
    "pending",
    "matched",
    "low_confidence",
    "anomaly",
    "confirmed",
    "false_alarm",
    "auto_resolved",
)


class Detection(Base):
    __tablename__ = "detection"
    __table_args__ = (
        UniqueConstraint("site_id", "event_id", name="uq_detection_site_event"),
        CheckConstraint("count > 0", name="count_positive"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "state IN ('pending', 'matched', 'low_confidence', 'anomaly', "
            "'confirmed', 'false_alarm', 'auto_resolved')",
            name="state_valid",
        ),
        Index("ix_detection_site_timestamp", "site_id", "timestamp"),
        Index("ix_detection_site_state", "site_id", "state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"))
    event_id: Mapped[str] = mapped_column(String(64))  # idempotency key from the edge
    camera_id: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime)
    category: Mapped[str] = mapped_column(String(64))
    count: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float)
    snapshot_ref: Mapped[str | None] = mapped_column(String(255), default=None)
    model_version: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20), default="pending")
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
