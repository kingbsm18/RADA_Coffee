"""app/schemas/settings.py — TODO: implement (see docs/architecture.md)."""
"""Pydantic schemas for RADA AI site settings."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class SiteSettingsRead(BaseModel):
    """General site settings returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    site_id: str

    reconciliation_enabled: bool
    pos_sync_enabled: bool
    cv_enabled: bool

    default_lookback_seconds: int = Field(ge=0, le=1800)
    default_grace_seconds: int = Field(ge=0, le=1800)
    default_confidence_threshold: float = Field(ge=0.0, le=1.0)

    business_day_start: int = Field(ge=0, le=23)
    data_retention_days: int = Field(ge=1, le=3650)

    alerts_enabled: bool
    auto_resolve_matched_alerts: bool

    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_aware_datetime(
        cls,
        value: datetime,
    ) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datetime values must be timezone-aware")
        return value


class SiteSettingsUpdate(BaseModel):
    """Partial update of general site settings."""

    model_config = ConfigDict(extra="forbid")

    reconciliation_enabled: bool | None = None
    pos_sync_enabled: bool | None = None
    cv_enabled: bool | None = None

    default_lookback_seconds: int | None = Field(
        default=None,
        ge=0,
        le=1800,
    )
    default_grace_seconds: int | None = Field(
        default=None,
        ge=0,
        le=1800,
    )
    default_confidence_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )

    business_day_start: int | None = Field(
        default=None,
        ge=0,
        le=23,
    )
    data_retention_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
    )

    alerts_enabled: bool | None = None
    auto_resolve_matched_alerts: bool | None = None


class SiteCategoryConfigRead(BaseModel):
    """Category-specific configuration returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    site_id: str
    category_id: UUID

    lookback_seconds: int = Field(ge=0, le=1800)
    grace_seconds: int = Field(ge=0, le=1800)
    confidence_threshold: float = Field(ge=0.0, le=1.0)

    min_unit_price: Decimal | None = Field(default=None, ge=0)
    max_unit_price: Decimal | None = Field(default=None, ge=0)

    is_enabled: bool
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_price_range(self) -> "SiteCategoryConfigRead":
        if (
            self.min_unit_price is not None
            and self.max_unit_price is not None
            and self.max_unit_price < self.min_unit_price
        ):
            raise ValueError(
                "max_unit_price cannot be lower than min_unit_price"
            )

        return self


class SiteCategoryConfigUpdate(BaseModel):
    """Partial update of one site's category configuration."""

    model_config = ConfigDict(extra="forbid")

    lookback_seconds: int | None = Field(
        default=None,
        ge=0,
        le=1800,
    )
    grace_seconds: int | None = Field(
        default=None,
        ge=0,
        le=1800,
    )
    confidence_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )

    min_unit_price: Decimal | None = Field(default=None, ge=0)
    max_unit_price: Decimal | None = Field(default=None, ge=0)

    is_enabled: bool | None = None

    @model_validator(mode="after")
    def validate_price_range(self) -> "SiteCategoryConfigUpdate":
        if (
            self.min_unit_price is not None
            and self.max_unit_price is not None
            and self.max_unit_price < self.min_unit_price
        ):
            raise ValueError(
                "max_unit_price cannot be lower than min_unit_price"
            )

        return self
