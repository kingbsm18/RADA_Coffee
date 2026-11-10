from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

Priority = Literal["high", "normal"]


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    site_id: str
    detection_id: uuid.UUID
    category: str
    subtype: str | None
    missing_qty: int
    loss_est: Decimal  # "perte estimée": an estimate, never an exact amount
    loss_min: Decimal
    loss_max: Decimal
    status: str
    strong: bool
    review_note: str | None
    created_at: datetime
    resolved_at: datetime | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def priority(self) -> Priority:
        """R11 grouping level: strong alerts (above the R12 noise level) are high priority."""
        return "high" if self.strong else "normal"


class AlertPage(BaseModel):
    items: list[AlertOut]
    total: int


class AlertReviewIn(BaseModel):
    status: Literal["confirmed", "false_alarm"]
    note: str | None = Field(default=None, max_length=2000)


class AlertGroupOut(BaseModel):
    """Anomalies of one site, local day, category and priority (R11)."""

    model_config = ConfigDict(from_attributes=True)

    site_id: str
    day: date
    category: str
    priority: Priority
    count: int
    missing_qty: int
    # "Perte détectée": open + confirmed anomalies (false alarms and auto-resolved excluded).
    loss_detected_est: Decimal
    loss_detected_min: Decimal
    loss_detected_max: Decimal
    loss_confirmed: Decimal  # only explicitly confirmed anomalies
    by_status: dict[str, int]
    open_count: int
    open_alert_ids: list[uuid.UUID]  # capped; use with POST /alerts/review


class AlertTotalsOut(BaseModel):
    count: int
    by_status: dict[str, int]
    loss_detected: Decimal
    loss_confirmed: Decimal


class AlertSummaryOut(BaseModel):
    groups: list[AlertGroupOut]
    totals: AlertTotalsOut


class BulkReviewIn(BaseModel):
    """Qualify a whole group at once. Optional, like any human decision (R11)."""

    alert_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    status: Literal["confirmed", "false_alarm"]
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("alert_ids")
    @classmethod
    def _unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("alert_ids must be unique")
        return value


class BulkReviewOut(BaseModel):
    updated: int
    alert_ids: list[uuid.UUID]
