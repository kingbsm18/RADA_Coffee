"""app/schemas/alerts.py — TODO: implement (see docs/architecture.md)."""
"""Pydantic schemas for RADA AI alerts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AlertStatus(str, Enum):
    ANOMALY = "anomaly"
    CONFIRMED = "confirmed"
    FALSE_ALARM = "false_alarm"
    AUTO_RESOLVED = "auto_resolved"


class AlertReviewStatus(str, Enum):
    """Statuses a manager may explicitly assign during review."""

    CONFIRMED = "confirmed"
    FALSE_ALARM = "false_alarm"


class AlertRead(BaseModel):
    """Alert representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    detection_event_id: str
    site_id: str
    category: str
    detected_at: datetime
    quantity: int = Field(gt=0)

    status: AlertStatus
    subtype: str | None = None

    estimated_loss: Decimal = Field(ge=0)
    min_estimated_loss: Decimal = Field(ge=0)
    max_estimated_loss: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)

    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    review_note: str | None = None

    created_at: datetime

    @field_validator("detected_at", "reviewed_at", "created_at")
    @classmethod
    def validate_aware_datetime(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("Datetime values must be timezone-aware")
        return value


class AlertReviewRequest(BaseModel):
    """Request to review an alert as confirmed or false alarm."""

    model_config = ConfigDict(extra="forbid")

    status: AlertReviewStatus
    review_note: str | None = Field(default=None, max_length=1000)


class AlertListResponse(BaseModel):
    """Paginated alert listing."""

    items: list[AlertRead]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
