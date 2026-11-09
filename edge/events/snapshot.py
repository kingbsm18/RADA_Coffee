"""Local JPEG snapshot storage for edge events."""

from __future__ import annotations

import os
import re
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np


VALID_MODES = {"always", "on_alert", "never"}


def _safe_component(value: str, field_name: str) -> str:
    """Validate a path component and prevent directory traversal."""

    value = str(value).strip()

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError(f"Invalid {field_name}.")

    return value


def _require_aware(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset.")

    return timestamp.astimezone(timezone.utc)


class SnapshotManager:
    """Save event snapshots locally and return opaque relative references."""

    def __init__(
        self,
        root: str | Path = "./data",
        mode: str | None = None,
        jpeg_quality: int = 85,
    ) -> None:
        selected_mode = (
            mode or os.getenv("SNAPSHOT_UPLOAD", "on_alert")
        ).strip().lower()

        if selected_mode not in VALID_MODES:
            raise ValueError(
                "SNAPSHOT_UPLOAD must be always, on_alert or never."
            )

        if not 1 <= jpeg_quality <= 100:
            raise ValueError("jpeg_quality must be between 1 and 100.")

        self.root = Path(root).expanduser().resolve()
        self.mode = selected_mode
        self.jpeg_quality = int(jpeg_quality)

    def capture(
        self,
        frame: np.ndarray,
        *,
        event_id: str | uuid.UUID,
        site_id: str,
        camera_id: str,
        timestamp: datetime,
        is_alert: bool = True,
    ) -> str | None:
        """Save one BGR frame as JPEG and return its relative reference."""

        if self.mode == "never":
            return None

        if self.mode == "on_alert" and not is_alert:
            return None

        if not isinstance(frame, np.ndarray):
            raise TypeError("frame must be a NumPy array.")

        if frame.ndim != 3 or frame.shape[2] != 3 or frame.size == 0:
            raise ValueError("Expected a non-empty BGR image.")

        event_uuid = uuid.UUID(str(event_id))
        site = _safe_component(site_id, "site_id")
        camera = _safe_component(camera_id, "camera_id")
        utc_timestamp = _require_aware(timestamp)

        year = utc_timestamp.strftime("%Y")
        month = utc_timestamp.strftime("%m")
        day = utc_timestamp.strftime("%d")

        relative_path = Path(
            "snapshots",
            site,
            camera,
            year,
            month,
            day,
            f"{event_uuid}.jpg",
        )

        destination = (self.root / relative_path).resolve()

        # Ensure the destination remains inside the configured root.
        if not destination.is_relative_to(self.root):
            raise ValueError("Snapshot path escapes the storage root.")

        destination.parent.mkdir(parents=True, exist_ok=True)

        success, encoded = cv2.imencode(
            ".jpg",
            frame,
            [
                cv2.IMWRITE_JPEG_QUALITY,
                self.jpeg_quality,
            ],
        )

        if not success:
            raise RuntimeError("OpenCV could not encode the snapshot.")

        temporary_path = destination.with_name(
            f".{destination.stem}.{uuid.uuid4().hex}.tmp"
        )

        try:
            with temporary_path.open("wb") as file:
                file.write(encoded.tobytes())
                file.flush()
                os.fsync(file.fileno())

            os.replace(temporary_path, destination)

        finally:
            if temporary_path.exists():
                temporary_path.unlink()

        reference = relative_path.as_posix()

        if len(reference) > 255:
            destination.unlink(missing_ok=True)
            raise ValueError("snapshot_ref exceeds 255 characters.")

        return reference

    def resolve(self, snapshot_ref: str) -> Path:
        """Resolve a stored reference without allowing path traversal."""

        if not snapshot_ref or "\\" in snapshot_ref:
            raise ValueError("Invalid snapshot reference.")

        relative = Path(snapshot_ref)

        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid snapshot reference.")

        resolved = (self.root / relative).resolve()

        if not resolved.is_relative_to(self.root):
            raise ValueError("Snapshot reference escapes storage root.")

        return resolved

    def read(self, snapshot_ref: str) -> bytes:
        """Read a previously stored snapshot."""

        path = self.resolve(snapshot_ref)

        if not path.is_file():
            raise FileNotFoundError(snapshot_ref)

        return path.read_bytes()

    def exists(self, snapshot_ref: str) -> bool:
        """Check whether a snapshot reference exists."""

        return self.resolve(snapshot_ref).is_file()


def create_snapshot_manager(
    config: dict[str, Any],
) -> SnapshotManager:
    """Create snapshot storage from the edge configuration."""

    section = config.get("snapshot", {})

    if not isinstance(section, dict):
        raise ValueError("Invalid snapshot configuration.")

    return SnapshotManager(
        root=section.get("root", "./data"),
        mode=section.get("mode"),
        jpeg_quality=int(section.get("jpeg_quality", 85)),
    )
