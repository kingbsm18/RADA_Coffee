
"""Video capture and region-of-interest utilities for RADA Edge."""

from .capture import (
    CaptureError,
    FrameCapture,
    create_capture,
    open_capture,
)
from .roi import (
    RegionOfInterest,
    apply_roi,
    create_roi,
    crop_roi,
    point_in_roi,
)

__all__ = [
    "CaptureError",
    "FrameCapture",
    "create_capture",
    "open_capture",
    "RegionOfInterest",
    "apply_roi",
    "create_roi",
    "crop_roi",
    "point_in_roi",
]
