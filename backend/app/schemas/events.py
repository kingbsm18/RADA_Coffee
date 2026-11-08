"""app/schemas/events.py — TODO: implement (see docs/architecture.md)."""
"""Pydantic schemas for computer vision events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


DetectionStatus = Literal[
    "pending",
    "matched",
    "low_confidence",
    "anomaly",
    "confirmed",
    "false_alarm",
    "auto_resolved",
]


class VisualEventCreate(BaseModel):
    """Incoming event following the visual_event.v1 contract."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visual_event.v1"] = Field(
        default="visual_event.v1",
        alias="schema",
    )

    event_id: UUID
    site_id: str = Field(min_length=1, max_length=64)
    camera_id: str = Field(min_length=1, max_length=64)
    timestamp: datetime
    category: str = Field(min_length=1, max_length=64)
    count: int = Field(gt=0)
    confidence: float = Field(ge=0.0, le=1.0)
    snapshot_ref: str | None = Field(default=None, max_length=1024)
    model_version: str = Field(min_length=1, max_length=64)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "timestamp must include timezone information"
            )

        return value.astimezone(timezone.utc)


class DetectionRead(BaseModel):
    """Detection representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    site_id: str
    camera_id: str
    timestamp: datetime
    category: str
    count: int = Field(gt=0)
    confidence: float = Field(ge=0.0, le=1.0)
    snapshot_ref: str | None = None
    model_version: str
    status: DetectionStatus
    created_at: datetime
    updated_at: datetime

    @field_validator("timestamp", "created_at", "updated_at")
    @classmethod
    def validate_aware_datetime(
        cls,
        value: datetime,
    ) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datetime values must be timezone-aware")
        return value


class VisualEventBatch(BaseModel):
    """Batch of visual events received from an Edge AI device."""

    model_config = ConfigDict(extra="forbid")

    events: list[VisualEventCreate] = Field(
        min_length=1,
        max_length=500,
    )


class EventIngestionResult(BaseModel):
    """Result of processing one incoming visual event."""

    event_id: UUID
    accepted: bool
    duplicate: bool = False
    message: str | None = None


class EventBatchIngestionResult(BaseModel):
    """Result of processing a batch of visual events."""

    received: int = Field(ge=0)
    accepted: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    rejected: int = Field(ge=0)
    results: list[EventIngestionResult]
