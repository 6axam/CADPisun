"""Strict online-handwriting capture models and immutable persistence."""

from .models import (
    CapturePoint,
    CaptureProvenance,
    CaptureSample,
    CaptureSession,
    CaptureStroke,
    CoordinateReference,
    DeviceCapabilities,
    WritingGuides,
)
from .repository import CaptureRecord, CaptureRepository, load_capture_bytes, serialize_capture
from .processing import (
    ProcessedCapture,
    ProcessedRecord,
    ProcessedRepository,
    ProcessingParameters,
    process_sample,
)

__all__ = [
    "CapturePoint",
    "CaptureProvenance",
    "CaptureRecord",
    "CaptureRepository",
    "CaptureSample",
    "CaptureSession",
    "CaptureStroke",
    "CoordinateReference",
    "DeviceCapabilities",
    "ProcessedCapture",
    "ProcessedRecord",
    "ProcessedRepository",
    "ProcessingParameters",
    "WritingGuides",
    "load_capture_bytes",
    "process_sample",
    "serialize_capture",
]
