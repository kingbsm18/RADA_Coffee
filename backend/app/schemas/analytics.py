from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class DailySummaryOut(BaseModel):
    day: date
    category: str
    pos_qty: int
    cv_qty: int
    gap_qty: int
    loss_est: Decimal
    loss_min: Decimal
    loss_max: Decimal
    loss_confirmed: Decimal
    pending_count: int
    false_alarm_count: int
    is_final: bool


class HourlyPointOut(BaseModel):
    hour: int
    category: str
    pos_qty: int
    cv_qty: int
