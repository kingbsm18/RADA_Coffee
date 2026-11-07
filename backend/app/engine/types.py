"""Shared pure data types for the reconciliation engine.

No database, framework or wall-clock imports belong here. Engine modules receive
and return these types only; the persistence layer converts to and from them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, Mapping

SaleStatus = Literal["paid", "voided", "refunded"]
SUPPORTED_STATUSES = frozenset({"paid", "voided", "refunded"})

DetectionState = Literal[
    "pending",
    "matched",
    "low_confidence",
    "anomaly",
    "confirmed",
    "false_alarm",
    "auto_resolved",
]

# Absolute ceiling for any lookback/grace window (business rules, section 2).
MAX_WINDOW = timedelta(minutes=30)


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class SaleRecord:
    """Normalized POS sale line used to create reconciliation credits.

    ``timestamp`` must be the original sale event time, not the import time.
    A paid line priced at Decimal("0") is valid and creates free-item credits.
    """

    site_id: str
    external_id: str
    timestamp: datetime
    category: str
    quantity: int
    unit_price: Decimal
    status: SaleStatus

    def __post_init__(self) -> None:
        if not self.site_id.strip():
            raise ValueError("site_id cannot be empty")
        if not self.external_id.strip():
            raise ValueError("external_id cannot be empty")
        if not self.category.strip():
            raise ValueError("category cannot be empty")
        _require_aware("timestamp", self.timestamp)
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("quantity must be an integer")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if not isinstance(self.unit_price, Decimal):
            raise TypeError("unit_price must be Decimal; float is not accepted")
        if not self.unit_price.is_finite():
            raise ValueError("unit_price must be finite")
        if self.unit_price < Decimal("0"):
            raise ValueError("unit_price cannot be negative")
        if self.status not in SUPPORTED_STATUSES:
            raise ValueError(f"Unsupported sale status: {self.status!r}")


@dataclass(frozen=True, slots=True)
class Credit:
    """A single POS unit available to reconcile against one visual unit."""

    credit_id: str
    site_id: str
    sale_id: str
    unit_index: int
    timestamp: datetime
    category: str
    unit_price: Decimal


@dataclass(frozen=True, slots=True)
class Detection:
    """One unique visual event (rule R4). ``count`` = number of units it covers."""

    event_id: str
    site_id: str
    timestamp: datetime
    category: str
    count: int
    confidence: float
    snapshot_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id cannot be empty")
        if not self.site_id.strip():
            raise ValueError("site_id cannot be empty")
        if not self.category.strip():
            raise ValueError("category cannot be empty")
        _require_aware("timestamp", self.timestamp)
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise TypeError("count must be an integer")
        if self.count <= 0:
            raise ValueError("count must be positive")
        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class CategoryWindows:
    """Per-category, per-site windows (rule R5)."""

    lookback: timedelta
    grace: timedelta

    def __post_init__(self) -> None:
        for name in ("lookback", "grace"):
            value = getattr(self, name)
            if value < timedelta(0):
                raise ValueError(f"{name} cannot be negative")
            if value > MAX_WINDOW:
                raise ValueError(f"{name} cannot exceed {MAX_WINDOW}")


@dataclass(frozen=True, slots=True)
class SiteSettings:
    """Engine settings of one site, passed in explicitly (never read from a DB)."""

    site_id: str
    confidence_threshold: float
    windows: Mapping[str, CategoryWindows]

    def __post_init__(self) -> None:
        if not self.site_id.strip():
            raise ValueError("site_id cannot be empty")
        if (
            not math.isfinite(self.confidence_threshold)
            or not 0.0 <= self.confidence_threshold <= 1.0
        ):
            raise ValueError("confidence_threshold must be between 0 and 1")
        # Freeze the mapping so settings cannot change during a cycle.
        object.__setattr__(self, "windows", MappingProxyType(dict(self.windows)))

    def windows_for(self, category: str) -> CategoryWindows:
        try:
            return self.windows[category]
        except KeyError:
            raise ValueError(
                f"No windows configured for category {category!r} "
                f"on site {self.site_id!r}"
            ) from None
