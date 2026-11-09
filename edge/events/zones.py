"""Zone geometry and object crossing detection for the edge pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


Point = tuple[float, float]
Direction = str


@dataclass(frozen=True, slots=True)
class Zone:
    """Polygonal zone expressed in normalized or pixel coordinates."""

    polygon: tuple[Point, ...]
    direction: Direction = "in_to_out"
    name: str = "handover"

    def __post_init__(self) -> None:
        if len(self.polygon) < 3:
            raise ValueError("A zone polygon must contain at least 3 points.")

        if self.direction not in {"in_to_out", "out_to_in", "both"}:
            raise ValueError(
                "direction must be in_to_out, out_to_in or both."
            )

        for x, y in self.polygon:
            if x < 0 or y < 0:
                raise ValueError("Polygon coordinates cannot be negative.")

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "Zone":
        """Build a zone from the edge YAML zone section."""

        raw_polygon = config.get("polygon", [])

        if not isinstance(raw_polygon, Sequence) or isinstance(
            raw_polygon, (str, bytes)
        ):
            raise ValueError("zone.polygon must be a sequence of points.")

        points: list[Point] = []

        for point in raw_polygon:
            if not isinstance(point, Sequence) or len(point) != 2:
                raise ValueError(
                    "Each polygon point must contain exactly [x, y]."
                )

            x, y = float(point[0]), float(point[1])

            if x < 0 or y < 0:
                raise ValueError("Polygon coordinates cannot be negative.")

            points.append((x, y))

        return cls(
            polygon=tuple(points),
            direction=str(config.get("direction", "in_to_out")).lower(),
            name=str(config.get("name", "handover")),
        )

    def to_pixel_polygon(
        self,
        frame_width: int,
        frame_height: int,
    ) -> tuple[Point, ...]:
        """Convert normalized coordinates to image pixel coordinates."""

        if frame_width <= 0 or frame_height <= 0:
            raise ValueError("Invalid frame dimensions.")

        normalized = all(
            0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
            for x, y in self.polygon
        )

        if normalized:
            return tuple(
                (
                    x * (frame_width - 1),
                    y * (frame_height - 1),
                )
                for x, y in self.polygon
            )

        if any(
            x > frame_width or y > frame_height
            for x, y in self.polygon
        ):
            raise ValueError(
                "Pixel polygon coordinates exceed the frame dimensions."
            )

        return self.polygon

    def contains(
        self,
        point: Point,
        frame_width: int,
        frame_height: int,
    ) -> bool:
        """Return True when a point is inside or on the polygon boundary."""

        polygon = self.to_pixel_polygon(frame_width, frame_height)
        x, y = point

        inside = False

        for index, (x1, y1) in enumerate(polygon):
            x2, y2 = polygon[(index + 1) % len(polygon)]

            # Treat points on an edge as inside.
            cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)

            if abs(cross) < 1e-8:
                if (
                    min(x1, x2) - 1e-8 <= x <= max(x1, x2) + 1e-8
                    and min(y1, y2) - 1e-8 <= y <= max(y1, y2) + 1e-8
                ):
                    return True

            intersects = (y1 > y) != (y2 > y)

            if intersects:
                intersection_x = (
                    (x2 - x1) * (y - y1) / (y2 - y1) + x1
                )

                if x < intersection_x:
                    inside = not inside

        return inside


@dataclass(frozen=True, slots=True)
class ZoneCrossing:
    """A tracked object crossing a zone boundary."""

    track_id: int
    direction: Direction
    detection: Any
    point: Point


@dataclass(slots=True)
class _TrackZoneState:
    inside: bool
    last_frame: int


class ZoneMonitor:
    """Detect zone entry/exit transitions for tracked objects."""

    def __init__(
        self,
        zone: Zone,
        max_lost: int = 30,
        anchor: str = "bottom_center",
    ) -> None:
        if max_lost < 0:
            raise ValueError("max_lost cannot be negative.")

        if anchor not in {"center", "bottom_center"}:
            raise ValueError("Unsupported detection anchor.")

        self.zone = zone
        self.max_lost = int(max_lost)
        self.anchor = anchor

        self._states: dict[int, _TrackZoneState] = {}
        self._frame_id = -1

    @staticmethod
    def _get_track_id(detection: Any) -> int | None:
        value = getattr(detection, "track_id", None)

        if value is None:
            return None

        return int(value)

    def _anchor_point(self, detection: Any) -> Point:
        bbox = getattr(detection, "bbox", None)

        if bbox is None or len(bbox) != 4:
            raise ValueError("Detection must provide an xyxy bbox.")

        x1, y1, x2, y2 = map(float, bbox)

        if self.anchor == "center":
            return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

        # Bottom-center is generally more stable for objects resting
        # on a counter or moving across a service area.
        return ((x1 + x2) / 2.0, y2)

    def update(
        self,
        detections: Sequence[Any],
        frame_shape: Sequence[int],
        frame_id: int | None = None,
    ) -> list[ZoneCrossing]:
        """Return only confirmed boundary crossings.

        Detections without track_id are ignored to prevent one event
        being generated for every video frame.
        """

        if len(frame_shape) < 2:
            raise ValueError("frame_shape must contain height and width.")

        frame_height = int(frame_shape[0])
        frame_width = int(frame_shape[1])

        if frame_width <= 0 or frame_height <= 0:
            raise ValueError("Invalid frame dimensions.")

        if frame_id is None:
            frame_id = self._frame_id + 1

        if frame_id <= self._frame_id:
            raise ValueError("frame_id must increase monotonically.")

        self._frame_id = frame_id

        # Remove tracks that have disappeared for too many frames.
        for track_id, state in list(self._states.items()):
            if frame_id - state.last_frame > self.max_lost:
                del self._states[track_id]

        crossings: list[ZoneCrossing] = []
        processed_ids: set[int] = set()

        for detection in detections:
            track_id = self._get_track_id(detection)

            if track_id is None or track_id in processed_ids:
                continue

            processed_ids.add(track_id)

            point = self._anchor_point(detection)

            inside = self.zone.contains(
                point,
                frame_width,
                frame_height,
            )

            previous = self._states.get(track_id)

            if previous is None:
                self._states[track_id] = _TrackZoneState(
                    inside=inside,
                    last_frame=frame_id,
                )
                continue

            previous_inside = previous.inside

            previous.inside = inside
            previous.last_frame = frame_id

            if previous_inside == inside:
                continue

            direction = (
                "in_to_out"
                if previous_inside and not inside
                else "out_to_in"
            )

            if self.zone.direction not in {"both", direction}:
                continue

            crossings.append(
                ZoneCrossing(
                    track_id=track_id,
                    direction=direction,
                    detection=detection,
                    point=point,
                )
            )

        return crossings

    def reset(self) -> None:
        """Forget all tracked zone states."""

        self._states.clear()
        self._frame_id = -1

    @property
    def active_tracks(self) -> int:
        return len(self._states)


def create_zone_monitor(
    config: Mapping[str, Any],
) -> ZoneMonitor:
    """Create a zone monitor from the edge configuration."""

    section = config.get("zone", config)

    if not isinstance(section, Mapping):
        raise ValueError("Invalid zone configuration.")

    zone = Zone.from_config(section)

    return ZoneMonitor(
        zone=zone,
        max_lost=int(section.get("max_lost", 30)),
        anchor=str(section.get("anchor", "bottom_center")),
    )
