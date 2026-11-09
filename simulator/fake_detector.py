"""Build visual events and the matching POS sales for a scenario (no camera needed)."""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

CSV_COLUMNS = (
    "external_id", "timestamp", "product_name", "pos_category", "quantity", "unit_price", "status",
)
_NAMESPACE = uuid.UUID("5f2f6f3e-9b7d-4a41-8d3e-0f3c1c1d7a11")


@dataclass(frozen=True)
class Built:
    events: list[dict[str, Any]]  # valid visual_event.v1 payloads
    sales: list[dict[str, str]]  # rows with the CSV_COLUMNS keys
    expectations: dict[str, str]  # event_id -> final state


def load(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def build(config: dict[str, Any], name: str, *, start: datetime, run_id: str = "") -> Built:
    """Deterministic: same scenario, start and run_id give the same ids and rows."""
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    defaults, categories = config["defaults"], config["categories"]
    events: list[dict[str, Any]] = []
    sales: list[dict[str, str]] = []
    expectations: dict[str, str] = {}

    for index, item in enumerate(config["scenarios"][name]["items"]):
        when = (start + timedelta(minutes=item["at"])).astimezone(timezone.utc)
        event_id = str(uuid.uuid5(_NAMESPACE, f"{name}:{index}:{run_id}"))
        events.append(
            {
                "schema": "visual_event.v1",
                "event_id": event_id,
                "site_id": defaults["site_id"],
                "camera_id": defaults["camera_id"],
                "timestamp": when.isoformat(),
                "category": item["category"],
                "count": item["count"],
                "confidence": item["confidence"],
                "snapshot_ref": None,
                "model_version": defaults["model_version"],
            }
        )
        expectations[event_id] = item["expect"]

        sale = item.get("sale")
        if sale is not None:
            product = categories[item["category"]]
            sale_time = when + timedelta(minutes=sale.get("offset", 0))
            sales.append(
                {
                    "external_id": f"SIM-{name}-{index}-{run_id}".rstrip("-"),
                    "timestamp": sale_time.isoformat(),
                    "product_name": product["product_name"],
                    "pos_category": product["pos_category"],
                    "quantity": str(sale.get("quantity", item["count"])),
                    "unit_price": str(sale.get("price", product["unit_price"])),
                    "status": sale.get("status", "paid"),
                }
            )
    return Built(events, sales, expectations)


def sales_csv(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()
