"""Fine-tune a pretrained YOLO model for RADA product detection."""

from __future__ import annotations

import argparse
import logging

from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("rada.training.train")


def train_model(
    *,
    dataset_yaml: Path,
    pretrained: str = "yolo11n.pt",
    epochs: int = 100,
    image_size: int = 640,
    batch_size: int = 16,
    patience: int = 20,
    project: Path = Path("training/runs"),
    name: str = "rada-coffee",
    device: str | None = None,
    workers: int = 4,
    seed: int = 42,
) -> Path:
    """Fine-tune a pretrained Ultralytics YOLO model."""

    if not dataset_yaml.is_file():
        raise FileNotFoundError(f"Dataset YAML not found: {dataset_yaml}")

    if epochs < 1 or image_size < 32 or batch_size < 1:
        raise ValueError("Invalid training parameters.")

    if patience < 0 or workers < 0:
        raise ValueError("patience and workers cannot be negative.")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Ultralytics is required. Install training/requirements.txt."
        ) from exc

    model = YOLO(pretrained)

    arguments: dict[str, Any] = {
        "data": str(dataset_yaml.resolve()),
        "epochs": epochs,
        "imgsz": image_size,
        "batch": batch_size,
        "patience": patience,
        "project": str(project),
        "name": name,
        "workers": workers,
        "seed": seed,
        "pretrained": True,
        "plots": True,
        "save": True,
        "save_period": 10,
        "exist_ok": True,
        "verbose": True,
    }

    if device:
        arguments["device"] = device

    LOGGER.info(
        "Starting YOLO fine-tuning | model=%s | dataset=%s",
        pretrained,
        dataset_yaml,
    )

    results = model.train(**arguments)

    save_dir = Path(results.save_dir)
    best_weights = save_dir / "weights" / "best.pt"

    if not best_weights.is_file():
        raise RuntimeError(
            f"Training completed but best.pt was not found in {save_dir}."
        )

    LOGGER.info("Best model saved to %s", best_weights)

    return best_weights


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fine-tune the RADA YOLO detector."
    )
    parser.add_argument("--data", default="training/data/processed/dataset.yaml")
    parser.add_argument("--model", default="yolo11n.pt")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--patience", type=int, default=20)
    parser.add_argument("--project", default="training/runs")
    parser.add_argument("--name", default="rada-coffee")
    parser.add_argument("--device", default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    train_model(
        dataset_yaml=Path(args.data),
        pretrained=args.model,
        epochs=args.epochs,
        image_size=args.imgsz,
        batch_size=args.batch,
        patience=args.patience,
        project=Path(args.project),
        name=args.name,
        device=args.device,
        workers=args.workers,
        seed=args.seed,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
