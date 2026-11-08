"""app/pos/normalizer.py — TODO: implement (see docs/architecture.md)."""
"""Normalize raw POS payloads into canonical RADA AI sale records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from app.engine.types import MAX_SALE_QUANTITY, SUPPORTED_STATUSES
from app.pos.category_mapping import CategoryMapper, create_default_mapper


class POSNormalizationError(ValueError):
    """Base exception for POS normalization errors."""


class MissingPOSFieldError(POSNormalizationError):
    """Raised when a required POS field is missing."""


class InvalidPOSFieldError(POSNormalizationError):
    """Raised when a POS field has an invalid value."""


@dataclass(frozen=True, slots=True)
class NormalizedPOSSale:
    """Canonical POS sale line ready for persistence."""

    site_id: str
    external_id: str
    timestamp: datetime
    product_name: str
    pos_category: str | None
    category: str
    quantity: int
    unit_price: Decimal
    status: str
    raw: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.site_id.strip():
            raise InvalidPOSFieldError("site_id cannot be empty")

        if not self.external_id.strip():
            raise InvalidPOSFieldError("external_id cannot be empty")

        if not self.product_name.strip():
            raise InvalidPOSFieldError("product_name cannot be empty")

        if not self.category.strip():
            raise InvalidPOSFieldError("category cannot be empty")

        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise InvalidPOSFieldError("timestamp must be timezone-aware")

        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise InvalidPOSFieldError("quantity must be an integer")

        if not 1 <= self.quantity <= MAX_SALE_QUANTITY:
            raise InvalidPOSFieldError(
                f"quantity must be between 1 and {MAX_SALE_QUANTITY}"
            )

        if not isinstance(self.unit_price, Decimal):
            raise InvalidPOSFieldError("unit_price must be Decimal")

        if not self.unit_price.is_finite() or self.unit_price < Decimal("0"):
            raise InvalidPOSFieldError("unit_price must be finite and non-negative")

        if self.status not in SUPPORTED_STATUSES:
            raise InvalidPOSFieldError(
                f"Unsupported sale status: {self.status!r}"
            )


def _required_string(
    record: Mapping[str, Any],
    field: str,
) -> str:
    value = record.get(field)

    if value is None:
        raise MissingPOSFieldError(f"Missing required field: {field}")

    if not isinstance(value, str) or not value.strip():
        raise InvalidPOSFieldError(
            f"{field} must be a non-empty string"
        )

    return value.strip()


def _parse_timestamp(value: Any) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC."""

    if isinstance(value, datetime):
        parsed = value

    elif isinstance(value, str):
        cleaned = value.strip()

        if not cleaned:
            raise InvalidPOSFieldError("timestamp cannot be empty")

        # Support ISO-8601 UTC suffix.
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"

        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError as exc:
            raise InvalidPOSFieldError(
                f"Invalid ISO-8601 timestamp: {value!r}"
            ) from exc

    else:
        raise InvalidPOSFieldError(
            "timestamp must be a datetime or ISO-8601 string"
        )

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidPOSFieldError(
            "timestamp must include timezone information"
        )

    return parsed.astimezone(timezone.utc)


def _parse_decimal(value: Any) -> Decimal:
    """Convert a POS price without introducing binary float errors."""

    if isinstance(value, bool) or isinstance(value, float):
        raise InvalidPOSFieldError(
            "unit_price must be a string, integer or Decimal; float is not accepted"
        )

    if not isinstance(value, (str, int, Decimal)):
        raise InvalidPOSFieldError(
            "unit_price must be a string, integer or Decimal"
        )

    try:
        price = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise InvalidPOSFieldError(
            f"Invalid unit_price: {value!r}"
        ) from exc

    if not price.is_finite() or price < Decimal("0"):
        raise InvalidPOSFieldError(
            "unit_price must be finite and non-negative"
        )

    return price


def normalize_pos_record(
    record: Mapping[str, Any],
    site_id: str,
    mapper: CategoryMapper | None = None,
) -> NormalizedPOSSale:
    """Convert one raw POS record into a validated RADA sale.

    Required input fields:
        external_id, timestamp, product_name, quantity, unit_price, status

    pos_category is optional and may be None.

    The original POS timestamp is always preserved as the sale timestamp.
    Import time must never be substituted for it.
    """

    if not isinstance(record, Mapping):
        raise InvalidPOSFieldError("POS record must be a mapping")

    if not isinstance(site_id, str) or not site_id.strip():
        raise InvalidPOSFieldError("site_id cannot be empty")

    external_id = _required_string(record, "external_id")
    product_name = _required_string(record, "product_name")

    timestamp = _parse_timestamp(record.get("timestamp"))

    quantity = record.get("quantity")

    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise InvalidPOSFieldError("quantity must be an integer")

    if not 1 <= quantity <= MAX_SALE_QUANTITY:
        raise InvalidPOSFieldError(
            f"quantity must be between 1 and {MAX_SALE_QUANTITY}"
        )

    unit_price = _parse_decimal(record.get("unit_price"))

    status = record.get("status")

    if not isinstance(status, str):
        raise InvalidPOSFieldError("status must be a string")

    status = status.strip().lower()

    if status not in SUPPORTED_STATUSES:
        raise InvalidPOSFieldError(
            f"Unsupported sale status: {status!r}"
        )

    pos_category = record.get("pos_category")

    if pos_category is not None:
        if not isinstance(pos_category, str):
            raise InvalidPOSFieldError(
                "pos_category must be a string or None"
            )

        pos_category = pos_category.strip() or None

    category_mapper = mapper or create_default_mapper()

    try:
        category = category_mapper.resolve(
            pos_category=pos_category,
            product_name=product_name,
        )
    except ValueError as exc:
        raise POSNormalizationError(
            f"Cannot map POS sale {external_id!r}: {exc}"
        ) from exc

    return NormalizedPOSSale(
        site_id=site_id.strip(),
        external_id=external_id,
        timestamp=timestamp,
        product_name=product_name,
        pos_category=pos_category,
        category=category,
        quantity=quantity,
        unit_price=unit_price,
        status=status,
        raw=dict(record),
    )


def to_sale_record(sale: NormalizedPOSSale):
    """Convert a normalized POS sale into the pure engine SaleRecord."""

    from app.engine.types import SaleRecord

    return SaleRecord(
        site_id=sale.site_id,
        external_id=sale.external_id,
        timestamp=sale.timestamp,
        category=sale.category,
        quantity=sale.quantity,
        unit_price=sale.unit_price,
        status=sale.status,
    )
