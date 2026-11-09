"""Export a trained YOLO model to ONNX for RADA Edge inference."""

from __future__ import annotations

import argparse
import logging

from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("rada.training.export")


def export_onnx(
    *,
    weights: Path,
    output_dir: Path,
    image_size: int = 640,
    opset: int = 17,
    simplify: bool = False,
    verify: bool = True,
) -> Path:
    """Export YOLO weights to a static-shape ONNX model."""

    if not weights.is_file():
        raise FileNotFoundError(f"Model weights not found: {weights}")

    if image_size < 32:
        raise ValueError("image_size must be at least 32.")

    if opset < 12:
        raise ValueError("Use ONNX opset 12 or newer.")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "Ultralytics is required. Install training/requirements.txt."
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(weights))

    exported = model.export(
        format="onnx",
        imgsz=image_size,
        opset=opset,
        simplify=simplify,
        dynamic=False,
        half=False,
        batch=1,
    )

    exported_path = Path(exported)

    if not exported_path.is_file():
        raise RuntimeError(
            f"Ultralytics did not create the expected ONNX file: {exported_path}"
        )

    destination = output_dir / f"{weights.stem}.onnx"

    if exported_path.resolve() != destination.resolve():
        import shutil

        shutil.copy2(exported_path, destination)

    if verify:
        try:
            import onnx
        except ImportError as exc:
            raise RuntimeError(
                "Install the 'onnx' package to verify the exported model."
            ) from exc

        graph = onnx.load(str(destination))
        onnx.checker.check_model(graph)

        inputs = graph.graph.input

        if len(inputs) != 1:
            raise RuntimeError(
                "Exported ONNX model must have exactly one input."
            )

        input_shape = [
            dimension.dim_value
            for dimension in inputs[0].type.tensor_type.shape.dim
        ]

        if len(input_shape) != 4:
            raise RuntimeError("ONNX input must use NCHW dimensions.")

        if input_shape[1] not in {0, 3}:
            raise RuntimeError("ONNX input must have 3 channels.")

        if input_shape[2:] != [image_size, image_size]:
            raise RuntimeError(
                f"Unexpected ONNX input dimensions: {input_shape}"
            )

        LOGGER.info("ONNX model passed structural validation.")

    LOGGER.info("ONNX model exported to %s", destination)

    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export RADA YOLO weights to ONNX."
    )
    parser.add_argument("--weights", required=True)
    parser.add_argument("--output", default="edge/models")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument("--simplify", action="store_true")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip ONNX structural validation.",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    export_onnx(
        weights=Path(args.weights),
        output_dir=Path(args.output),
        image_size=args.imgsz,
        opset=args.opset,
        simplify=args.simplify,
        verify=not args.no_verify,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
