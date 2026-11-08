"""training/evaluate.py — TODO: implement (see docs/architecture.md)."""
"""Evaluate a trained YOLO model on the held-out test set."""

from __future__ import annotations

import argparse
import json
import logging

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("rada.training.evaluate")


def _to_float(value: Any) -> float | None:
    """Convert a metric value to a JSON-compatible float."""

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None

    if result != result or result in {float("inf"), float("-inf")}:
        return None

    return result


def evaluate_model(
    *,
    weights: Path,
    dataset_yaml: Path,
    output_path: Path,
    image_size: int = 640,
    batch_size: int = 16,
    device: str | None = None,
) -> dict[str, Any]:
    """Evaluate a YOLO model and persist its main metrics."""

    if not weights.is_file():
        raise FileNotFoundError(f"Model weights not found: {weights}")

    if not dataset_yaml.is_file():
        raise FileNotFoundError(f"Dataset YAML not found: {dataset_yaml}")

    if image_size < 32 or batch_size < 1:
        raise ValueError("Invalid evaluation parameters.")

    try:
        import yaml
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Ultralytics and PyYAML are required for evaluation."
        ) from exc

    with dataset_yaml.open("r", encoding="utf-8") as file:
        dataset = yaml.safe_load(file)

    if not isinstance(dataset, dict) or not dataset.get("test"):
        raise ValueError(
            "Dataset YAML must define a separate test split."
        )

    model = YOLO(str(weights))

    arguments: dict[str, Any] = {
        "data": str(dataset_yaml.resolve()),
        "split": "test",
        "imgsz": image_size,
        "batch": batch_size,
        "plots": True,
        "verbose": True,
    }

    if device:
        arguments["device"] = device

    metrics = model.val(**arguments)

    box_metrics = getattr(metrics, "box", None)

    if box_metrics is None:
        raise RuntimeError("YOLO evaluation did not return box metrics.")

    result: dict[str, Any] = {
        "model": str(weights.resolve()),
        "dataset": str(dataset_yaml.resolve()),
        "split": "test",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {
            "precision": _to_float(getattr(box_metrics, "mp", None)),
            "recall": _to_float(getattr(box_metrics, "mr", None)),
            "map50": _to_float(getattr(box_metrics, "map50", None)),
            "map50_95": _to_float(getattr(box_metrics, "map", None)),
        },
        "per_class": {},
    }

    names = getattr(metrics, "names", {}) or {}
    class_map = getattr(box_metrics, "maps", [])

    for index, value in enumerate(class_map):
        if isinstance(names, dict):
            class_name = str(names.get(index, f"class_{index}"))
        else:
            class_name = str(
                names[index] if index < len(names) else f"class_{index}"
            )

        result["per_class"][class_name] = {
            "map50_95": _to_float(value),
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    LOGGER.info("Evaluation metrics saved to %s", output_path)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the RADA YOLO detector."
    )
    parser.add_argument("--weights", required=True)
    parser.add_argument("--data", default="training/data/processed/dataset.yaml")
    parser.add_argument("--output", default="training/reports/evaluation.json")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--device", default=None)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    evaluate_model(
        weights=Path(args.weights),
        dataset_yaml=Path(args.data),
        output_path=Path(args.output),
        image_size=args.imgsz,
        batch_size=args.batch,
        device=args.device,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
