"""Video source management for RADA Edge.

Supports:
- RTSP/IP camera streams.
- Local video files.
- OpenCV-compatible camera indices.

The video stream is processed locally on the Edge machine.
It must never be forwarded to the backend.
"""

from __future__ import annotations

import logging
import os

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import cv2


LOGGER = logging.getLogger("rada.edge.video")


class CaptureError(RuntimeError):
    """Raised when a video source cannot be opened or read."""


class FrameCapture:
    """Small, predictable wrapper around cv2.VideoCapture."""

    def __init__(
        self,
        source: str | int,
        *,
        buffer_size: int = 1,
        open_timeout_ms: int = 10_000,
        read_timeout_ms: int = 10_000,
    ) -> None:
        if buffer_size < 1:
            raise ValueError("buffer_size must be at least 1.")

        if open_timeout_ms <= 0 or read_timeout_ms <= 0:
            raise ValueError("Capture timeouts must be positive.")

        self.source = source
        self._capture: cv2.VideoCapture | None = None

        self._open(
            buffer_size=buffer_size,
            open_timeout_ms=open_timeout_ms,
            read_timeout_ms=read_timeout_ms,
        )

    def _open(
        self,
        *,
        buffer_size: int,
        open_timeout_ms: int,
        read_timeout_ms: int,
    ) -> None:
        """Open the source and configure low-latency capture."""

        params: list[int] = []

        # These properties are supported by recent OpenCV versions.
        if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
            params.extend(
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, open_timeout_ms]
            )

        if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
            params.extend(
                [cv2.CAP_PROP_READ_TIMEOUT_MSEC, read_timeout_ms]
            )

        try:
            if params:
                capture = cv2.VideoCapture(
                    self.source,
                    cv2.CAP_ANY,
                    params,
                )
            else:
                capture = cv2.VideoCapture(self.source)

        except (cv2.error, TypeError) as exc:
            raise CaptureError(
                "OpenCV could not initialize the video source."
            ) from exc

        if not capture.isOpened():
            capture.release()
            raise CaptureError(
                "Could not open the configured video source."
            )

        capture.set(cv2.CAP_PROP_BUFFERSIZE, buffer_size)
        self._capture = capture

        LOGGER.info("Video source opened successfully.")

    def isOpened(self) -> bool:
        """Return whether the underlying source is still open."""

        return (
            self._capture is not None
            and self._capture.isOpened()
        )

    def read(self) -> tuple[bool, Any | None]:
        """Read the next BGR frame."""

        if not self.isOpened():
            return False, None

        try:
            success, frame = self._capture.read()
        except cv2.error as exc:
            LOGGER.warning("Video frame read failed: %s", exc)
            return False, None

        if not success or frame is None:
            return False, None

        if (
            not hasattr(frame, "ndim")
            or frame.ndim != 3
            or frame.shape[2] != 3
            or frame.size == 0
        ):
            LOGGER.warning("Received an invalid video frame.")
            return False, None

        return True, frame

    def get(self, property_id: int) -> float:
        """Read a property from the underlying OpenCV capture."""

        if not self.isOpened():
            return 0.0

        return float(self._capture.get(property_id))

    def set(self, property_id: int, value: float) -> bool:
        """Set an OpenCV capture property."""

        if not self.isOpened():
            return False

        return bool(self._capture.set(property_id, value))

    def release(self) -> None:
        """Release the camera or video file."""

        if self._capture is not None:
            self._capture.release()
            self._capture = None

        LOGGER.info("Video source released.")

    def __enter__(self) -> "FrameCapture":
        if not self.isOpened():
            raise CaptureError("Video source is not open.")
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release()


def open_capture(
    source: str | int,
    *,
    buffer_size: int = 1,
    open_timeout_ms: int = 10_000,
    read_timeout_ms: int = 10_000,
) -> FrameCapture:
    """Open an RTSP stream, local video file or camera index."""

    return FrameCapture(
        source,
        buffer_size=buffer_size,
        open_timeout_ms=open_timeout_ms,
        read_timeout_ms=read_timeout_ms,
    )


def create_capture(config: Mapping[str, Any]) -> FrameCapture:
    """Create a video capture from the RADA Edge configuration.

    Expected configuration:

    camera:
      source_type: rtsp
      rtsp_uri_env: RTSP_URI

    Or:

    camera:
      source_type: video_file
      video_path: ./videos/test.mp4

    Or:

    camera:
      source_type: camera_index
      index: 0
    """

    camera = config.get("camera", config)

    if not isinstance(camera, Mapping):
        raise ValueError("Invalid camera configuration.")

    source_type = str(
        camera.get("source_type", "rtsp")
    ).strip().lower()

    buffer_size = int(camera.get("buffer_size", 1))
    open_timeout_ms = int(
        camera.get("open_timeout_ms", 10_000)
    )
    read_timeout_ms = int(
        camera.get("read_timeout_ms", 10_000)
    )

    if source_type == "rtsp":
        env_name = str(
            camera.get("rtsp_uri_env", "RTSP_URI")
        ).strip()

        if not env_name:
            raise ValueError("camera.rtsp_uri_env cannot be empty.")

        source = os.getenv(env_name, "").strip()

        if not source:
            raise CaptureError(
                f"RTSP source is missing. Set environment variable {env_name}."
            )

        if not source.lower().startswith("rtsp://"):
            raise ValueError(
                "The configured RTSP source must start with rtsp://."
            )

    elif source_type == "video_file":
        raw_path = camera.get("video_path")

        if not raw_path:
            raise ValueError("camera.video_path is required.")

        path = Path(str(raw_path)).expanduser().resolve()

        if not path.is_file():
            raise CaptureError(
                "Configured video file does not exist."
            )

        source = str(path)

    elif source_type == "camera_index":
        index = camera.get("index", 0)

        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("camera.index must be an integer.")

        if index < 0:
            raise ValueError("camera.index cannot be negative.")

        source = index

    else:
        raise ValueError(
            "Unsupported camera.source_type. "
            "Expected rtsp, video_file or camera_index."
        )

    return open_capture(
        source,
        buffer_size=buffer_size,
        open_timeout_ms=open_timeout_ms,
        read_timeout_ms=read_timeout_ms,
    )
