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
from .metrics import (
    GlyphMetricOverride,
    MetricProfileStore,
    NormalizedGlyph,
    NormalizedRecord,
    NormalizedRepository,
    StyleMetricProfile,
    normalize_processed_glyph,
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
    "GlyphMetricOverride",
    "MetricProfileStore",
    "NormalizedGlyph",
    "NormalizedRecord",
    "NormalizedRepository",
    "ProcessedCapture",
    "ProcessedRecord",
    "ProcessedRepository",
    "ProcessingParameters",
    "StyleMetricProfile",
    "WritingGuides",
    "load_capture_bytes",
    "normalize_processed_glyph",
    "process_sample",
    "serialize_capture",
]
