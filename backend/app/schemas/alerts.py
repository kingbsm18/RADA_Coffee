from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class AlertPage(BaseModel):
    items: list[AlertOut]
    total: int


class AlertReviewIn(BaseModel):
    status: Literal["confirmed", "false_alarm"]
    note: str | None = Field(default=None, max_length=2000)
