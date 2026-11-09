"""Replay synthetic café scenarios through the real RADA Edge pipeline."""

from __future__ import annotations

import argparse
import json
import logging

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from edge.detection.tracker import ByteTrackLite
from edge.events.handover import (
    HandoverProcessor,
    create_handover_processor,
)

from simulator.fake_detector import FakeDetector


LOGGER = logging.getLogger("rada.simulator")


class ReplayError(RuntimeError):
    """Raised when a simulator scenario cannot be replayed."""


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Outputs produced by one scenario replay."""

    scenario: str
    site_id: str
    frames_processed: int
    visual_events: tuple[dict[str, Any], ...]
    pos_sales: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "site_id": self.site_id,
            "frames_processed": self.frames_processed,
            "visual_events": list(self.visual_events),
            "pos_sales": list(self.pos_sales),
        }


def _parse_timestamp(value: Any) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC."""

    if not isinstance(value, str) or not value.strip():
        raise ReplayError("scenario.start_at must be an ISO-8601 string.")

    try:
        timestamp = datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ReplayError("Invalid scenario.start_at timestamp.") from exc

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ReplayError("scenario.start_at must include a UTC offset.")

    return timestamp.astimezone(timezone.utc)


def load_scenarios(path: str | Path) -> dict[str, Any]:
    """Load and validate the YAML scenario collection."""

    scenario_path = Path(path)

    if not scenario_path.is_file():
        raise ReplayError(
            f"Scenario file not found: {scenario_path}"
        )

    try:
        with scenario_path.open("r", encoding="utf-8") as file:
            document = yaml.safe_load(file)
    except yaml.YAMLError as exc:
        raise ReplayError("Invalid scenarios YAML file.") from exc

    if not isinstance(document, Mapping):
        raise ReplayError("Scenario document must be a YAML mapping.")

    scenarios = document.get("scenarios")

    if not isinstance(scenarios, Mapping) or not scenarios:
        raise ReplayError("No scenarios defined in the YAML file.")

    return dict(scenarios)


def _validate_pos_sales(
    raw_sales: Any,
    site_id: str,
) -> tuple[dict[str, Any], ...]:
    """Validate the basic shape of POS fixture records."""

    if raw_sales is None:
        return ()

    if not isinstance(raw_sales, list):
        raise ReplayError("pos_sales must be a list.")

    results: list[dict[str, Any]] = []

    allowed_statuses = {"paid", "voided", "refunded"}

    for index, sale in enumerate(raw_sales):
        if not isinstance(sale, Mapping):
            raise ReplayError(f"POS sale {index} must be a mapping.")

        required = {
            "external_id",
            "timestamp",
            "product_name",
            "pos_category",
            "quantity",
            "unit_price",
            "status",
        }

        missing = required.difference(sale)

        if missing:
            raise ReplayError(
                f"POS sale {index} is missing: {', '.join(sorted(missing))}."
            )

        quantity = sale["quantity"]

        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or not 1 <= quantity <= 100
        ):
            raise ReplayError(
                f"POS sale {index}: quantity must be between 1 and 100."
            )

        status = str(sale["status"])

        if status not in allowed_statuses:
            raise ReplayError(
                f"POS sale {index}: unsupported status {status!r}."
            )

        unit_price = str(sale["unit_price"])

        # Keep prices as decimal strings; never convert to float.
        import re

        if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", unit_price):
            raise ReplayError(
                f"POS sale {index}: unit_price must be a decimal string."
            )

        timestamp = _parse_timestamp(sale["timestamp"])

        external_id = str(sale["external_id"]).strip()
        product_name = str(sale["product_name"]).strip()

        if not external_id or len(external_id) > 128:
            raise ReplayError(f"POS sale {index}: invalid external_id.")

        if not product_name or len(product_name) > 200:
            raise ReplayError(f"POS sale {index}: invalid product_name.")

        category = sale["pos_category"]

        if category is not None:
            category = str(category)

            if len(category) > 200:
                raise ReplayError(f"POS sale {index}: pos_category is too long.")

        results.append(
            {
                "site_id": site_id,
                "external_id": external_id,
                "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                "product_name": product_name,
                "pos_category": category,
                "quantity": quantity,
                "unit_price": unit_price,
                "status": status,
            }
        )

    return tuple(results)


