"""edge/events/handover.py — TODO: implement (see docs/architecture.md)."""
"""Handover event generation from tracked object crossings."""

from __future__ import annotations

import re
import uuid

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .zones import ZoneMonitor, create_zone_monitor


def _require_aware(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset.")

    return timestamp.astimezone(timezone.utc)


def _normalize_category(
    class_name: str,
    category_map: Mapping[str, str] | None = None,
) -> str:
    """Map a detector class to the canonical POS category."""

    if category_map:
        mapped = category_map.get(
            class_name,
            category_map.get(class_name.lower()),
        )

        if mapped is not None:
            class_name = str(mapped)

    category = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "_",
        str(class_name).strip().lower(),
    ).strip("_")

    if not category or len(category) > 64:
        raise ValueError(
            f"Invalid event category derived from {class_name!r}."
        )

    return category


@dataclass(frozen=True, slots=True)
class HandoverEvent:
    """An event compliant with contracts/visual_event.v1.schema.json."""

    event_id: str
    site_id: str
    camera_id: str
    timestamp: str
    category: str
    count: int
    confidence: float
    snapshot_ref: str | None
    model_version: str

    schema: str = "visual_event.v1"

    def to_dict(self) -> dict[str, Any]:
        """Return the exact JSON contract payload."""

        return {
            "schema": self.schema,
            "event_id": self.event_id,
            "site_id": self.site_id,
            "camera_id": self.camera_id,
            "timestamp": self.timestamp,
            "category": self.category,
            "count": self.count,
            "confidence": self.confidence,
            "snapshot_ref": self.snapshot_ref,
            "model_version": self.model_version,
        }


class HandoverProcessor:
    """Convert tracked zone crossings into visual events.

    One event is generated per tracked article crossing.
    A detection without a track_id never generates an event.
    """

    def __init__(
        self,
        *,
        site_id: str,
        camera_id: str,
        model_version: str,
        zone_monitor: ZoneMonitor,
        category_map: Mapping[str, str] | None = None,
        snapshot_manager: Any | None = None,
    ) -> None:
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",
            site_id,
        ):
            raise ValueError("Invalid site_id.")

        if not camera_id or len(camera_id) > 64:
            raise ValueError("Invalid camera_id.")

        if not model_version or len(model_version) > 64:
            raise ValueError("Invalid model_version.")

        self.site_id = site_id
        self.camera_id = camera_id
        self.model_version = model_version
        self.zone_monitor = zone_monitor
        self.category_map = dict(category_map or {})
        self.snapshot_manager = snapshot_manager

    def process_frame(
        self,
        detections: Sequence[Any],
        frame: Any,
        timestamp: datetime,
        frame_id: int | None = None,
    ) -> list[HandoverEvent]:
        """Process one frame and return newly created handover events."""

        utc_timestamp = _require_aware(timestamp)

        if frame is None or not hasattr(frame, "shape"):
            raise ValueError("A valid image frame is required.")

        crossings = self.zone_monitor.update(
            detections=detections,
            frame_shape=frame.shape,
            frame_id=frame_id,
        )

        events: list[HandoverEvent] = []

        for crossing in crossings:
            detection = crossing.detection

            confidence = float(
                getattr(detection, "confidence", 0.0)
            )

            if not 0.0 <= confidence <= 1.0:
                raise ValueError("Detection confidence must be in [0, 1].")

            class_name = str(
                getattr(detection, "class_name", "")
            ).strip()

            if not class_name:
                raise ValueError(
                    "Detection must provide a non-empty class_name."
                )

            category = _normalize_category(
                class_name,
                self.category_map,
            )

            event_id = uuid.uuid4()
            snapshot_ref: str | None = None

            if self.snapshot_manager is not None:
                snapshot_ref = self.snapshot_manager.capture(
                    frame,
                    event_id=event_id,
                    site_id=self.site_id,
                    camera_id=self.camera_id,
                    timestamp=utc_timestamp,
                    is_alert=True,
                )

            events.append(
                HandoverEvent(
                    event_id=str(event_id),
                    site_id=self.site_id,
                    camera_id=self.camera_id,
                    timestamp=utc_timestamp.isoformat().replace(
                        "+00:00",
                        "Z",
                    ),
                    category=category,
                    # One event represents one tracked article.
                    count=1,
                    confidence=confidence,
                    snapshot_ref=snapshot_ref,
                    model_version=self.model_version,
                )
            )

        return events

    def reset(self) -> None:
        """Reset zone tracking state."""

        self.zone_monitor.reset()


def create_handover_processor(
    config: Mapping[str, Any],
    snapshot_manager: Any | None = None,
) -> HandoverProcessor:
    """Create a handover processor from edge/config.yaml."""

    camera = config.get("camera", {})
    detector = config.get("detector", {})
    zone_config = config.get("zone", {})

    if not isinstance(camera, Mapping):
        raise ValueError("Invalid camera configuration.")

    if not isinstance(detector, Mapping):
        raise ValueError("Invalid detector configuration.")

    if not isinstance(zone_config, Mapping):
        raise ValueError("Invalid zone configuration.")

    site_id = str(config.get("site_id", "")).strip()

    camera_id = str(
        camera.get("id", camera.get("name", ""))
    ).strip()

    model_version = str(
        config.get(
            "model_version",
            detector.get("model_version", "unversioned"),
        )
    ).strip()

    category_map = config.get("category_map", {})

    if not isinstance(category_map, Mapping):
        raise ValueError("category_map must be a mapping.")

    return HandoverProcessor(
        site_id=site_id,
        camera_id=camera_id,
        model_version=model_version,
        zone_monitor=create_zone_monitor(config),
        category_map=category_map,
        snapshot_manager=snapshot_manager,
    )
