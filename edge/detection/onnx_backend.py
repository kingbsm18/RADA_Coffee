"""ONNX Runtime inference backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np


ProviderSpec = str | tuple[str, dict[str, Any]]


class ONNXBackend:
    """Run an ONNX model through ONNX Runtime."""

    def __init__(
        self,
        model_path: str | Path,
        providers: Sequence[ProviderSpec] | None = None,
        intra_op_num_threads: int = 0,
        inter_op_num_threads: int = 0,
    ) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError(
                "ONNX Runtime is not installed. "
                "Install it with: pip install onnxruntime"
            ) from exc

        self.model_path = Path(model_path)

        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"ONNX model not found: {self.model_path}"
            )

        available = ort.get_available_providers()

        if providers is None:
            selected: list[ProviderSpec] = [
                name
                for name in (
                    "CUDAExecutionProvider",
                    "CPUExecutionProvider",
                )
                if name in available
            ]
        else:
            selected = []

            for provider in providers:
                name = (
                    provider[0]
                    if isinstance(provider, tuple)
                    else provider
                )

                if name in available:
                    selected.append(provider)

        if not selected:
            raise RuntimeError(
                "No compatible ONNX Runtime execution provider found. "
                f"Available providers: {available}"
            )

        session_options = ort.SessionOptions()
        session_options.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        )
        session_options.log_severity_level = 3

        if intra_op_num_threads > 0:
            session_options.intra_op_num_threads = intra_op_num_threads

        if inter_op_num_threads > 0:
            session_options.inter_op_num_threads = inter_op_num_threads

        self.session = ort.InferenceSession(
            str(self.model_path),
            sess_options=session_options,
            providers=selected,
        )

        inputs = self.session.get_inputs()

        if len(inputs) != 1:
            raise ValueError(
                "This backend expects a model with exactly one input."
            )

        self.input_name = inputs[0].name
        self.input_type = inputs[0].type

        if "float16" in self.input_type:
            self.input_dtype = np.float16
        elif "float" in self.input_type:
            self.input_dtype = np.float32
        else:
            raise TypeError(
                f"Unsupported ONNX input type: {self.input_type}"
            )

        input_shape = inputs[0].shape

        if len(input_shape) != 4:
            raise ValueError(
                "Expected an ONNX input with NCHW dimensions."
            )

        channels = input_shape[1]

        if isinstance(channels, int) and channels != 3:
            raise ValueError(
                f"Expected 3 input channels, received {channels}."
            )

        height = input_shape[2]
        width = input_shape[3]

        if (
            isinstance(height, int)
            and isinstance(width, int)
            and height > 0
            and width > 0
        ):
            self.input_size: tuple[int, int] | None = (
                height,
                width,
            )
        else:
            self.input_size = None

        self.metadata = (
            self.session.get_modelmeta().custom_metadata_map or {}
        )

    def infer(self, tensor: np.ndarray) -> list[np.ndarray]:
        """Execute inference and return raw model outputs."""

        tensor = np.asarray(
            tensor,
            dtype=self.input_dtype,
        )

        if tensor.ndim != 4:
            raise ValueError(
                f"Expected a 4D input tensor, got {tensor.shape}."
            )

        outputs = self.session.run(
            None,
            {self.input_name: tensor},
        )

        return [
            np.asarray(output)
            for output in outputs
        ]
