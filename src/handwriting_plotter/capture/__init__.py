"""Strict online-handwriting capture models and immutable persistence."""

from .annotation import (
    AnnotationStore,
    GlyphAnnotation,
    PairJoinPreview,
    create_anchor_annotation,
    preview_join,
)

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
    "AnnotationStore",
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
    "GlyphAnnotation",
    "MetricProfileStore",
    "NormalizedGlyph",
    "NormalizedRecord",
    "NormalizedRepository",
    "PairJoinPreview",
    "ProcessedCapture",
    "ProcessedRecord",
    "ProcessedRepository",
    "ProcessingParameters",
    "StyleMetricProfile",
    "WritingGuides",
    "load_capture_bytes",
    "create_anchor_annotation",
    "normalize_processed_glyph",
    "process_sample",
    "preview_join",
    "serialize_capture",
]
