"""edge/main.py — TODO: implement (see docs/architecture.md)."""
"""RADA AI Edge runtime entry point.

Run from the repository root:
    python -m edge.main --config edge/config.yaml
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import cv2
import yaml

from edge.detection import create_detector, create_tracker
from edge.events.handover import create_handover_processor
from edge.events.snapshot import create_snapshot_manager
from edge.ops.health import create_health_reporter
from edge.transport import create_outbox, create_sender


LOGGER = logging.getLogger("rada.edge")


class EdgeRuntimeError(RuntimeError):
    """Raised when the edge runtime cannot start or continue."""


def configure_logging(config: Mapping[str, Any]) -> None:
    """Configure structured-enough console logging."""

    section = config.get("logging", {})
    if not isinstance(section, Mapping):
        section = {}

    level_name = str(section.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


def load_config(config_path: str | Path) -> tuple[dict[str, Any], Path]:
    """Load YAML configuration and return it with its directory."""

    path = Path(config_path).expanduser().resolve()

    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
    except yaml.YAMLError as exc:
        raise EdgeRuntimeError(f"Invalid YAML configuration: {exc}") from exc

    if not isinstance(config, dict):
        raise EdgeRuntimeError("The edge configuration must be a YAML mapping.")

    return config, path.parent


def _resolve_config_path(
    section: dict[str, Any],
    key: str,
    config_dir: Path,
) -> None:
    """Resolve a relative path against the configuration directory."""

    value = section.get(key)

    if value is None or not str(value).strip():
        return

    path = Path(str(value)).expanduser()

    if not path.is_absolute():
        path = config_dir / path

    section[key] = str(path.resolve())


def normalize_config_paths(
    config: dict[str, Any],
    config_dir: Path,
) -> None:
    """Make configured filesystem paths independent of the working directory."""

    detector = config.setdefault("detector", {})
    transport = config.setdefault("transport", {})
    snapshot = config.setdefault("snapshot", {})
    health = config.setdefault("health", {})

    for name, section in (
        ("detector", detector),
        ("transport", transport),
        ("snapshot", snapshot),
        ("health", health),
    ):
        if not isinstance(section, dict):
            raise EdgeRuntimeError(f"Invalid {name} configuration.")

    _resolve_config_path(detector, "model_path", config_dir)
    _resolve_config_path(detector, "engine_cache_dir", config_dir)
    _resolve_config_path(transport, "outbox_path", config_dir)
    _resolve_config_path(snapshot, "root", config_dir)
    _resolve_config_path(health, "storage_path", config_dir)


def validate_config(config: Mapping[str, Any]) -> None:
    """Validate essential runtime configuration before initializing hardware."""

    site_id = config.get("site_id")

    if not isinstance(site_id, str) or not site_id.strip():
        raise EdgeRuntimeError("site_id is required.")

    camera = config.get("camera")
    detector = config.get("detector")
    zone = config.get("zone")
    tracker = config.get("tracker")
    transport = config.get("transport")

    for name, section in (
        ("camera", camera),
        ("detector", detector),
        ("zone", zone),
        ("tracker", tracker),
        ("transport", transport),
    ):
        if not isinstance(section, Mapping):
            raise EdgeRuntimeError(f"Missing or invalid '{name}' configuration.")

    camera_env = str(
        camera.get("rtsp_uri_env", "RTSP_URI")
    ).strip()

    if not camera_env:
        raise EdgeRuntimeError("camera.rtsp_uri_env cannot be empty.")

    if not os.getenv(camera_env, "").strip():
        raise EdgeRuntimeError(
            f"Camera source is missing. Set the {camera_env} environment variable."
        )

    if not str(detector.get("model_path", "")).strip():
        raise EdgeRuntimeError("detector.model_path is required.")

    if not str(transport.get("backend_url", "")).strip():
        raise EdgeRuntimeError("transport.backend_url is required.")

    fps_sample = float(camera.get("fps_sample", 5))

    if fps_sample <= 0:
        raise EdgeRuntimeError("camera.fps_sample must be greater than zero.")

    polygon = zone.get("polygon")

    if not isinstance(polygon, list) or len(polygon) < 3:
        raise EdgeRuntimeError(
            "zone.polygon must contain at least 3 points. "
            "Configure the service zone before starting the runtime."
        )

    tracker_type = str(tracker.get("type", "bytetrack")).lower()

    if tracker_type in {"none", "off", "disabled"}:
        raise EdgeRuntimeError(
            "Tracking cannot be disabled: zone crossing detection requires track IDs."
        )


def open_camera(source: str) -> cv2.VideoCapture:
    """Open an RTSP or other OpenCV-compatible camera source."""

    capture = cv2.VideoCapture(source)

    if not capture.isOpened():
        capture.release()
        raise EdgeRuntimeError("Could not open the configured camera stream.")

    # Reduce latency by avoiding a large queue of old frames.
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    return capture


def build_runtime(config: dict[str, Any]) -> dict[str, Any]:
    """Initialize the detector, tracker, event processor and transport."""

    detector = create_detector(config)
    tracker = None
    outbox = None
    sender = None

    try:
        tracker = create_tracker(config)

        if tracker is None:
            raise EdgeRuntimeError(
                "A tracker is required for zone-based event generation."
            )

        snapshot_manager = create_snapshot_manager(config)

        processor = create_handover_processor(
            config,
            snapshot_manager=snapshot_manager,
        )

        outbox = create_outbox(config)
        sender = create_sender(config, outbox)

        health_reporter = create_health_reporter(config)

        return {
            "detector": detector,
            "tracker": tracker,
            "processor": processor,
            "outbox": outbox,
            "sender": sender,
            "health": health_reporter,
        }

    except Exception:
        if sender is not None:
            sender.close()

        if outbox is not None:
            outbox.close()

        if detector is not None:
            detector.close()

        raise


def run(config: dict[str, Any]) -> None:
    """Run the continuous camera-to-backend processing pipeline."""

    validate_config(config)

    camera_config = config["camera"]
    transport_config = config["transport"]

    camera_env = str(
        camera_config.get("rtsp_uri_env", "RTSP_URI")
    )

    camera_source = os.environ[camera_env].strip()

    camera_id = str(
        camera_config.get(
            "id",
            camera_config.get("name", "camera-1"),
        )
    )

    sample_fps = float(camera_config.get("fps_sample", 5))
    sample_interval = 1.0 / sample_fps

    reconnect_delay = float(
        camera_config.get("reconnect_delay_seconds", 3)
    )

    max_reconnect_delay = float(
        camera_config.get("max_reconnect_delay_seconds", 30)
    )

    sender_interval = float(
        transport_config.get("send_interval_seconds", 1)
    )

    health_interval = float(
        config.get("health", {}).get("interval_seconds", 60)
    )

    if reconnect_delay <= 0 or max_reconnect_delay < reconnect_delay:
        raise EdgeRuntimeError("Invalid camera reconnect configuration.")

    if sender_interval <= 0 or health_interval <= 0:
        raise EdgeRuntimeError("Invalid sender or health interval.")

    runtime = build_runtime(config)

    detector = runtime["detector"]
    tracker = runtime["tracker"]
    processor = runtime["processor"]
    outbox = runtime["outbox"]
    sender = runtime["sender"]
    health_reporter = runtime["health"]

    stop_requested = False

    def request_shutdown(signum: int, frame: Any) -> None:
        nonlocal stop_requested
        LOGGER.info("Shutdown signal received: %s", signum)
        stop_requested = True

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    capture: cv2.VideoCapture | None = None
    frame_id = 0
    next_sample_at = 0.0
    next_send_at = 0.0
    next_health_at = 0.0
    current_reconnect_delay = reconnect_delay

    LOGGER.info(
        "RADA Edge starting | site=%s | camera=%s | fps_sample=%.2f",
        config["site_id"],
        camera_id,
        sample_fps,
    )

    try:
        while not stop_requested:

            # ------------------------------------------------ camera
            if capture is None or not capture.isOpened():
                try:
                    LOGGER.info("Connecting to camera stream...")
                    capture = open_camera(camera_source)
                    current_reconnect_delay = reconnect_delay
                    next_sample_at = 0.0

                    # Do not carry old tracks across a camera disconnect.
                    tracker.reset()
                    processor.reset()

                    LOGGER.info("Camera stream connected.")

                except EdgeRuntimeError as exc:
                    LOGGER.warning("%s", exc)
                    time.sleep(current_reconnect_delay)

                    current_reconnect_delay = min(
                        current_reconnect_delay * 2,
                        max_reconnect_delay,
                    )
                    continue

            # ------------------------------------------------ frame
            success, frame = capture.read()

            if not success or frame is None:
                LOGGER.warning("Camera frame unavailable; reconnecting.")

                capture.release()
                capture = None

                tracker.reset()
                processor.reset()

                time.sleep(current_reconnect_delay)

                current_reconnect_delay = min(
                    current_reconnect_delay * 2,
                    max_reconnect_delay,
                )
                continue

            now_monotonic = time.monotonic()

            # ------------------------------------------------ sender
            # Send pending events even when the current frame is skipped.
            if now_monotonic >= next_send_at:
                try:
                    result = sender.send_pending()

                    if result.sent or result.dead:
                        LOGGER.info(
                            "Transport | sent=%d retry=%d dead=%d remaining=%d",
                            result.sent,
                            result.retried,
                            result.dead,
                            result.remaining,
                        )

                except Exception:
                    LOGGER.exception("Transport delivery failed.")

                next_send_at = now_monotonic + sender_interval

            # ------------------------------------------------ health
            if now_monotonic >= next_health_at:
                try:
                    report = health_reporter.collect(
                        camera_ok=True,
                        detector_ok=True,
                    )

                    LOGGER.info(
                        "Edge health | status=%s | uptime=%.1fs",
                        report.status,
                        report.uptime_seconds,
                    )

                    if report.status in {"unhealthy", "degraded"}:
                        for check in report.checks:
                            if check.status in {"unhealthy", "degraded"}:
                                LOGGER.warning(
                                    "Health check %s: %s",
                                    check.name,
                                    check.message,
                                )

                except Exception:
                    LOGGER.exception("Health collection failed.")

                next_health_at = now_monotonic + health_interval

            # ------------------------------------------------ sampling
            if now_monotonic < next_sample_at:
                continue

            next_sample_at = now_monotonic + sample_interval
            frame_id += 1

            frame_timestamp = datetime.now(timezone.utc)

            try:
                # 1. Object detection
                detections = detector.detect(frame)

                # 2. Object tracking
                tracked_detections = tracker.update(
                    detections,
                    frame_id=frame_id,
                )

                # 3. Zone crossing and event generation
                events = processor.process_frame(
                    detections=tracked_detections,
                    frame=frame,
                    timestamp=frame_timestamp,
                    frame_id=frame_id,
                )

                # 4. Persist events before attempting network delivery
                for event in events:
                    inserted = outbox.enqueue(event.to_dict())

                    if inserted:
                        LOGGER.info(
                            "Event queued | event_id=%s | category=%s | confidence=%.3f",
                            event.event_id,
                            event.category,
                            event.confidence,
                        )

            except Exception:
                # A single bad frame must not terminate the whole edge process.
                LOGGER.exception(
                    "Frame processing failed | frame_id=%d",
                    frame_id,
                )

    finally:
        LOGGER.info("Stopping RADA Edge runtime...")

        if capture is not None:
            capture.release()

        try:
            # Make one last best-effort delivery attempt.
            result = sender.send_pending()
            LOGGER.info(
                "Final transport attempt | sent=%d | remaining=%d",
                result.sent,
                result.remaining,
            )
        except Exception:
            LOGGER.exception("Final transport attempt failed.")

        sender.close()
        outbox.close()
        detector.close()

        LOGGER.info("RADA Edge stopped.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RADA AI Edge runtime",
    )

    parser.add_argument(
        "--config",
        default="edge/config.yaml",
        help="Path to the edge YAML configuration.",
    )

    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate configuration without starting the camera.",
    )

    args = parser.parse_args()

    try:
        config, config_dir = load_config(args.config)
        normalize_config_paths(config, config_dir)
        configure_logging(config)

        if args.check_config:
            validate_config(config)
            LOGGER.info("Configuration validation successful.")
            return 0

        run(config)
        return 0

    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user.")
        return 0

    except Exception as exc:
        logging.basicConfig(level=logging.ERROR)
        LOGGER.exception("RADA Edge startup/runtime error: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
