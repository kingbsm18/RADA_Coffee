"""Turn one raw POS row (strings) into a validated ``PosSaleIn``.

Nothing is guessed: ambiguous or malformed values reject the row (and are reported)
instead of being silently coerced.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.schemas.events import PosSaleIn

# ISO 8601 is always tried first. d/m/Y variants are common in French exports;
# m/d/Y is deliberately NOT supported because it is ambiguous with d/m/Y.
DEFAULT_TIMESTAMP_FORMATS: tuple[str, ...] = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)

STATUS_ALIASES: dict[str, str] = {
    "paid": "paid",
    "payé": "paid",
    "paye": "paid",
    "completed": "paid",
    "voided": "voided",
    "void": "voided",
    "cancelled": "voided",
    "canceled": "voided",
    "annulé": "voided",
    "annule": "voided",
    "refunded": "refunded",
    "refund": "refunded",
    "remboursé": "refunded",
    "rembourse": "refunded",
}


class RowRejected(ValueError):
    """The row cannot be imported; the message is safe to show to the user."""


def parse_timestamp(
    value: str, tz: ZoneInfo, formats: Sequence[str] = DEFAULT_TIMESTAMP_FORMATS
) -> datetime:
    text = value.strip()
    if not text:
        raise RowRejected("timestamp is empty")
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in formats:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise RowRejected(f"unrecognized timestamp format: {text!r}")
    if parsed.tzinfo is None:
        # Naive values are interpreted in the site's local timezone.
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def parse_decimal(value: str, field_name: str) -> Decimal:
    text = value.strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        raise RowRejected(f"{field_name} is empty")
    if "," in text and "." in text:
        raise RowRejected(f"{field_name} is ambiguous (thousands separator?): {value!r}")
    if text.count(",") > 1 or text.count(".") > 1:
        raise RowRejected(f"{field_name} is not a valid number: {value!r}")
    text = text.replace(",", ".")
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise RowRejected(f"{field_name} is not a valid number: {value!r}") from None
    if not number.is_finite():
        raise RowRejected(f"{field_name} is not a finite number: {value!r}")
    return number


def parse_quantity(value: str) -> int:
    number = parse_decimal(value, "quantity")
    if number != number.to_integral_value():
        raise RowRejected(f"fractional quantity is not supported: {value!r}")
    return int(number)


def parse_unit_price(value: str) -> Decimal:
    price = parse_decimal(value, "unit_price")
    if price < 0:
        raise RowRejected("unit_price cannot be negative")
    if price != price.quantize(Decimal("0.01")):
        raise RowRejected(f"unit_price has more than 2 decimals: {value!r}")
    return price.quantize(Decimal("0.01"))


def parse_status(value: str) -> str:
    key = value.strip().casefold()
    if key not in STATUS_ALIASES:
        raise RowRejected(f"unknown sale status: {value!r}")
    return STATUS_ALIASES[key]


def normalize_row(
    row: Mapping[str, str],
    *,
    site_id: str,
    tz: ZoneInfo,
    timestamp_formats: Sequence[str] = DEFAULT_TIMESTAMP_FORMATS,
) -> PosSaleIn:
    """``row`` uses canonical keys: external_id, timestamp, product_name, pos_category,
    quantity, unit_price, status."""
    try:
        return PosSaleIn(
            site_id=site_id,
            external_id=(row.get("external_id") or "").strip(),
            timestamp=parse_timestamp(row.get("timestamp") or "", tz, timestamp_formats),
            product_name=(row.get("product_name") or "").strip(),
            pos_category=((row.get("pos_category") or "").strip() or None),
            quantity=parse_quantity(row.get("quantity") or ""),
            unit_price=parse_unit_price(row.get("unit_price") or ""),
            status=parse_status(row.get("status") or "paid") if "status" in row else "paid",
            raw={key: value for key, value in row.items()},
        )
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise RowRejected(f"{location}: {first['msg']}") from None
