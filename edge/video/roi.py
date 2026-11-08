"""edge/video/roi.py — TODO: implement (see docs/architecture.md)."""

"""Region-of-interest geometry and image operations for RADA Edge.

ROI polygons may use:
- Normalized coordinates in [0, 1].
- Absolute pixel coordinates.

The polygon is converted to pixel coordinates using the actual frame size.
"""

from __future__ import annotations

import math

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import cv2
import numpy as np


Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class RegionOfInterest:
    """A polygonal region of interest."""

    polygon: tuple[Point, ...]
    name: str = "service_area"

    def __post_init__(self) -> None:
        if len(self.polygon) < 3:
            raise ValueError(
                "An ROI polygon must contain at least 3 points."
            )

        for point in self.polygon:
            if len(point) != 2:
                raise ValueError(
                    "Each ROI point must contain exactly two coordinates."
                )

            x, y = point

            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError(
                    "ROI coordinates must be finite numbers."
                )

            if x < 0 or y < 0:
                raise ValueError(
                    "ROI coordinates cannot be negative."
                )

        if not self.name.strip():
            raise ValueError("ROI name cannot be empty.")

    @property
    def is_normalized(self) -> bool:
        """Return True if all coordinates are within [0, 1]."""

        return all(
            0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
            for x, y in self.polygon
        )

    def to_pixels(
        self,
        frame_width: int,
        frame_height: int,
    ) -> np.ndarray:
        """Convert the polygon to an OpenCV int32 polygon."""

        if frame_width <= 0 or frame_height <= 0:
            raise ValueError("Frame dimensions must be positive.")

        if self.is_normalized:
            points = [
                (
                    round(x * (frame_width - 1)),
                    round(y * (frame_height - 1)),
                )
                for x, y in self.polygon
            ]
        else:
            if any(
                x > frame_width - 1 or y > frame_height - 1
                for x, y in self.polygon
            ):
                raise ValueError(
                    "ROI pixel coordinates exceed frame dimensions."
                )

            points = [
                (round(x), round(y))
                for x, y in self.polygon
            ]

        return np.asarray(points, dtype=np.int32).reshape((-1, 1, 2))

    def mask(
        self,
        frame_shape: Sequence[int],
    ) -> np.ndarray:
        """Create a single-channel uint8 mask for this ROI."""

        if len(frame_shape) < 2:
            raise ValueError(
                "frame_shape must contain height and width."
            )

        height = int(frame_shape[0])
        width = int(frame_shape[1])

        polygon = self.to_pixels(width, height)

        result = np.zeros((height, width), dtype=np.uint8)

        cv2.fillPoly(
            result,
            [polygon],
            color=255,
        )

        return result

    def contains(
        self,
        point: Point,
        frame_width: int,
        frame_height: int,
    ) -> bool:
        """Check whether a pixel-coordinate point is inside the ROI."""

        x, y = map(float, point)

        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("Point coordinates must be finite.")

        if not (
            0 <= x < frame_width
            and 0 <= y < frame_height
        ):
            return False

        polygon = self.to_pixels(
            frame_width,
            frame_height,
        )

        result = cv2.pointPolygonTest(
            polygon,
            (x, y),
            False,
        )

        # Boundary points are considered inside.
        return result >= 0

    def bounding_box(
        self,
        frame_width: int,
        frame_height: int,
    ) -> tuple[int, int, int, int]:
        """Return the clipped (x1, y1, x2, y2) ROI bounding box."""

        polygon = self.to_pixels(
            frame_width,
            frame_height,
        )

        x, y, width, height = cv2.boundingRect(polygon)

        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(frame_width, x + width)
        y2 = min(frame_height, y + height)

        if x2 <= x1 or y2 <= y1:
            raise ValueError("ROI has an empty bounding box.")

        return x1, y1, x2, y2


def create_roi(
    config: Mapping[str, object],
) -> RegionOfInterest:
    """Create an ROI from the RADA Edge configuration.

    Supports either an 'roi' section or the existing 'zone' section.
    """

    section = config.get(
        "roi",
        config.get("zone", config),
    )

    if not isinstance(section, Mapping):
        raise ValueError("Invalid ROI configuration.")

    raw_polygon = section.get("polygon")

    if (
        not isinstance(raw_polygon, Sequence)
        or isinstance(raw_polygon, (str, bytes))
    ):
        raise ValueError("roi.polygon must be a sequence of points.")

    points: list[Point] = []

    for point in raw_polygon:
        if (
            not isinstance(point, Sequence)
            or isinstance(point, (str, bytes))
            or len(point) != 2
        ):
            raise ValueError(
                "Each ROI point must contain exactly [x, y]."
            )

        try:
            x = float(point[0])
            y = float(point[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "ROI coordinates must be numeric."
            ) from exc

        points.append((x, y))

    return RegionOfInterest(
        polygon=tuple(points),
        name=str(section.get("name", "service_area")),
    )


def point_in_roi(
    point: Point,
    roi: RegionOfInterest,
    frame_width: int,
    frame_height: int,
) -> bool:
    """Convenience function for checking a point against an ROI."""

    return roi.contains(
        point,
        frame_width,
        frame_height,
    )


def apply_roi(
    frame: np.ndarray,
    roi: RegionOfInterest,
    *,
    outside_value: int = 0,
) -> np.ndarray:
    """Return a copy of the frame with pixels outside the ROI masked.

    The input frame is never modified.
    """

    if not isinstance(frame, np.ndarray):
        raise TypeError("frame must be a NumPy array.")

    if frame.size == 0 or frame.ndim not in {2, 3}:
        raise ValueError("frame must be a non-empty image.")

    if isinstance(outside_value, bool) or not isinstance(
        outside_value, int
    ):
        raise TypeError("outside_value must be an integer.")

    if not 0 <= outside_value <= 255:
        raise ValueError("outside_value must be between 0 and 255.")

    height, width = frame.shape[:2]
    mask = roi.mask((height, width))

    result = frame.copy()

    if result.ndim == 2:
        result[mask == 0] = outside_value
    else:
        result[mask == 0, :] = outside_value

    return result


def crop_roi(
    frame: np.ndarray,
    roi: RegionOfInterest,
    *,
    mask_outside: bool = True,
) -> np.ndarray:
    """Crop the ROI bounding rectangle from a frame.

    When mask_outside is True, pixels outside the polygon but inside
    its bounding rectangle are set to zero.
    """

    if not isinstance(frame, np.ndarray):
        raise TypeError("frame must be a NumPy array.")

    if frame.size == 0 or frame.ndim not in {2, 3}:
        raise ValueError("frame must be a non-empty image.")

    height, width = frame.shape[:2]

    x1, y1, x2, y2 = roi.bounding_box(
        width,
        height,
    )

    cropped = frame[y1:y2, x1:x2].copy()

    if not mask_outside:
        return cropped

    full_mask = roi.mask((height, width))
    cropped_mask = full_mask[y1:y2, x1:x2]

    if cropped.ndim == 2:
        cropped[cropped_mask == 0] = 0
    else:
        cropped[cropped_mask == 0, :] = 0

    return cropped
