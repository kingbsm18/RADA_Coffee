"""edge/detection/detector.py — TODO: implement (see docs/architecture.md)."""
"""Object detector and YOLO post-processing."""

from __future__ import annotations

import json

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class Detection:
    """One detected object in original image coordinates."""

    bbox: tuple[float, float, float, float]
    confidence: float
    class_id: int
    class_name: str
    track_id: int | None = None


class InferenceBackend(Protocol):
    input_size: tuple[int, int] | None
    input_dtype: Any
    metadata: Mapping[str, Any]

    def infer(self, tensor: np.ndarray) -> Sequence[np.ndarray]:
        ...


def _normalize_class_names(
    value: Any,
) -> dict[int, str]:
    """Convert model labels into an integer-to-name mapping."""

    if value is None:
        return {}

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}

    if isinstance(value, Mapping):
        result: dict[int, str] = {}

        for key, label in value.items():
            try:
                result[int(key)] = str(label)
            except (TypeError, ValueError):
                continue

        return result

    if isinstance(value, Sequence):
        return {
            index: str(label)
            for index, label in enumerate(value)
        }

    return {}


class Detector:
    """YOLO-style object detector."""

    SUPPORTED_FORMATS = {
        "auto",
        "yolov5",
        "yolov8",
        "xyxy",
    }

    def __init__(
        self,
        backend: InferenceBackend,
        confidence_min: float = 0.4,
        nms_iou: float = 0.45,
        input_size: int | tuple[int, int] | None = None,
        class_names: Any = None,
        max_detections: int = 300,
        model_format: str = "auto",
    ) -> None:
        if not 0 <= confidence_min <= 1:
            raise ValueError("confidence_min must be between 0 and 1.")

        if not 0 < nms_iou <= 1:
            raise ValueError("nms_iou must be between 0 and 1.")

        if max_detections < 1:
            raise ValueError("max_detections must be positive.")

        if model_format not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported model format: {model_format}"
            )

        self.backend = backend
        self.confidence_min = float(confidence_min)
        self.nms_iou = float(nms_iou)
        self.max_detections = int(max_detections)
        self.model_format = model_format

        if input_size is None:
            input_size = getattr(backend, "input_size", None)

        if input_size is None:
            input_size = (640, 640)

        if isinstance(input_size, int):
            input_size = (input_size, input_size)

        if len(input_size) != 2:
            raise ValueError(
                "input_size must be an integer or (height, width)."
            )

        height, width = int(input_size[0]), int(input_size[1])

        if height <= 0 or width <= 0:
            raise ValueError("Invalid detector input size.")

        self.input_size = (height, width)

        self.class_names = _normalize_class_names(class_names)

        if not self.class_names:
            metadata = getattr(backend, "metadata", {})
            self.class_names = _normalize_class_names(
                metadata.get("names")
            )

    def detect(
        self,
        frame: np.ndarray,
    ) -> list[Detection]:
        """Detect objects in one BGR image."""

        if not isinstance(frame, np.ndarray):
            raise TypeError("frame must be a NumPy array.")

        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(
                "Expected a BGR image with shape (height, width, 3)."
            )

        if frame.size == 0:
            return []

        tensor, transform = self._preprocess(frame)

        outputs = self.backend.infer(tensor)

        return self._postprocess(
            outputs=outputs,
            transform=transform,
        )

    def _preprocess(
        self,
        frame: np.ndarray,
    ) -> tuple[
        np.ndarray,
        tuple[float, float, int, int, int, int],
    ]:
        """Resize with letterboxing and convert BGR to RGB."""

        original_height, original_width = frame.shape[:2]

        target_height, target_width = self.input_size

        scale = min(
            target_width / original_width,
            target_height / original_height,
        )

        resized_width = max(
            1,
            min(target_width, int(round(original_width * scale))),
        )

        resized_height = max(
            1,
            min(target_height, int(round(original_height * scale))),
        )

        resized = cv2.resize(
            frame,
            (resized_width, resized_height),
            interpolation=cv2.INTER_LINEAR,
        )

        pad_width = target_width - resized_width
        pad_height = target_height - resized_height

        pad_left = pad_width // 2
        pad_top = pad_height // 2

        canvas = np.full(
            (target_height, target_width, 3),
            114,
            dtype=np.uint8,
        )

        canvas[
            pad_top:pad_top + resized_height,
            pad_left:pad_left + resized_width,
        ] = resized

        rgb = cv2.cvtColor(
            canvas,
            cv2.COLOR_BGR2RGB,
        )

        tensor = (
            rgb.astype(np.float32) / 255.0
        ).transpose(2, 0, 1)[None, ...]

        tensor = np.ascontiguousarray(tensor)

        scale_x = resized_width / original_width
        scale_y = resized_height / original_height

        transform = (
            scale_x,
            scale_y,
            pad_left,
            pad_top,
            original_width,
            original_height,
        )

        return tensor, transform

    def _postprocess(
        self,
        outputs: Sequence[np.ndarray],
        transform: tuple[
            float, float, int, int, int, int
        ],
    ) -> list[Detection]:
        """Decode raw YOLO predictions into detections."""

        if not outputs:
            return []

        if len(outputs) != 1:
            raise ValueError(
                "This detector expects one YOLO output tensor. "
                "Models with separate boxes/scores outputs need "
                "a dedicated decoder."
            )

        predictions = np.asarray(outputs[0])

        while predictions.ndim > 2 and predictions.shape[0] == 1:
            predictions = predictions[0]

        if predictions.ndim != 2:
            raise ValueError(
                f"Unsupported YOLO output shape: {predictions.shape}"
            )

        if predictions.shape[0] == 0:
            return []

        # Convert channel-first predictions to row-first predictions.
        if (
            predictions.shape[0] == 6
            and predictions.shape[1] > 6
        ):
            predictions = predictions.T
        elif (
            predictions.shape[0] < predictions.shape[1]
            and predictions.shape[0] <= 512
            and predictions.shape[1] > 512
        ):
            predictions = predictions.T

        if predictions.shape[1] < 6:
            raise ValueError(
                f"Unsupported YOLO output shape: {predictions.shape}"
            )

        output_format = self._resolve_output_format(
            predictions.shape[1]
        )

        scale_x, scale_y, pad_left, pad_top, width, height = transform

        candidates: list[
            tuple[tuple[float, float, float, float], float, int]
        ] = []

        for row in predictions:
            if not np.isfinite(row).all():
                continue

            if output_format == "xyxy":
                x1, y1, x2, y2 = map(float, row[:4])
                confidence = float(row[4])
                class_id = int(round(float(row[5])))

            else:
                center_x, center_y, box_width, box_height = map(
                    float,
                    row[:4],
                )

                if output_format == "yolov5":
                    objectness = float(row[4])
                    class_scores = row[5:]

                    if class_scores.size == 0:
                        continue

                    class_id = int(np.argmax(class_scores))

                    confidence = (
                        objectness
                        * float(class_scores[class_id])
                    )

                else:
                    class_scores = row[4:]

                    if class_scores.size == 0:
                        continue

                    class_id = int(np.argmax(class_scores))
                    confidence = float(class_scores[class_id])

                x1 = center_x - box_width / 2
                y1 = center_y - box_height / 2
                x2 = center_x + box_width / 2
                y2 = center_y + box_height / 2

            if class_id < 0 or confidence < self.confidence_min:
                continue

            confidence = min(1.0, max(0.0, confidence))

            # Undo letterbox and restore original image coordinates.
            x1 = (x1 - pad_left) / scale_x
            y1 = (y1 - pad_top) / scale_y
            x2 = (x2 - pad_left) / scale_x
            y2 = (y2 - pad_top) / scale_y

            x1 = float(np.clip(x1, 0, width))
            y1 = float(np.clip(y1, 0, height))
            x2 = float(np.clip(x2, 0, width))
            y2 = float(np.clip(y2, 0, height))

            if x2 <= x1 or y2 <= y1:
                continue

            candidates.append(
                (
                    (x1, y1, x2, y2),
                    confidence,
                    class_id,
                )
            )

        if not candidates:
            return []

        # Apply NMS separately for each class.
        kept_indices: list[int] = []

        class_ids = sorted({
            candidate[2]
            for candidate in candidates
        })

        for class_id in class_ids:
            indices = [
                index
                for index, candidate in enumerate(candidates)
                if candidate[2] == class_id
            ]

            boxes = [
                candidates[index][0]
                for index in indices
            ]

            scores = [
                candidates[index][1]
                for index in indices
            ]

            local_keep = self._nms(
                boxes,
                scores,
                self.nms_iou,
            )

            kept_indices.extend(
                indices[index]
                for index in local_keep
            )

        kept_indices.sort(
            key=lambda index: candidates[index][1],
            reverse=True,
        )

        detections: list[Detection] = []

        for index in kept_indices[:self.max_detections]:
            bbox, confidence, class_id = candidates[index]

            class_name = self.class_names.get(
                class_id,
                f"class_{class_id}",
            )

            detections.append(
                Detection(
                    bbox=bbox,
                    confidence=confidence,
                    class_id=class_id,
                    class_name=class_name,
                )
            )

        return detections

    def _resolve_output_format(
        self,
        feature_count: int,
    ) -> str:
        """Determine the YOLO output format."""

        if self.model_format != "auto":
            output_format = self.model_format

        else:
            class_count = len(self.class_names)

            if (
                class_count > 0
                and feature_count == 5 + class_count
            ):
                output_format = "yolov5"

            elif (
                class_count > 0
                and feature_count == 4 + class_count
            ):
                output_format = "yolov8"

            elif feature_count == 6:
                output_format = "xyxy"

            elif feature_count == 85:
                output_format = "yolov5"

            else:
                output_format = "yolov8"

        if output_format == "xyxy" and feature_count != 6:
            raise ValueError(
                "The xyxy output format requires exactly 6 columns."
            )

        if output_format == "yolov5" and feature_count < 6:
            raise ValueError("Invalid YOLOv5 output dimensions.")

        if output_format == "yolov8" and feature_count < 5:
            raise ValueError("Invalid YOLOv8 output dimensions.")

        return output_format

    @staticmethod
    def _nms(
        boxes: Sequence[tuple[float, float, float, float]],
        scores: Sequence[float],
        threshold: float,
    ) -> list[int]:
        """Pure NumPy non-maximum suppression."""

        if not boxes:
            return []

        boxes_array = np.asarray(
            boxes,
            dtype=np.float32,
        )

        scores_array = np.asarray(
            scores,
            dtype=np.float32,
        )

        x1 = boxes_array[:, 0]
        y1 = boxes_array[:, 1]
        x2 = boxes_array[:, 2]
        y2 = boxes_array[:, 3]

        areas = (
            np.maximum(0, x2 - x1)
            * np.maximum(0, y2 - y1)
        )

        order = np.argsort(scores_array)[::-1]
        keep: list[int] = []

        while order.size > 0:
            current = int(order[0])
            keep.append(current)

            remaining = order[1:]

            if remaining.size == 0:
                break

            xx1 = np.maximum(x1[current], x1[remaining])
            yy1 = np.maximum(y1[current], y1[remaining])
            xx2 = np.minimum(x2[current], x2[remaining])
            yy2 = np.minimum(y2[current], y2[remaining])

            intersection = (
                np.maximum(0, xx2 - xx1)
                * np.maximum(0, yy2 - yy1)
            )

            union = (
                areas[current]
                + areas[remaining]
                - intersection
            )

            iou = intersection / np.maximum(union, 1e-9)

            order = remaining[iou <= threshold]

        return keep

    def close(self) -> None:
        """Release backend resources if supported."""

        close_method = getattr(self.backend, "close", None)

        if callable(close_method):
            close_method()


