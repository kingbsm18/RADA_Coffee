"""POS adapter interfaces. One adapter per vendor, all producing ``PosSaleIn``."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from app.schemas.events import PosSaleIn


class PosImportError(Exception):
    """The whole file/response is unusable (bad encoding, missing columns, too large)."""


@dataclass(frozen=True, slots=True)
class RowError:
    row: int  # 1-based data row number (header excluded)
    message: str


@dataclass(slots=True)
class ParseResult:
    sales: list[PosSaleIn] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    rows_received: int = 0


class FilePosAdapter(Protocol):
    """Adapter reading an exported file (CSV): the MVP fallback when no API exists."""

    name: str

    def parse(self, content: bytes, *, site_id: str, tz: ZoneInfo) -> ParseResult: ...


class ApiPosAdapter(ABC):
    """Adapter polling a vendor API. Subclass once the real POS and its fields are known."""

    name: str

    @abstractmethod
    def fetch_sales(
        self, *, site_id: str, since: datetime, until: datetime, tz: ZoneInfo
    ) -> ParseResult:
        """Return sales whose event time is in [since, until)."""
