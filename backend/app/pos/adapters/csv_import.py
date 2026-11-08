"""CSV adapter: the MVP fallback while the POS vendor/API is not chosen.

One CSV line = one sale line. ``external_id`` must be unique per line (if the POS
exports tickets with several items, combine ticket and line number in that column).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping, Sequence
from zoneinfo import ZoneInfo

from app.pos.base import ParseResult, PosImportError, RowError
from app.pos.normalizer import DEFAULT_TIMESTAMP_FORMATS, RowRejected, normalize_row

CANONICAL_COLUMNS = (
    "external_id",
    "timestamp",
    "product_name",
    "pos_category",
    "quantity",
    "unit_price",
    "status",
)
REQUIRED_COLUMNS = ("external_id", "timestamp", "product_name", "quantity", "unit_price")


class CsvImportAdapter:
    name = "csv"

    def __init__(
        self,
        *,
        column_map: Mapping[str, str] | None = None,
        timestamp_formats: Sequence[str] = DEFAULT_TIMESTAMP_FORMATS,
        max_rows: int = 50_000,
    ) -> None:
        """``column_map`` maps canonical names to the CSV's own header names."""
        self._column_map = {c: c for c in CANONICAL_COLUMNS}
        if column_map:
            unknown = set(column_map) - set(CANONICAL_COLUMNS)
            if unknown:
                raise ValueError(f"unknown canonical columns: {sorted(unknown)}")
            self._column_map.update(column_map)
        self._timestamp_formats = tuple(timestamp_formats)
        self._max_rows = max_rows

    def parse(self, content: bytes, *, site_id: str, tz: ZoneInfo) -> ParseResult:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise PosImportError("file must be UTF-8 encoded") from None

        first_line = text.split("\n", 1)[0]
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if reader.fieldnames is None:
            raise PosImportError("file is empty")

        headers = {name.strip().casefold(): name for name in reader.fieldnames if name}
        source: dict[str, str] = {}
        for canonical, header in self._column_map.items():
            actual = headers.get(header.strip().casefold())
            if actual is not None:
                source[canonical] = actual
        missing = [c for c in REQUIRED_COLUMNS if c not in source]
        if missing:
            raise PosImportError(f"missing required columns: {', '.join(missing)}")

        result = ParseResult()
        seen: dict[str, dict[str, str]] = {}
        for index, raw_row in enumerate(reader, start=1):
            if index > self._max_rows:
                raise PosImportError(f"too many rows (max {self._max_rows})")
            result.rows_received += 1
            row = {
                canonical: (raw_row.get(actual) or "")
                for canonical, actual in source.items()
            }
            try:
                sale = normalize_row(
                    row, site_id=site_id, tz=tz, timestamp_formats=self._timestamp_formats
                )
            except RowRejected as exc:
                result.errors.append(RowError(index, str(exc)))
                continue

            previous = seen.get(sale.external_id)
            if previous is not None:
                if previous == row:
                    continue  # exact repeat inside the file: harmless, skip
                result.errors.append(
                    RowError(index, f"conflicting duplicate external_id {sale.external_id!r}")
                )
                continue
            seen[sale.external_id] = row
            result.sales.append(sale)
        return result
