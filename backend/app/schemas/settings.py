from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.engine.types import MAX_WINDOW
from app.schemas.events import SITE_PATTERN

MAX_WINDOW_MINUTES = int(MAX_WINDOW.total_seconds() // 60)


class WindowsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lookback: int = Field(ge=0, le=MAX_WINDOW_MINUTES, description="minutes before the item")
    grace: int = Field(ge=0, le=MAX_WINDOW_MINUTES, description="minutes after the item")


class SiteSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confidence_threshold: float = Field(ge=0, le=1)
    windows: dict[str, WindowsIn] = Field(min_length=1)
    snapshot_retention_days: int = Field(ge=1, le=365)
    snapshot_upload_policy: str = Field(pattern=r"^(always|on_alert|never)$")

    @field_validator("windows")
    @classmethod
    def _category_names(cls, value: dict[str, WindowsIn]) -> dict[str, WindowsIn]:
        for name in value:
            if not name or len(name) > 64 or name != name.strip():
                raise ValueError(f"invalid category name: {name!r}")
        return value


class SiteSettingsOut(BaseModel):
    site_id: str
    confidence_threshold: float
    windows: dict[str, WindowsIn]
    snapshot_retention_days: int
    snapshot_upload_policy: str
    updated_at: datetime


class CategoryMappingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_field: str = Field(pattern=r"^(product_name|pos_category)$")
    match_value: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=64)


class CategoryMappingsIn(BaseModel):
    items: list[CategoryMappingItem] = Field(max_length=2000)


class CategoryMappingsOut(BaseModel):
    items: list[CategoryMappingItem]


class SiteCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=SITE_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    timezone: str = "Africa/Casablanca"
    currency: str = Field(default="MAD", pattern=r"^[A-Z]{3}$")


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    timezone: str
    currency: str
    active: bool
    created_at: datetime


class SiteCreatedOut(BaseModel):
    site: SiteOut
    edge_key: str  # shown once, only its hash is stored


class EdgeKeyOut(BaseModel):
    edge_key: str


class ImportBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    status: str
    rows_received: int
    rows_inserted: int
    rows_updated: int
    rows_unchanged: int
    rows_rejected: int
    started_at: datetime
    completed_at: datetime | None
