"""app/schemas/analytics.py — TODO: implement (see docs/architecture.md)."""
"""Pydantic schemas for RADA AI analytics."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DailySummaryRead(BaseModel):
    """Daily analytics for one site and one product category."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    site_id: str
    summary_date: date
    category: str

    pos_units: int = Field(ge=0)
    detected_units: int = Field(ge=0)
    matched_units: int = Field(ge=0)
    anomaly_units: int = Field(ge=0)
    alerts_count: int = Field(ge=0)

    pos_revenue: Decimal = Field(ge=0)
    estimated_loss: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)

    calculated_at: datetime
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_unit_counts(self) -> "DailySummaryRead":
        if self.matched_units > self.detected_units:
            raise ValueError(
                "matched_units cannot exceed detected_units"
            )
        return self


class AnalyticsQuery(BaseModel):
    """Filters for daily analytics queries."""

    model_config = ConfigDict(extra="forbid")

    site_id: str = Field(min_length=1, max_length=64)
    start_date: date
    end_date: date
    category: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_date_range(self) -> "AnalyticsQuery":
        if self.start_date > self.end_date:
            raise ValueError(
                "start_date must be earlier than or equal to end_date"
            )

        return self


class AnalyticsTotals(BaseModel):
    """Aggregated totals for a requested reporting period.

    These values must be calculated by the analytics service.
    They are not stored directly in the DailySummary model.
    """

    model_config = ConfigDict(extra="forbid")

    site_id: str
    start_date: date
    end_date: date
    category: str | None = None

    pos_units: int = Field(ge=0)
    detected_units: int = Field(ge=0)
    matched_units: int = Field(ge=0)
    anomaly_units: int = Field(ge=0)
    alerts_count: int = Field(ge=0)

    pos_revenue: Decimal = Field(ge=0)
    estimated_loss: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_totals(self) -> "AnalyticsTotals":
        if self.start_date > self.end_date:
            raise ValueError("Invalid analytics date range")

        if self.matched_units > self.detected_units:
            raise ValueError(
                "matched_units cannot exceed detected_units"
            )

        return self


class DailySummaryListResponse(BaseModel):
    """List of daily summaries."""

    items: list[DailySummaryRead]
    total: int = Field(ge=0)


class AnalyticsOverviewResponse(BaseModel):
    """Overview combining period totals and daily breakdown."""

    totals: AnalyticsTotals
    daily_summaries: list[DailySummaryRead]
