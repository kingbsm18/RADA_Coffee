"""Deterministic fake detector used by the RADA simulator."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from edge.detection.detector import Detection


class FakeDetector:
    """Generate synthetic detections from a scenario frame sequence.

    Bounding boxes in scenario files use normalized xyxy coordinates
    in the [0, 1] range. They are converted to image pixels here.
    """

    def __init__(
        self,
        frames: Sequence[Mapping[str, Any]],
        *,
        default_confidence: float = 0.95,
    ) -> None:
        if not 0.0 <= default_confidence <= 1.0:
            raise ValueError("default_confidence must be between 0 and 1.")

        self.frames = list(frames)
        self.default_confidence = float(default_confidence)

        for frame_index, frame in enumerate(self.frames):
            if not isinstance(frame, Mapping):
                raise ValueError(
                    f"Frame {frame_index} must be a mapping."
                )

            detections = frame.get("detections", [])

            if not isinstance(detections, Sequence) or isinstance(
                detections, (str, bytes)
            ):
                raise ValueError(
                    f"Frame {frame_index}: detections must be a list."
                )

    def detect(
        self,
        frame: Any,
        *,
        frame_index: int,
    ) -> list[Detection]:
        """Return synthetic detections for a given frame index."""

        if frame is None or not hasattr(frame, "shape"):
            raise ValueError("A valid image frame is required.")

        if len(frame.shape) < 2:
            raise ValueError("Invalid frame shape.")

        height = int(frame.shape[0])
        width = int(frame.shape[1])

        if height <= 0 or width <= 0:
            raise ValueError("Frame dimensions must be positive.")

        if frame_index < 0:
            raise ValueError("frame_index cannot be negative.")

        if frame_index >= len(self.frames):
            return []

        frame_config = self.frames[frame_index]
        raw_detections = frame_config.get("detections", [])

        results: list[Detection] = []

        for index, item in enumerate(raw_detections):
            if not isinstance(item, Mapping):
                raise ValueError(
                    f"Frame {frame_index}, detection {index}: "
                    "expected a mapping."
                )

            bbox = item.get("bbox")

            if (
                not isinstance(bbox, Sequence)
                or isinstance(bbox, (str, bytes))
                or len(bbox) != 4
            ):
                raise ValueError(
                    f"Frame {frame_index}, detection {index}: "
                    "bbox must contain [x1, y1, x2, y2]."
                )

            try:
                x1, y1, x2, y2 = map(float, bbox)
            except (TypeError, ValueError) as exc:
                raise ValueError("Bounding box coordinates must be numeric.") from exc

            if not all(0.0 <= value <= 1.0 for value in (x1, y1, x2, y2)):
                raise ValueError(
                    "Fake detector bounding boxes must be normalized to [0, 1]."
                )

            if x2 <= x1 or y2 <= y1:
                raise ValueError("Bounding box must have positive dimensions.")

            confidence = float(
                item.get("confidence", self.default_confidence)
            )

            if not 0.0 <= confidence <= 1.0:
                raise ValueError("Detection confidence must be in [0, 1].")

            class_name = str(item.get("class_name", "")).strip()

            if not class_name:
                raise ValueError("Detection class_name cannot be empty.")

            class_id = item.get("class_id", 0)

            if isinstance(class_id, bool) or not isinstance(class_id, int):
                raise ValueError("Detection class_id must be an integer.")

            results.append(
                Detection(
                    bbox=(
                        x1 * width,
                        y1 * height,
                        x2 * width,
                        y2 * height,
                    ),
                    confidence=confidence,
                    class_id=class_id,
                    class_name=class_name,
                )
            )

        return results

    def reset(self) -> None:
        """Reset hook for compatibility with detector-like components."""

        return None