def replay_scenario(
    scenario_name: str,
    *,
    scenarios_path: str | Path = "simulator/scenarios.yaml",
) -> ReplayResult:
    """Replay one named scenario using the real tracker and event processor."""

    scenarios = load_scenarios(scenarios_path)

    if scenario_name not in scenarios:
        available = ", ".join(sorted(scenarios))
        raise ReplayError(
            f"Unknown scenario {scenario_name!r}. Available: {available}"
        )

    scenario = scenarios[scenario_name]

    if not isinstance(scenario, Mapping):
        raise ReplayError("Scenario definition must be a YAML mapping.")

    site_id = str(scenario.get("site_id", "")).strip()

    if not site_id:
        raise ReplayError("Scenario site_id is required.")

    camera = scenario.get("camera", {})
    zone = scenario.get("zone", {})
    frames = scenario.get("frames", [])

    if not isinstance(camera, Mapping):
        raise ReplayError("Scenario camera must be a mapping.")

    if not isinstance(zone, Mapping):
        raise ReplayError("Scenario zone must be a mapping.")

    if not isinstance(frames, list) or not frames:
        raise ReplayError("Scenario must contain at least one frame.")

    camera_id = str(camera.get("id", "sim-camera")).strip()
    model_version = str(
        scenario.get("model_version", "simulator-1.0")
    ).strip()

    if not camera_id or len(camera_id) > 64:
        raise ReplayError("Invalid scenario camera id.")

    if not model_version or len(model_version) > 64:
        raise ReplayError("Invalid scenario model_version.")

    width = int(scenario.get("frame_width", 1280))
    height = int(scenario.get("frame_height", 720))
    fps = float(scenario.get("fps", 5))

    if width <= 0 or height <= 0:
        raise ReplayError("Frame dimensions must be positive.")

    if fps <= 0:
        raise ReplayError("Scenario fps must be positive.")

    start_at = _parse_timestamp(
        scenario.get("start_at", "2026-01-01T12:00:00Z")
    )

    edge_config = {
        "site_id": site_id,
        "camera": {"id": camera_id},
        "detector": {"model_version": model_version},
        "zone": dict(zone),
    }

    try:
        fake_detector = FakeDetector(frames)
        tracker = ByteTrackLite()
        processor: HandoverProcessor = create_handover_processor(
            edge_config
        )
    except (TypeError, ValueError) as exc:
        raise ReplayError(
            f"Invalid scenario configuration: {exc}"
        ) from exc

    visual_events: list[dict[str, Any]] = []
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    try:
        for frame_index in range(len(frames)):
            detections = fake_detector.detect(
                frame,
                frame_index=frame_index,
            )

            tracked = tracker.update(
                detections,
                frame_id=frame_index,
            )

            timestamp = start_at + timedelta(
                seconds=frame_index / fps
            )

            events = processor.process_frame(
                detections=tracked,
                frame=frame,
                timestamp=timestamp,
                frame_id=frame_index,
            )

            visual_events.extend(
                event.to_dict()
                for event in events
            )

    finally:
        tracker.reset()
        processor.reset()

    pos_sales = _validate_pos_sales(
        scenario.get("pos_sales", []),
        site_id,
    )

    LOGGER.info(
        "Replay completed | scenario=%s | frames=%d | visual_events=%d | pos_sales=%d",
        scenario_name,
        len(frames),
        len(visual_events),
        len(pos_sales),
    )

    return ReplayResult(
        scenario=scenario_name,
        site_id=site_id,
        frames_processed=len(frames),
        visual_events=tuple(visual_events),
        pos_sales=pos_sales,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay RADA AI café simulation scenarios."
    )

    parser.add_argument(
        "--scenario",
        required=True,
        help="Scenario name defined in scenarios.yaml.",
    )

    parser.add_argument(
        "--scenarios",
        default="simulator/scenarios.yaml",
        help="Path to the scenarios YAML file.",
    )

    parser.add_argument(
        "--output",
        default="-",
        help="Output JSON path, or '-' for stdout.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        result = replay_scenario(
            args.scenario,
            scenarios_path=args.scenarios,
        )

        output = json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            indent=2,
        )

        if args.output == "-":
            print(output)
        else:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output + "\n", encoding="utf-8")
            LOGGER.info("Replay output saved to %s", output_path)

        return 0

    except ReplayError as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
