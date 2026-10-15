"""Shared style metrics and explicit CaptureFrame-to-GlyphFrame normalization."""

from __future__ import annotations

import math
import os
import re
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads
from handwriting_plotter.geometry.bounds import Bounds, curve_bounds
from handwriting_plotter.geometry.curves import Cubic, Line, Point2, Quadratic, Segment, Stroke
from handwriting_plotter.styles.models import (
    CubicModel,
    LineModel,
    PointModel,
    QuadraticModel,
    SegmentModel,
    StrokeModel,
    to_segment,
)

from .models import CaptureSample
from .processing import ProcessedCapture, ProcessedRepository
from .repository import CaptureRepository

MAX_NORMALIZED_BYTES = 32 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class StyleMetricProfile(StrictModel):
    """One vertical calibration shared by every glyph in an editable style."""

    format: Literal["hp-style-metrics"] = "hp-style-metrics"
    schema_version: Literal["1.0"] = "1.0"
    style_id: str = Field(min_length=1, max_length=64)
    revision: int = Field(default=1, ge=1)
    source_frame_width_px: float = Field(gt=0)
    source_frame_height_px: float = Field(gt=0)
    ascender_y_px: float
    x_height_y_px: float
    baseline_y_px: float
    descender_y_px: float
    x_height_gu: float = 1000.0
    default_advance_gu: float = Field(default=900.0, gt=0)
    default_left_bearing_gu: float = Field(default=50.0, ge=0)
    minimum_right_bearing_gu: float = Field(default=50.0, ge=0)
    space_advance_gu: float = Field(default=900.0, gt=0)
    line_gap_gu: float = Field(default=500.0, ge=0)
    supported_x_height_mm: tuple[float, float] = (2.5, 5.0)
    preview_x_height_mm: float = Field(default=3.5, gt=0)

    @field_validator(
        "source_frame_width_px", "source_frame_height_px", "ascender_y_px",
        "x_height_y_px", "baseline_y_px", "descender_y_px", "x_height_gu",
        "default_advance_gu", "default_left_bearing_gu", "minimum_right_bearing_gu",
        "space_advance_gu", "line_gap_gu", "preview_x_height_mm",
    )
    @classmethod
    def finite_values(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("metric value must be finite")
        return value

    @field_validator("supported_x_height_mm")
    @classmethod
    def valid_physical_range(cls, value: tuple[float, float]) -> tuple[float, float]:
        if len(value) != 2 or value[0] <= 0 or value[0] > value[1]:
            raise ValueError("invalid supported x-height range")
        return value

    @model_validator(mode="after")
    def coherent_frame(self) -> StyleMetricProfile:
        if not self.ascender_y_px <= self.x_height_y_px < self.baseline_y_px <= self.descender_y_px:
            raise ValueError("invalid shared guide order")
        if not all(0 <= value <= self.source_frame_height_px for value in (
            self.ascender_y_px, self.x_height_y_px, self.baseline_y_px, self.descender_y_px,
        )):
            raise ValueError("shared guides are outside source frame")
        if abs(self.x_height_gu - 1000.0) > 1e-9:
            raise ValueError("GlyphFrame x-height must equal 1000 gu")
        if not self.supported_x_height_mm[0] <= self.preview_x_height_mm <= self.supported_x_height_mm[1]:
            raise ValueError("preview x-height is outside supported range")
        return self

    @property
    def scale_gu_per_px(self) -> float:
        return self.x_height_gu / (self.baseline_y_px - self.x_height_y_px)

    @property
    def ascender_gu(self) -> float:
        return (self.baseline_y_px - self.ascender_y_px) * self.scale_gu_per_px

    @property
    def descender_gu(self) -> float:
        return (self.baseline_y_px - self.descender_y_px) * self.scale_gu_per_px

    @classmethod
    def from_sample(
        cls,
        style_id: str,
        sample: CaptureSample,
        *,
        preview_x_height_mm: float = 3.5,
    ) -> StyleMetricProfile:
        frame, guides = sample.coordinate_reference, sample.guides
        return cls(
            style_id=style_id,
            source_frame_width_px=frame.width,
            source_frame_height_px=frame.height,
            ascender_y_px=guides.ascender_y,
            x_height_y_px=guides.x_height_y,
            baseline_y_px=guides.baseline_y,
            descender_y_px=guides.descender_y,
            preview_x_height_mm=preview_x_height_mm,
        )


class GlyphMetricOverride(StrictModel):
    variant_id: str = Field(min_length=1, max_length=256)
    advance_gu: float | None = Field(default=None, gt=0)
    left_bearing_gu: float | None = Field(default=None, ge=0)
    minimum_right_bearing_gu: float | None = Field(default=None, ge=0)
    baseline_offset_gu: float = Field(default=0.0, ge=-500.0, le=500.0)

    @field_validator("advance_gu", "left_bearing_gu", "minimum_right_bearing_gu", "baseline_offset_gu")
    @classmethod
    def finite_override(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("metric override must be finite")
        return value


class NormalizedBounds(StrictModel):
    min_x_gu: float
    min_y_gu: float
    max_x_gu: float
    max_y_gu: float

    @model_validator(mode="after")
    def valid_bounds(self) -> NormalizedBounds:
        values = (self.min_x_gu, self.min_y_gu, self.max_x_gu, self.max_y_gu)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("normalized bounds must be finite")
        if self.min_x_gu > self.max_x_gu or self.min_y_gu > self.max_y_gu:
            raise ValueError("invalid normalized bounds ordering")
        return self


class NormalizedGlyph(StrictModel):
    format: Literal["hp-normalized-glyph"] = "hp-normalized-glyph"
    schema_version: Literal["1.0"] = "1.0"
    normalized_id: str = Field(min_length=1, max_length=128)
    source_capture_sha256: str
    source_processed_sha256: str
    source_sample_id: str = Field(min_length=1, max_length=128)
    metric_profile_sha256: str
    metric_profile: StyleMetricProfile
    variant_id: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=256)
    context_tag: Literal["isolated", "initial", "medial", "final"] = "isolated"
    units: Literal["gu"] = "gu"
    strokes: tuple[StrokeModel, ...]
    advance_gu: float = Field(gt=0)
    left_bearing_gu: float = Field(ge=0)
    right_bearing_gu: float = Field(ge=0)
    baseline_offset_gu: float
    bounds: NormalizedBounds
    preview_x_height_mm: float = Field(gt=0)

    @field_validator("source_capture_sha256", "source_processed_sha256", "metric_profile_sha256")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("INVALID_NORMALIZATION_HASH")
        return value

    @model_validator(mode="after")
    def coherent_output(self) -> NormalizedGlyph:
        expected = metric_profile_sha256(self.metric_profile)
        if self.metric_profile_sha256 != expected:
            raise ValueError("METRIC_PROFILE_HASH_MISMATCH")
        if not self.strokes:
            raise ValueError("normalized glyph must contain strokes")
        runtime = self.to_strokes()
        actual = _geometry_bounds(runtime)
        declared = (
            self.bounds.min_x_gu, self.bounds.min_y_gu,
            self.bounds.max_x_gu, self.bounds.max_y_gu,
        )
        measured = (actual.min_x, actual.min_y, actual.max_x, actual.max_y)
        if any(abs(left - right) > 1e-7 for left, right in zip(declared, measured, strict=True)):
            raise ValueError("NORMALIZED_BOUNDS_MISMATCH")
        if abs(self.bounds.min_x_gu - self.left_bearing_gu) > 1e-7:
            raise ValueError("NORMALIZED_LEFT_BEARING_MISMATCH")
        if abs(self.advance_gu - self.bounds.max_x_gu - self.right_bearing_gu) > 1e-7:
            raise ValueError("NORMALIZED_RIGHT_BEARING_MISMATCH")
        if self.advance_gu + 1e-9 < self.bounds.max_x_gu:
            raise ValueError("advance does not contain glyph geometry")
        if self.bounds.min_y_gu < self.metric_profile.descender_gu - 1e-7:
            raise ValueError("glyph exceeds style descender")
        if self.bounds.max_y_gu > self.metric_profile.ascender_gu + 1e-7:
            raise ValueError("glyph exceeds style ascender")
        if tuple(stroke.id for stroke in runtime) != tuple(stroke.id for stroke in self.strokes):
            raise ValueError("normalized stroke order mismatch")
        return self

    def to_strokes(self) -> tuple[Stroke, ...]:
        return tuple(
            Stroke(
                item.id,
                tuple(to_segment(segment) for segment in item.segments),
                item.source_refs,
                item.role,
                item.direction_provenance,
            )
            for item in self.strokes
        )

    def physical_preview_strokes(self) -> tuple[Stroke, ...]:
        scale = self.preview_x_height_mm / 1000.0

        def point(value: Point2) -> Point2:
            return Point2(value.x * scale, -value.y * scale)

        def segment(value: Segment) -> Segment:
            if isinstance(value, Line):
                return Line(point(value.p0), point(value.p1))
            if isinstance(value, Quadratic):
                return Quadratic(point(value.p0), point(value.c1), point(value.p1))
            return Cubic(point(value.p0), point(value.c1), point(value.c2), point(value.p1))

        return tuple(
            Stroke(
                stroke.id,
                tuple(segment(item) for item in stroke.segments),
                stroke.source_refs,
                stroke.role,
                stroke.direction_provenance,
            )
            for stroke in self.to_strokes()
        )


def metric_profile_sha256(profile: StyleMetricProfile) -> str:
    return sha256(canonical_json_bytes(profile.model_dump(mode="json"))).hexdigest()


def _point_model(point: Point2) -> PointModel:
    return PointModel(x=point.x, y=point.y)


def _segment_model(segment: Segment) -> SegmentModel:
    if isinstance(segment, Line):
        return LineModel(kind="line", p0=_point_model(segment.p0), p1=_point_model(segment.p1))
    if isinstance(segment, Quadratic):
        return QuadraticModel(
            kind="quadratic", p0=_point_model(segment.p0), c1=_point_model(segment.c1),
            p1=_point_model(segment.p1),
        )
    return CubicModel(
        kind="cubic", p0=_point_model(segment.p0), c1=_point_model(segment.c1),
        c2=_point_model(segment.c2), p1=_point_model(segment.p1),
    )


def _transform_segment(segment: Segment, scale: float, baseline: float, x_shift: float, y_offset: float) -> Segment:
    def point(value: Point2) -> Point2:
        return Point2(value.x * scale + x_shift, (baseline - value.y) * scale + y_offset)

    if isinstance(segment, Line):
        return Line(point(segment.p0), point(segment.p1))
    if isinstance(segment, Quadratic):
        return Quadratic(point(segment.p0), point(segment.c1), point(segment.p1))
    return Cubic(point(segment.p0), point(segment.c1), point(segment.c2), point(segment.p1))


def _translate_x_segment(segment: Segment, offset: float) -> Segment:
    def point(value: Point2) -> Point2:
        return Point2(value.x + offset, value.y)

    if isinstance(segment, Line):
        return Line(point(segment.p0), point(segment.p1))
    if isinstance(segment, Quadratic):
        return Quadratic(point(segment.p0), point(segment.c1), point(segment.p1))
    return Cubic(point(segment.p0), point(segment.c1), point(segment.c2), point(segment.p1))


def _geometry_bounds(strokes: tuple[Stroke, ...]) -> Bounds:
    parts = [curve_bounds(segment) for stroke in strokes for segment in stroke.segments]
    if not parts:
        raise ValueError("NORMALIZATION_EMPTY_GEOMETRY")
    result = parts[0]
    for item in parts[1:]:
        result = result.union(item)
    return result


def normalize_processed_glyph(
    processed: ProcessedCapture,
    processed_sha256: str,
    raw_sample: CaptureSample,
    profile: StyleMetricProfile,
    *,
    variant_id: str,
    label: str,
    context_tag: Literal["isolated", "initial", "medial", "final"] = "isolated",
    override: GlyphMetricOverride | None = None,
) -> NormalizedGlyph:
    """Apply one shared vertical calibration; never scale from a glyph bbox."""
    if not _SHA256.fullmatch(processed_sha256):
        raise ValueError("INVALID_PROCESSED_HASH")
    if processed.source_sample_id != raw_sample.sample_id:
        raise ValueError("NORMALIZATION_SAMPLE_MISMATCH")
    if label != raw_sample.label:
        raise ValueError("NORMALIZATION_LABEL_MISMATCH")
    if processed.source_capture_sha256 == processed_sha256:
        raise ValueError("NORMALIZATION_SOURCE_HASH_COLLISION")
    frame = raw_sample.coordinate_reference
    if (
        abs(frame.width - profile.source_frame_width_px) > 1e-7
        or abs(frame.height - profile.source_frame_height_px) > 1e-7
        or abs(processed.frame_width - frame.width) > 1e-7
        or abs(processed.frame_height - frame.height) > 1e-7
    ):
        raise ValueError("METRIC_FRAME_MISMATCH")
    if override is not None and override.variant_id != variant_id:
        raise ValueError("METRIC_OVERRIDE_VARIANT_MISMATCH")

    scale = profile.scale_gu_per_px
    baseline_offset = override.baseline_offset_gu if override else 0.0
    initial = tuple(
        Stroke(
            stroke.id,
            tuple(_transform_segment(segment, scale, profile.baseline_y_px, 0.0, baseline_offset)
                  for segment in stroke.segments),
            stroke.source_refs,
            stroke.role,
            stroke.direction_provenance,
        )
        for stroke in processed.to_strokes()
    )
    initial_bounds = _geometry_bounds(initial)
    left_bearing = (
        override.left_bearing_gu
        if override is not None and override.left_bearing_gu is not None
        else profile.default_left_bearing_gu
    )
    x_shift = left_bearing - initial_bounds.min_x
    normalized = tuple(
        Stroke(
            stroke.id,
            tuple(_translate_x_segment(segment, x_shift) for segment in stroke.segments),
            stroke.source_refs,
            stroke.role,
            stroke.direction_provenance,
        )
        for stroke in initial
    )
    bounds = _geometry_bounds(normalized)
    minimum_right = (
        override.minimum_right_bearing_gu
        if override is not None and override.minimum_right_bearing_gu is not None
        else profile.minimum_right_bearing_gu
    )
    required_advance = bounds.max_x + minimum_right
    requested_advance = (
        override.advance_gu
        if override is not None and override.advance_gu is not None
        else profile.default_advance_gu
    )
    if requested_advance + 1e-9 < required_advance:
        raise ValueError("ADVANCE_TOO_SMALL_FOR_GLYPH")
    if bounds.min_y < profile.descender_gu - 1e-7 or bounds.max_y > profile.ascender_gu + 1e-7:
        raise ValueError("GLYPH_OUTSIDE_STYLE_VERTICAL_ENVELOPE")

    profile_hash = metric_profile_sha256(profile)
    identity = canonical_json_bytes({
        "source_processed_sha256": processed_sha256,
        "metric_profile_sha256": profile_hash,
        "variant_id": variant_id,
        "label": label,
        "context_tag": context_tag,
        "override": None if override is None else override.model_dump(mode="json"),
    })
    return NormalizedGlyph(
        normalized_id=f"normalized-{sha256(identity).hexdigest()[:24]}",
        source_capture_sha256=processed.source_capture_sha256,
        source_processed_sha256=processed_sha256,
        source_sample_id=processed.source_sample_id,
        metric_profile_sha256=profile_hash,
        metric_profile=profile,
        variant_id=variant_id,
        label=label,
        context_tag=context_tag,
        strokes=tuple(StrokeModel(
            id=stroke.id,
            segments=tuple(_segment_model(segment) for segment in stroke.segments),
            source_refs=stroke.source_refs,
            role=stroke.role,
            direction_provenance=stroke.direction_provenance,
        ) for stroke in normalized),
        advance_gu=requested_advance,
        left_bearing_gu=left_bearing,
        right_bearing_gu=requested_advance - bounds.max_x,
        baseline_offset_gu=baseline_offset,
        bounds=NormalizedBounds(
            min_x_gu=bounds.min_x, min_y_gu=bounds.min_y,
            max_x_gu=bounds.max_x, max_y_gu=bounds.max_y,
        ),
        preview_x_height_mm=profile.preview_x_height_mm,
    )


def serialize_normalized(value: NormalizedGlyph) -> bytes:
    return canonical_json_bytes(value.model_dump(mode="json"))


def load_normalized_bytes(data: bytes) -> NormalizedGlyph:
    if len(data) > MAX_NORMALIZED_BYTES:
        raise ValueError("NORMALIZED_FILE_TOO_LARGE")
    decoded = strict_json_loads(data)
    if not isinstance(decoded, dict):
        raise ValueError("NORMALIZED_ROOT_MUST_BE_OBJECT")
    if decoded.get("format") != "hp-normalized-glyph":
        raise ValueError("UNSUPPORTED_NORMALIZED_FORMAT")
    if decoded.get("schema_version") != "1.0":
        raise ValueError("UNSUPPORTED_NORMALIZED_SCHEMA")
    return NormalizedGlyph.model_validate_json(canonical_json_bytes(decoded), strict=True)


class MetricProfileStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, style_id: str) -> Path:
        if not _SAFE_ID.fullmatch(style_id):
            raise ValueError("INVALID_METRIC_STYLE_ID")
        return self.root / "drafts" / "metrics" / f"{style_id}.json"

    def save(self, profile: StyleMetricProfile) -> Path:
        path = self.path_for(profile.style_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            current = self.load(profile.style_id)
            if current == profile:
                return path
            if profile.revision != current.revision + 1:
                raise ValueError("METRIC_PROFILE_REVISION_CONFLICT")
        _atomic_replace(path, canonical_json_bytes(profile.model_dump(mode="json")), ".metrics-")
        return path

    def load(self, style_id: str) -> StyleMetricProfile:
        decoded = strict_json_loads(self.path_for(style_id).read_bytes())
        if not isinstance(decoded, dict) or decoded.get("format") != "hp-style-metrics":
            raise ValueError("UNSUPPORTED_METRIC_PROFILE_FORMAT")
        if decoded.get("schema_version") != "1.0":
            raise ValueError("UNSUPPORTED_METRIC_PROFILE_SCHEMA")
        return StyleMetricProfile.model_validate_json(canonical_json_bytes(decoded), strict=True)


@dataclass(frozen=True, slots=True)
class NormalizedRecord:
    sha256: str
    path: Path
    glyph: NormalizedGlyph


class NormalizedRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, processed_hash: str, digest: str) -> Path:
        if not _SHA256.fullmatch(processed_hash) or not _SHA256.fullmatch(digest):
            raise ValueError("INVALID_NORMALIZED_HASH")
        return self.root / "normalized" / processed_hash[:2] / processed_hash / f"{digest}.hp-normalized.json"

    def store(self, glyph: NormalizedGlyph) -> NormalizedRecord:
        self._verify_sources(glyph)
        content = serialize_normalized(glyph)
        if len(content) > MAX_NORMALIZED_BYTES:
            raise ValueError("NORMALIZED_FILE_TOO_LARGE")
        digest = sha256(content).hexdigest()
        path = self.path_for(glyph.source_processed_sha256, digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = path.read_bytes()
            if sha256(existing).hexdigest() != digest or existing != content:
                raise ValueError("NORMALIZED_HASH_MISMATCH")
        else:
            _atomic_create(path, content, ".normalized-")
        return NormalizedRecord(digest, path, glyph)

    def load(self, processed_hash: str, digest: str) -> NormalizedGlyph:
        path = self.path_for(processed_hash, digest)
        content = path.read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("NORMALIZED_HASH_MISMATCH")
        glyph = load_normalized_bytes(content)
        if glyph.source_processed_sha256 != processed_hash:
            raise ValueError("NORMALIZED_SOURCE_MISMATCH")
        self._verify_sources(glyph)
        return glyph

    def list_for_processed(self, processed_hash: str) -> tuple[NormalizedRecord, ...]:
        if not _SHA256.fullmatch(processed_hash):
            raise ValueError("INVALID_PROCESSED_HASH")
        folder = self.root / "normalized" / processed_hash[:2] / processed_hash
        if not folder.is_dir():
            return ()
        records = []
        for path in sorted(folder.glob("*.hp-normalized.json"), key=lambda item: item.stat().st_mtime_ns):
            digest = path.name.removesuffix(".hp-normalized.json")
            records.append(NormalizedRecord(digest, path, self.load(processed_hash, digest)))
        return tuple(records)

    def _verify_sources(self, glyph: NormalizedGlyph) -> None:
        raw = CaptureRepository(self.root).load(glyph.source_capture_sha256)
        sample = next((item for item in raw.samples if item.sample_id == glyph.source_sample_id), None)
        if sample is None:
            raise ValueError("NORMALIZED_SOURCE_MISMATCH")
        if glyph.label != sample.label:
            raise ValueError("NORMALIZED_SOURCE_MISMATCH")
        processed = ProcessedRepository(self.root).load(
            glyph.source_capture_sha256, glyph.source_processed_sha256
        )
        if processed.source_sample_id != sample.sample_id:
            raise ValueError("NORMALIZED_SOURCE_MISMATCH")


def _atomic_replace(path: Path, content: bytes, prefix: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=path.parent)
    staging = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, path)
        _sync_directory(path.parent)
    finally:
        staging.unlink(missing_ok=True)


def _atomic_create(path: Path, content: bytes, prefix: str) -> None:
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=path.parent)
    staging = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(staging, path)
        except FileExistsError:
            existing = path.read_bytes()
            if existing != content:
                raise ValueError("NORMALIZED_HASH_MISMATCH")
        _sync_directory(path.parent)
    finally:
        staging.unlink(missing_ok=True)


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
