"""app/models/site_settings.py — TODO: implement (see docs/architecture.md)."""
"""Database model for site-level RADA AI settings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SiteSettings(Base):
    """General configuration for one RADA AI site.

    Category-specific reconciliation settings belong to
    SiteCategoryConfig in category.py.

    This model stores site-wide operational settings.
    """

    __tablename__ = "site_settings"

    __table_args__ = (
        UniqueConstraint(
            "site_id",
            name="uq_site_settings_site_id",
        ),
        CheckConstraint(
            "default_lookback_seconds >= 0 "
            "AND default_lookback_seconds <= 1800",
            name="ck_site_settings_lookback_range",
        ),
        CheckConstraint(
            "default_grace_seconds >= 0 "
            "AND default_grace_seconds <= 1800",
            name="ck_site_settings_grace_range",
        ),
        CheckConstraint(
            "default_confidence_threshold >= 0 "
            "AND default_confidence_threshold <= 1",
            name="ck_site_settings_confidence_range",
        ),
        CheckConstraint(
            "business_day_start >= 0 AND business_day_start <= 23",
            name="ck_site_settings_business_day_start",
        ),
        CheckConstraint(
            "data_retention_days >= 1 AND data_retention_days <= 3650",
            name="ck_site_settings_retention_range",
        ),
        Index(
            "ix_site_settings_reconciliation_enabled",
            "reconciliation_enabled",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    # Stable site identifier, matching Site.id.
    site_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    # Enable or disable the reconciliation engine for this site.
    reconciliation_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    # Enable POS ingestion for this site.
    pos_sync_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    # Enable computer vision event processing.
    cv_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    # Default matching window, in seconds.
    # Category-specific values can override this setting.
    default_lookback_seconds: Mapped[int] = mapped_column(
        nullable=False,
        default=600,
        server_default="600",
    )

    # Default grace period before an unmatched detection
    # can become an anomaly.
    default_grace_seconds: Mapped[int] = mapped_column(
        nullable=False,
        default=600,
        server_default="600",
    )

    # Default minimum confidence for accepted CV detections.
    default_confidence_threshold: Mapped[float] = mapped_column(
        nullable=False,
        default=0.80,
        server_default="0.80",
    )

    # Local hour at which the business day starts.
    # Example: 6 means the business day starts at 06:00.
    business_day_start: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )

    # Number of days to retain operational data.
    # Actual deletion must be performed by a retention job.
    data_retention_days: Mapped[int] = mapped_column(
        nullable=False,
        default=365,
        server_default="365",
    )

    # Whether the system should create alerts for anomalies.
    alerts_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    # Whether previously open alerts can be automatically
    # resolved when the reconciliation engine matches them.
    auto_resolve_matched_alerts: Mapped[bool] = mapped_column(
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
            f"<SiteSettings("
            f"id={self.id}, "
            f"site_id={self.site_id!r}, "
            f"reconciliation_enabled={self.reconciliation_enabled}, "
            f"pos_sync_enabled={self.pos_sync_enabled}, "
            f"cv_enabled={self.cv_enabled}"
            f")>"
        )