def create_detector(
    config: Mapping[str, Any],
) -> Detector:
    """Create a detector from the edge configuration."""

    section = config.get("detector", config)

    if not isinstance(section, Mapping):
        raise ValueError("Invalid detector configuration.")

    backend_name = str(
        section.get("backend", "onnx")
    ).lower()

    model_path = section.get(
        "model_path",
        "models/yolo.onnx",
    )

    if backend_name == "onnx":
        from .onnx_backend import ONNXBackend

        backend = ONNXBackend(
            model_path=model_path,
        )

    elif backend_name in {"tensorrt", "trt"}:
        from .tensorrt_backend import TensorRTBackend

        backend = TensorRTBackend(
            model_path=model_path,
            fp16=bool(section.get("fp16", True)),
            engine_cache_dir=section.get("engine_cache_dir"),
        )

    else:
        raise ValueError(
            f"Unsupported detector backend: {backend_name}"
        )

    return Detector(
        backend=backend,
        confidence_min=float(
            section.get("confidence_min", 0.4)
        ),
        nms_iou=float(
            section.get("nms_iou", 0.45)
        ),
        input_size=section.get("input_size"),
        class_names=section.get(
            "class_names",
            section.get("names"),
        ),
        max_detections=int(
            section.get("max_detections", 300)
        ),
        model_format=str(
            section.get("model_format", "auto")
        ).lower(),
    )
