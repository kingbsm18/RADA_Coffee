"""Lightweight ByteTrack-style object tracker."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .detector import Detection


@dataclass(slots=True)
class _Track:
    track_id: int
    bbox: tuple[float, float, float, float]
    class_id: int
    class_name: str
    confidence: float
    last_frame: int
    hits: int = 1


class ByteTrackLite:
    """
    Two-stage IoU tracker.

    High-confidence detections create tracks.
    Low-confidence detections can maintain existing tracks,
    but cannot create new ones.
    """

    def __init__(
        self,
        track_thresh: float = 0.5,
        low_thresh: float = 0.1,
        new_track_thresh: float = 0.5,
        match_iou: float = 0.3,
        max_lost: int = 30,
    ) -> None:
        for name, value in (
            ("track_thresh", track_thresh),
            ("low_thresh", low_thresh),
            ("new_track_thresh", new_track_thresh),
        ):
            if not 0 <= value <= 1:
                raise ValueError(
                    f"{name} must be between 0 and 1."
                )

        if not 0 < match_iou <= 1:
            raise ValueError("match_iou must be between 0 and 1.")

        if max_lost < 0:
            raise ValueError("max_lost cannot be negative.")

        if low_thresh > track_thresh:
            raise ValueError(
                "low_thresh must be less than or equal to track_thresh."
            )

        self.track_thresh = float(track_thresh)
        self.low_thresh = float(low_thresh)
        self.new_track_thresh = float(new_track_thresh)
        self.match_iou = float(match_iou)
        self.max_lost = int(max_lost)

        self._tracks: dict[int, _Track] = {}
        self._next_id = 1
        self._frame_id = -1

    def update(
        self,
        detections: Sequence[Detection],
        frame_id: int | None = None,
    ) -> list[Detection]:
        """Associate detections with existing object tracks."""

        if frame_id is None:
            frame_id = self._frame_id + 1

        if frame_id <= self._frame_id:
            raise ValueError(
                "frame_id must increase monotonically."
            )

        self._frame_id = frame_id

        detections = list(detections)

        # Remove tracks that have been missing for too long.
        for track_id, track in list(self._tracks.items()):
            if frame_id - track.last_frame > self.max_lost:
                del self._tracks[track_id]

        tracks = list(self._tracks.values())

        high_indices = [
            index
            for index, detection in enumerate(detections)
            if detection.confidence >= self.track_thresh
        ]

        low_indices = [
            index
            for index, detection in enumerate(detections)
            if self.low_thresh
            <= detection.confidence
            < self.track_thresh
        ]

        high_detections = [
            detections[index]
            for index in high_indices
        ]

        low_detections = [
            detections[index]
            for index in low_indices
        ]

        result_by_index: dict[int, Detection] = {}

        # Stage 1: associate existing tracks with high-confidence detections.
        matches, unmatched_tracks, unmatched_high = self._associate(
            tracks,
            high_detections,
            self.match_iou,
        )

        for track_index, detection_index in matches:
            track = tracks[track_index]
            detection = high_detections[detection_index]

            self._update_track(
                track,
                detection,
                frame_id,
            )

            original_index = high_indices[detection_index]

            result_by_index[original_index] = replace(
                detection,
                track_id=track.track_id,
            )

        # Stage 2: use low-confidence detections to recover unmatched tracks.
        remaining_tracks = [
            tracks[index]
            for index in unmatched_tracks
        ]

        low_matches, unmatched_after_low, _ = self._associate(
            remaining_tracks,
            low_detections,
            self.match_iou,
        )

        for track_index, detection_index in low_matches:
            track = remaining_tracks[track_index]
            detection = low_detections[detection_index]

            self._update_track(
                track,
                detection,
                frame_id,
            )

            original_index = low_indices[detection_index]

            result_by_index[original_index] = replace(
                detection,
                track_id=track.track_id,
            )

        # Create tracks only from unmatched high-confidence detections.
        for detection_index in unmatched_high:
            detection = high_detections[detection_index]

            if detection.confidence < self.new_track_thresh:
                continue

            track = _Track(
                track_id=self._next_id,
                bbox=detection.bbox,
                class_id=detection.class_id,
                class_name=detection.class_name,
                confidence=detection.confidence,
                last_frame=frame_id,
            )

            self._tracks[track.track_id] = track

            original_index = high_indices[detection_index]

            result_by_index[original_index] = replace(
                detection,
                track_id=track.track_id,
            )

            self._next_id += 1

        # Keep the original detection order.
        return [
            result_by_index[index]
            for index in range(len(detections))
            if index in result_by_index
        ]

    @staticmethod
    def _update_track(
        track: _Track,
        detection: Detection,
        frame_id: int,
    ) -> None:
        track.bbox = detection.bbox
        track.class_id = detection.class_id
        track.class_name = detection.class_name
        track.confidence = detection.confidence
        track.last_frame = frame_id
        track.hits += 1

    @classmethod
    def _associate(
        cls,
        tracks: Sequence[_Track],
        detections: Sequence[Detection],
        threshold: float,
    ) -> tuple[
        list[tuple[int, int]],
        list[int],
        list[int],
    ]:
        """Greedy IoU association, respecting object classes."""

        candidates: list[
            tuple[float, float, int, int]
        ] = []

        for track_index, track in enumerate(tracks):
            for detection_index, detection in enumerate(detections):
                if track.class_id != detection.class_id:
                    continue

                iou = cls._iou(
                    track.bbox,
                    detection.bbox,
                )

                if iou >= threshold:
                    candidates.append(
                        (
                            iou,
                            detection.confidence,
                            track_index,
                            detection_index,
                        )
                    )

        candidates.sort(
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )

        used_tracks: set[int] = set()
        used_detections: set[int] = set()
        matches: list[tuple[int, int]] = []

        for _, _, track_index, detection_index in candidates:
            if track_index in used_tracks:
                continue

            if detection_index in used_detections:
                continue

            used_tracks.add(track_index)
            used_detections.add(detection_index)

            matches.append(
                (track_index, detection_index)
            )

        unmatched_tracks = [
            index
            for index in range(len(tracks))
            if index not in used_tracks
        ]

        unmatched_detections = [
            index
            for index in range(len(detections))
            if index not in used_detections
        ]

        return (
            matches,
            unmatched_tracks,
            unmatched_detections,
        )

    @staticmethod
    def _iou(
        box_a: tuple[float, float, float, float],
        box_b: tuple[float, float, float, float],
    ) -> float:
        """Calculate intersection over union for two xyxy boxes."""

        ax1, ay1, ax2, ay2 = box_a
        bx1, by1, bx2, by2 = box_b

        x1 = max(ax1, bx1)
        y1 = max(ay1, by1)
        x2 = min(ax2, bx2)
        y2 = min(ay2, by2)

        intersection = (
            max(0.0, x2 - x1)
            * max(0.0, y2 - y1)
        )

        area_a = (
            max(0.0, ax2 - ax1)
            * max(0.0, ay2 - ay1)
        )

        area_b = (
            max(0.0, bx2 - bx1)
            * max(0.0, by2 - by1)
        )

        union = area_a + area_b - intersection

        if union <= 0:
            return 0.0

        return intersection / union

    def reset(self) -> None:
        """Reset all active tracks and restart frame numbering."""

        self._tracks.clear()
        self._next_id = 1
        self._frame_id = -1

    @property
    def active_tracks(self) -> int:
        return len(self._tracks)


def create_tracker(
    config: Mapping[str, Any],
) -> ByteTrackLite | None:
    """Create a tracker from the edge configuration."""

    section = config.get("tracker", config)

    if not isinstance(section, Mapping):
        raise ValueError("Invalid tracker configuration.")

    tracker_type = str(
        section.get("type", "bytetrack")
    ).lower()

    if tracker_type in {"none", "off", "disabled"}:
        return None

    if tracker_type not in {
        "bytetrack",
        "bytetrack_lite",
        "iou",
    }:
        raise ValueError(
            f"Unsupported tracker type: {tracker_type}"
        )

    return ByteTrackLite(
        track_thresh=float(
            section.get("track_thresh", 0.5)
        ),
        low_thresh=float(
            section.get("low_thresh", 0.1)
        ),
        new_track_thresh=float(
            section.get("new_track_thresh", 0.5)
        ),
        match_iou=float(
            section.get("match_iou", 0.3)
        ),
        max_lost=int(
            section.get("max_lost", 30)
        ),
    )
