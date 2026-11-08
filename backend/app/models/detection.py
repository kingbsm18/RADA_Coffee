"""app/models/detection.py — TODO: implement (see docs/architecture.md)."""

"""Database model for computer vision detection events."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Detection(Base):
    """One unique visual event produced by a computer vision model.

    A detection represents one event, potentially containing multiple units.
    It is not a video frame or an individual tracker observation.
    """

    __tablename__ = "detections"

    __table_args__ = (
        CheckConstraint(
            "count > 0",
            name="ck_detections_count_positive",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_detections_confidence_range",
        ),
        CheckConstraint(
            "status IN ("
            "'pending', "
            "'matched', "
            "'low_confidence', "
            "'anomaly', "
            "'confirmed', "
            "'false_alarm', "
            "'auto_resolved'"
            ")",
            name="ck_detections_valid_status",
        ),
        Index(
            "ix_detections_site_timestamp",
            "site_id",
            "timestamp",
        ),
        Index(
            "ix_detections_site_category_timestamp",
            "site_id",
            "category",
            "timestamp",
        ),
        Index(
            "ix_detections_site_status_timestamp",
            "site_id",
            "status",
            "timestamp",
        ),
        Index(
            "ix_detections_camera_timestamp",
            "camera_id",
            "timestamp",
        ),
    )

    # UUID event identifier from visual_event.v1.
    # This is also the idempotency key.
    event_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )

    # Site and camera information
    site_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    camera_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Original visual event timestamp.
    # The application must normalize it to UTC before persistence.
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Normalized product category.
    # Examples: coffee, soft_drink.
    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Number of units represented by this event.
    count: Mapped[int] = mapped_column(
        nullable=False,
    )

    # Model confidence between 0 and 1.
    confidence: Mapped[float] = mapped_column(
        nullable=False,
    )

    # Reference to a stored snapshot.
    # The actual image is stored through the storage abstraction,
    # never directly inside this database table.
    snapshot_ref: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    # Version of the CV model that generated this event.
    # Corresponds to model_version in visual_event.v1.
    model_version: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Reconciliation lifecycle.
    # The engine determines state transitions.
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )

    # Database ingestion timestamp.
    # This is not the visual event timestamp.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Last persistence update.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<Detection("
            f"event_id={self.event_id!r}, "
            f"site_id={self.site_id!r}, "
            f"camera_id={self.camera_id!r}, "
            f"category={self.category!r}, "
            f"count={self.count}, "
            f"status={self.status!r}"
            f")>"
        )
