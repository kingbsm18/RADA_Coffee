"""edge/detection/tensorrt_backend.py — TODO: implement (see docs/architecture.md)."""
"""TensorRT inference backend using ONNX Runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .onnx_backend import ONNXBackend


class TensorRTBackend(ONNXBackend):
    """
    Run an ONNX model with TensorRT acceleration.

    Requires an ONNX Runtime installation compiled with
    TensorRT Execution Provider support.
    """

    def __init__(
        self,
        model_path: str | Path,
        fp16: bool = True,
        engine_cache_dir: str | Path | None = None,
    ) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError(
                "ONNX Runtime is required for TensorRT inference."
            ) from exc

        model_path = Path(model_path)

        if not model_path.is_file():
            raise FileNotFoundError(
                f"ONNX model not found: {model_path}"
            )

        if model_path.suffix.lower() != ".onnx":
            raise ValueError(
                "TensorRT Execution Provider expects an ONNX model."
            )

        available = ort.get_available_providers()

        if "TensorrtExecutionProvider" not in available:
            raise RuntimeError(
                "TensorRT Execution Provider is unavailable. "
                "Install an ONNX Runtime GPU build with TensorRT support. "
                f"Available providers: {available}"
            )

        cache_dir = Path(
            engine_cache_dir or "/tmp/rada_trt_cache"
        )

        cache_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        trt_options: dict[str, Any] = {
            "trt_engine_cache_enable": True,
            "trt_engine_cache_path": str(cache_dir),
            "trt_engine_cache_prefix": "rada",
            "trt_fp16_enable": bool(fp16),
        }

        providers: list[Any] = [
            (
                "TensorrtExecutionProvider",
                trt_options,
            )
        ]

        if "CUDAExecutionProvider" in available:
            providers.append("CUDAExecutionProvider")

        if "CPUExecutionProvider" in available:
            providers.append("CPUExecutionProvider")

        super().__init__(
            model_path=model_path,
            providers=providers,
        )
