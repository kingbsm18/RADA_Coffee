"""Edge -> backend contracts. Mirrors contracts/*.schema.json (checked by tests)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.engine.types import MAX_SALE_QUANTITY

SITE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value


class VisualEventIn(BaseModel):
    """visual_event.v1"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: Literal["visual_event.v1"] = Field(alias="schema")
    event_id: uuid.UUID
    site_id: str = Field(pattern=SITE_PATTERN)
    camera_id: str = Field(min_length=1, max_length=64)
    timestamp: datetime
    category: str = Field(min_length=1, max_length=64)
    count: int = Field(ge=1, le=MAX_SALE_QUANTITY)
    confidence: float = Field(ge=0, le=1)
    snapshot_ref: str | None = Field(default=None, max_length=255)
    model_version: str = Field(min_length=1, max_length=64)

    _aware = field_validator("timestamp")(_require_aware)


class PosSaleIn(BaseModel):
    """pos_sale.v1 (normalized sale line)."""

    model_config = ConfigDict(extra="forbid")

    site_id: str = Field(pattern=SITE_PATTERN)
    external_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    product_name: str = Field(min_length=1, max_length=200)
    pos_category: str | None = Field(default=None, max_length=200)
    quantity: int = Field(ge=1, le=MAX_SALE_QUANTITY)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    status: Literal["paid", "voided", "refunded"]
    raw: dict[str, Any] | None = None

    _aware = field_validator("timestamp")(_require_aware)


class EventIngestResult(BaseModel):
    status: Literal["created", "duplicate"]
    id: uuid.UUID


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: str
    site_id: str
    camera_id: str
    timestamp: datetime
    category: str
    count: int
    confidence: float
    snapshot_ref: str | None
    model_version: str
    state: str


class EventPage(BaseModel):
    items: list[EventOut]
    total: int


class RowErrorOut(BaseModel):
    row: int
    message: str


class ImportReportOut(BaseModel):
    batch_id: uuid.UUID
    rows_received: int
    rows_inserted: int
    rows_updated: int
    rows_unchanged: int
    rows_rejected: int
    errors: list[RowErrorOut]
    unmapped: list[str]  # POS products/categories with no category mapping yet
    status_changes: list[str]  # external ids whose status changed (e.g. paid -> voided)
    earliest: datetime | None  # first/last sale time read from the file (UTC): check them!
    latest: datetime | None
