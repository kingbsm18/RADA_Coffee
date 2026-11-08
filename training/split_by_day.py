"""training/split_by_day.py — TODO: implement (see docs/architecture.md)."""
"""Split a YOLO dataset by recording day to prevent temporal leakage."""

from __future__ import annotations

import argparse
import csv
import logging
import random

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


LOGGER = logging.getLogger("rada.training.split")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def load_manifest(path: Path) -> dict[str, str]:
    """Load image-to-day mapping from extract_frames manifest."""

    if not path.is_file():
        raise FileNotFoundError(
            f"Manifest not found: {path}. "
            "Run extract_frames.py first."
        )

    result: dict[str, str] = {}

    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        if not {"image", "day"}.issubset(reader.fieldnames or []):
            raise ValueError("Manifest must contain image and day columns.")

        for row in reader:
            image = str(row["image"]).strip()
            day = str(row["day"]).strip()

            if image and day:
                result[image] = day

    return result


def split_days(
    days: list[str],
    *,
    train_ratio: float,
    val_ratio: float,
    seed: int,
) -> dict[str, set[str]]:
    """Assign whole days to train, validation and test."""

    if not 0 < train_ratio < 1:
        raise ValueError("train_ratio must be between 0 and 1.")

    if not 0 <= val_ratio < 1:
        raise ValueError("val_ratio must be between 0 and 1.")

    if train_ratio + val_ratio >= 1:
        raise ValueError("train_ratio + val_ratio must be less than 1.")

    unique_days = sorted(set(days))

    if len(unique_days) < 3:
        raise ValueError(
            "At least three distinct recording days are required "
            "for train/validation/test separation."
        )

    random.Random(seed).shuffle(unique_days)

    total = len(unique_days)
    train_count = max(1, round(total * train_ratio))
    val_count = max(1, round(total * val_ratio))

    if train_count + val_count >= total:
        train_count = total - 2
        val_count = 1

    train_days = set(unique_days[:train_count])
    val_days = set(unique_days[train_count:train_count + val_count])
    test_days = set(unique_days[train_count + val_count:])

    return {
        "train": train_days,
        "val": val_days,
        "test": test_days,
    }


def _copy_pair(
    image_path: Path,
    labels_root: Path,
    output_root: Path,
    split: str,
    source_root: Path,
) -> None:
    """Copy an image and its YOLO label file into a split directory."""

    relative = image_path.relative_to(source_root)
    label_path = labels_root / relative.with_suffix(".txt")

    if not label_path.is_file():
        raise FileNotFoundError(
            f"Missing YOLO annotation for image {image_path}: {label_path}"
        )

    destination_image = output_root / "images" / split / relative
    destination_label = (
        output_root / "labels" / split / relative.with_suffix(".txt")
    )

    destination_image.parent.mkdir(parents=True, exist_ok=True)
    destination_label.parent.mkdir(parents=True, exist_ok=True)

    import shutil

    shutil.copy2(image_path, destination_image)
    shutil.copy2(label_path, destination_label)


def create_dataset_split(
    *,
    images_dir: Path,
    labels_dir: Path,
    manifest_path: Path,
    output_dir: Path,
    train_ratio: float = 0.70,
    val_ratio: float = 0.20,
    seed: int = 42,
    names: list[str] | None = None,
) -> dict[str, Any]:
    """Create train/val/test directories and a YOLO dataset YAML."""

    if not images_dir.is_dir() or not labels_dir.is_dir():
        raise NotADirectoryError("Images and labels directories must exist.")

    image_days = load_manifest(manifest_path)

    images = sorted(
        path
        for path in images_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )

    if not images:
        raise ValueError("No images found.")

    groups: dict[str, list[Path]] = defaultdict(list)

    for image in images:
        day = image_days.get(image.name)

        if day is None:
            # Also allow a manifest key relative to images_dir.
            day = image_days.get(str(image.relative_to(images_dir)))

        if day is None:
            raise ValueError(
                f"No recording day found in manifest for {image.name}."
            )

        groups[day].append(image)

    assignments = split_days(
        list(groups),
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        seed=seed,
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {}

    for split, split_days_set in assignments.items():
        selected_images = [
            image
            for day in split_days_set
            for image in groups[day]
        ]

        for image in selected_images:
            _copy_pair(
                image,
                labels_dir,
                output_dir,
                split,
                images_dir,
            )

        summary[split] = {
            "days": sorted(split_days_set),
            "images": len(selected_images),
        }

    if names is None:
        names = ["coffee_cup", "soft_drink"]

    if not names or any(not name.strip() for name in names):
        raise ValueError("Class names must be non-empty.")

    dataset_config = {
        "path": str(output_dir.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {
            index: name
            for index, name in enumerate(names)
        },
    }

    yaml_path = output_dir / "dataset.yaml"

    with yaml_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            dataset_config,
            file,
            sort_keys=False,
            allow_unicode=True,
        )

    LOGGER.info("Dataset split saved to %s", yaml_path)

    for split, details in summary.items():
        LOGGER.info(
            "%s: %d images across %d days",
            split,
            details["images"],
            len(details["days"]),
        )

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split RADA YOLO dataset by recording day."
    )
    parser.add_argument("--images", default="training/data/raw/images")
    parser.add_argument("--labels", default="training/data/raw/labels")
    parser.add_argument("--manifest", default="training/data/raw/manifest.csv")
    parser.add_argument("--output", default="training/data/processed")
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--val-ratio", type=float, default=0.20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--names",
        nargs="+",
        default=["coffee_cup", "soft_drink"],
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    create_dataset_split(
        images_dir=Path(args.images),
        labels_dir=Path(args.labels),
        manifest_path=Path(args.manifest),
        output_dir=Path(args.output),
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        seed=args.seed,
        names=args.names,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
