"""Per-site engine settings (windows, confidence threshold)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, JSONType, UTCDateTime, utcnow
from app.engine.types import CategoryWindows, SiteSettings

# Starting values only: measure the real p95 delays at the pilot café (R5, R12).
DEFAULT_WINDOWS_MINUTES: dict[str, dict[str, int]] = {
    "coffee": {"lookback": 25, "grace": 12},
    "soft_drink": {"lookback": 10, "grace": 7},
}
DEFAULT_CONFIDENCE_THRESHOLD = 0.6


class SiteSettingsModel(Base):
    __tablename__ = "site_settings"
    __table_args__ = (
        CheckConstraint("confidence_threshold >= 0 AND confidence_threshold <= 1", name="threshold_range"),
    )

    site_id: Mapped[str] = mapped_column(ForeignKey("site.id", ondelete="CASCADE"), primary_key=True)
    confidence_threshold: Mapped[float] = mapped_column(Float, default=DEFAULT_CONFIDENCE_THRESHOLD)
    # {"coffee": {"lookback": 25, "grace": 12}, ...} in minutes (max 30, see engine.types)
    windows: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    snapshot_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    snapshot_upload_policy: Mapped[str] = mapped_column(String(16), default="on_alert")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    def to_engine(self) -> SiteSettings:
        """Convert to the pure engine type (validates the 30-minute ceiling)."""
        windows = {
            category: CategoryWindows(
                lookback=timedelta(minutes=int(values["lookback"])),
                grace=timedelta(minutes=int(values["grace"])),
            )
            for category, values in self.windows.items()
        }
        return SiteSettings(
            site_id=self.site_id,
            confidence_threshold=self.confidence_threshold,
            windows=windows,
        )
