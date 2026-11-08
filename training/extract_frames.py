"""training/extract_frames.py — TODO: implement (see docs/architecture.md)."""
"""Extract training frames from videos and create a reproducible manifest."""

from __future__ import annotations

import argparse
import csv
import logging

from datetime import datetime, timezone
from pathlib import Path

import cv2


LOGGER = logging.getLogger("rada.training.extract")


def extract_frames(
    video_path: Path,
    output_dir: Path,
    *,
    interval_seconds: float = 1.0,
    recorded_at: datetime | None = None,
    image_extension: str = ".jpg",
) -> list[dict[str, str | int]]:
    """Extract one frame every interval_seconds from a video."""

    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be positive.")

    if image_extension.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("Supported image extensions: .jpg, .jpeg, .png.")

    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")

    capture = cv2.VideoCapture(str(video_path))

    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    if fps <= 0:
        capture.release()
        raise RuntimeError("Video reports an invalid FPS value.")

    if recorded_at is None:
        recorded_at = datetime.fromtimestamp(
            video_path.stat().st_mtime,
            tz=timezone.utc,
        )
    elif recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        capture.release()
        raise ValueError("recorded_at must include a timezone.")

    recorded_at = recorded_at.astimezone(timezone.utc)

    output_dir.mkdir(parents=True, exist_ok=True)

    interval_frames = max(1, round(fps * interval_seconds))
    manifest: list[dict[str, str | int]] = []

    frame_index = 0
    saved_count = 0

    try:
        while True:
            success, frame = capture.read()

            if not success:
                break

            if frame_index % interval_frames == 0:
                offset_seconds = frame_index / fps
                timestamp = recorded_at.timestamp() + offset_seconds
                frame_time = datetime.fromtimestamp(
                    timestamp,
                    tz=timezone.utc,
                )

                filename = (
                    f"{video_path.stem}_"
                    f"{frame_index:09d}{image_extension.lower()}"
                )

                destination = output_dir / filename

                if not cv2.imwrite(str(destination), frame):
                    raise RuntimeError(
                        f"Could not write extracted frame: {destination}"
                    )

                manifest.append(
                    {
                        "image": filename,
                        "source_video": str(video_path.resolve()),
                        "frame_index": frame_index,
                        "timestamp": frame_time.isoformat(),
                        "day": frame_time.date().isoformat(),
                    }
                )

                saved_count += 1

            frame_index += 1

    finally:
        capture.release()

    LOGGER.info(
        "Extracted %d frames from %s (%d source frames).",
        saved_count,
        video_path.name,
        frame_count,
    )

    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract frames from videos for RADA model training."
    )
    parser.add_argument("--input", required=True, help="Input video or directory.")
    parser.add_argument("--output", default="training/data/raw/images")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument(
        "--recorded-at",
        help="Video recording start time in ISO-8601 with timezone.",
    )

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    input_path = Path(args.input)
    output_dir = Path(args.output)

    recorded_at = None

    if args.recorded_at:
        recorded_at = datetime.fromisoformat(
            args.recorded_at.replace("Z", "+00:00")
        )

        if recorded_at.tzinfo is None:
            parser.error("--recorded-at must include a timezone.")

    videos = (
        [input_path]
        if input_path.is_file()
        else sorted(
            path
            for path in input_path.rglob("*")
            if path.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv"}
        )
    )

    if not videos:
        parser.error("No supported video files found.")

    all_rows: list[dict[str, str | int]] = []

    for video in videos:
        rows = extract_frames(
            video,
            output_dir,
            interval_seconds=args.interval,
            recorded_at=recorded_at,
        )
        all_rows.extend(rows)

    manifest_path = output_dir.parent / "manifest.csv"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    with manifest_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "image",
                "source_video",
                "frame_index",
                "timestamp",
                "day",
            ],
        )
        writer.writeheader()
        writer.writerows(all_rows)

    LOGGER.info("Manifest saved to %s", manifest_path)
    LOGGER.info("Total extracted frames: %d", len(all_rows))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
