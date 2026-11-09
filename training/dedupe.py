"""Remove exact and near-duplicate images from a YOLO dataset."""

from __future__ import annotations

import argparse
import hashlib
import logging

from pathlib import Path

import cv2
import numpy as np


LOGGER = logging.getLogger("rada.training.dedupe")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def exact_hash(path: Path) -> str:
    """Return a SHA-256 hash of the original image file."""

    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def perceptual_hash(path: Path) -> int:
    """Calculate a 64-bit difference hash."""

    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)

    if image is None:
        raise ValueError(f"Could not read image: {path}")

    resized = cv2.resize(
        image,
        (9, 8),
        interpolation=cv2.INTER_AREA,
    )

    difference = resized[:, 1:] > resized[:, :-1]

    value = 0

    for bit in difference.flatten():
        value = (value << 1) | int(bit)

    return value


def hamming_distance(first: int, second: int) -> int:
    """Return the number of differing bits between two hashes."""

    return (first ^ second).bit_count()


def deduplicate(
    images_dir: Path,
    *,
    labels_dir: Path | None = None,
    threshold: int = 4,
    dry_run: bool = True,
) -> list[tuple[Path, Path]]:
    """Find and optionally remove duplicate images.

    The first encountered image is kept. Near duplicates are detected
    using a 64-bit perceptual hash and a Hamming distance threshold.
    """

    if not images_dir.is_dir():
        raise NotADirectoryError(images_dir)

    if not 0 <= threshold <= 64:
        raise ValueError("threshold must be between 0 and 64.")

    image_paths = sorted(
        path
        for path in images_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )

    exact_seen: dict[str, Path] = {}
    accepted_hashes: list[tuple[int, Path]] = []
    duplicates: list[tuple[Path, Path]] = []

    for path in image_paths:
        try:
            digest = exact_hash(path)

            if digest in exact_seen:
                duplicates.append((path, exact_seen[digest]))
                continue

            image_hash = perceptual_hash(path)

        except (OSError, ValueError) as exc:
            LOGGER.warning("Skipping %s: %s", path, exc)
            continue

        similar = next(
            (
                kept_path
                for kept_hash, kept_path in accepted_hashes
                if hamming_distance(image_hash, kept_hash) <= threshold
            ),
            None,
        )

        if similar is not None:
            duplicates.append((path, similar))
            continue

        exact_seen[digest] = path
        accepted_hashes.append((image_hash, path))

    for duplicate, _kept in duplicates:
        LOGGER.info(
            "%s duplicate: %s (kept: %s)",
            "Would remove" if dry_run else "Removing",
            duplicate,
            _kept,
        )

        if dry_run:
            continue

        if labels_dir is not None:
            label_path = (
                labels_dir
                / duplicate.relative_to(images_dir).with_suffix(".txt")
            )

            if label_path.is_file():
                label_path.unlink()

        duplicate.unlink()

    LOGGER.info(
        "Scanned %d images; found %d duplicates.",
        len(image_paths),
        len(duplicates),
    )

    return duplicates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deduplicate RADA training images."
    )
    parser.add_argument("--images", default="training/data/raw/images")
    parser.add_argument("--labels", default="training/data/raw/labels")
    parser.add_argument("--threshold", type=int, default=4)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually remove duplicates. Default is a dry run.",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    labels_dir = Path(args.labels)

    deduplicate(
        Path(args.images),
        labels_dir=labels_dir if labels_dir.is_dir() else None,
        threshold=args.threshold,
        dry_run=not args.apply,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
