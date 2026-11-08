"""app/pos/base.py — TODO: implement (see docs/architecture.md)."""
"""Common interface and data structures for POS integrations.

All POS connectors must implement the same asynchronous interface.
The adapter retrieves raw POS records; normalization and reconciliation
are handled by separate modules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping


class POSAdapterError(Exception):
    """Base exception for POS adapter errors."""


class POSConnectionError(POSAdapterError):
    """Raised when the adapter cannot connect to the POS system."""


class POSAuthenticationError(POSAdapterError):
    """Raised when POS credentials are invalid or expired."""


class POSDataError(POSAdapterError):
    """Raised when the POS returns invalid or incomplete data."""


def _require_aware(name: str, value: datetime) -> None:
    """Ensure a datetime contains timezone information."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class POSPage:
    """One page of raw POS sale records.

    records:
        Raw records returned by the POS provider.

    next_cursor:
        Pagination cursor for retrieving the next page.
        None means there are no more pages.
    """

    records: tuple[Mapping[str, Any], ...]
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        normalized_records: list[Mapping[str, Any]] = []

        for index, record in enumerate(self.records):
            if not isinstance(record, Mapping):
                raise POSDataError(
                    f"POS record at index {index} must be a mapping"
                )

            # Prevent accidental top-level mutation after retrieval.
            normalized_records.append(
                MappingProxyType(dict(record))
            )

        object.__setattr__(
            self,
            "records",
            tuple(normalized_records),
        )

        if self.next_cursor is not None:
            if not isinstance(self.next_cursor, str):
                raise POSDataError("next_cursor must be a string or None")

            if not self.next_cursor.strip():
                raise POSDataError("next_cursor cannot be empty")


class POSAdapter(ABC):
    """Abstract base class for POS system integrations.

    Each concrete adapter is responsible for:
    - Connecting to its POS provider.
    - Authenticating when required.
    - Retrieving sales within a requested time range.
    - Handling provider-specific pagination.
    - Returning raw records in POSPage objects.

    The adapter must NOT:
    - Create reconciliation credits.
    - Generate alerts.
    - Decide whether a sale is an anomaly.
    - Replace the original POS event timestamp with import time.

    Raw records are passed to the normalizer, which converts them
    into the canonical POS sale contract.
    """

    def __init__(self, site_id: str) -> None:
        if not isinstance(site_id, str) or not site_id.strip():
            raise ValueError("site_id cannot be empty")

        self.site_id = site_id.strip()

    @property
    def adapter_name(self) -> str:
        """Return the adapter implementation name."""
        return self.__class__.__name__

    async def test_connection(self) -> bool:
        """Test connectivity with the POS provider.

        Concrete adapters should override this method to perform
        a real health check.

        Returns:
            True when the connection is available.
        """
        raise NotImplementedError(
            f"{self.adapter_name} must implement test_connection()"
        )

    @abstractmethod
    async def fetch_sales(
        self,
        start_time: datetime,
        end_time: datetime,
        cursor: str | None = None,
    ) -> POSPage:
        """Fetch one page of POS sales within a time range.

        Args:
            start_time:
                Inclusive beginning of the requested period.

            end_time:
                Exclusive end of the requested period.

            cursor:
                Optional pagination cursor returned by the previous page.

        Returns:
            POSPage containing raw POS records and an optional next cursor.

        Important:
            The adapter must preserve the original sale event timestamp.
            It must never substitute the synchronization/import timestamp.

        Raises:
            POSConnectionError: if the POS provider is unavailable.
            POSAuthenticationError: if authentication fails.
            POSDataError: if the provider returns invalid data.
        """
        _require_aware("start_time", start_time)
        _require_aware("end_time", end_time)

        if start_time >= end_time:
            raise ValueError("start_time must be earlier than end_time")

        if cursor is not None and not cursor.strip():
            raise ValueError("cursor cannot be empty")

        raise NotImplementedError(
            "Concrete adapters must implement fetch_sales()"
        )

    async def close(self) -> None:
        """Release provider resources.

        Override this method when the adapter owns HTTP clients,
        database connections or other external resources.
        """
        return None

    async def __aenter__(self) -> POSAdapter:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        await self.close()
