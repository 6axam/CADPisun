"""Canonical, lossless raw online-handwriting data model."""

from __future__ import annotations

import math
import unicodedata
from datetime import datetime, timezone
from typing import Literal

import regex
from pydantic import Field, field_validator, model_validator

from handwriting_plotter.domain.models import StrictModel

MAX_POINTS_PER_STROKE = 250_000
MAX_POINTS_PER_SESSION = 1_000_000
MAX_SAMPLES_PER_SESSION = 100_000

Identifier = str
PointerType = Literal["mouse", "pen", "eraser", "touch", "unknown"]


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _utc_timestamp(value: str, name: str) -> str:
    if not value.endswith("Z"):
        raise ValueError(f"{name} must be an RFC 3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{name} must be an RFC 3339 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{name} must be UTC")
    return value


class CoordinateReference(StrictModel):
    """Fixed raw-canvas frame; resizing creates a different reference."""

    unit: Literal["logical_px"] = "logical_px"
    origin: Literal["top_left"] = "top_left"
    x_axis: Literal["right"] = "right"
    y_axis: Literal["down"] = "down"
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    device_pixel_ratio: float = Field(default=1.0, gt=0)

    @field_validator("width", "height", "device_pixel_ratio")
    @classmethod
    def finite_dimensions(cls, value: float, info) -> float:  # noqa: ANN001
        return _finite(value, info.field_name)


class WritingGuides(StrictModel):
    ascender_y: float
    x_height_y: float
    baseline_y: float
    descender_y: float

    @field_validator("ascender_y", "x_height_y", "baseline_y", "descender_y")
    @classmethod
    def finite_guides(cls, value: float, info) -> float:  # noqa: ANN001
        return _finite(value, info.field_name)

    @model_validator(mode="after")
    def ordered(self) -> WritingGuides:
        if not self.ascender_y <= self.x_height_y < self.baseline_y <= self.descender_y:
            raise ValueError("invalid writing guide order")
        return self


class DeviceCapabilities(StrictModel):
    pointer_types: tuple[PointerType, ...]
    pressure: bool = False
    tilt: bool = False
    rotation: bool = False
    maximum_touch_points: int | None = Field(default=None, ge=1)
    device_name: str | None = Field(default=None, max_length=256)
    system_id: str | None = Field(default=None, max_length=256)

    @field_validator("pointer_types")
    @classmethod
    def pointer_types_unique(cls, value: tuple[PointerType, ...]) -> tuple[PointerType, ...]:
        if not value:
            raise ValueError("at least one pointer type is required")
        if len(value) != len(set(value)):
            raise ValueError("duplicate pointer type")
        return value


class CaptureProvenance(StrictModel):
    source: Literal["online_capture", "synthetic_fixture", "imported"]
    captured_at_utc: str
    timing_source: Literal["monotonic", "none"]
    application_version: str = Field(min_length=1, max_length=128)
    author_id: str | None = Field(default=None, max_length=256)
    source_note: str | None = Field(default=None, max_length=2048)

    @field_validator("captured_at_utc")
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        return _utc_timestamp(value, "captured_at_utc")


class CapturePoint(StrictModel):
    point_id: Identifier = Field(min_length=1, max_length=128)
    event: Literal["down", "move", "up", "cancel"]
    x: float
    y: float
    elapsed_s: float | None = Field(default=None, ge=0)
    pressure: float | None = Field(default=None, ge=0, le=1)
    pointer_type: PointerType

    @field_validator("x", "y")
    @classmethod
    def finite_position(cls, value: float, info) -> float:  # noqa: ANN001
        return _finite(value, info.field_name)

    @field_validator("elapsed_s", "pressure")
    @classmethod
    def finite_optional(cls, value: float | None, info) -> float | None:  # noqa: ANN001
        return None if value is None else _finite(value, info.field_name)

    @model_validator(mode="after")
    def honest_mouse_pressure(self) -> CapturePoint:
        if self.pointer_type == "mouse" and self.pressure is not None:
            raise ValueError("mouse pressure requires an actual pressure capability")
        return self


class CaptureStroke(StrictModel):
    stroke_id: Identifier = Field(min_length=1, max_length=128)
    points: tuple[CapturePoint, ...]
    termination: Literal["completed", "cancelled", "interrupted"] = "completed"

    @model_validator(mode="after")
    def validate_sequence(self) -> CaptureStroke:
        if len(self.points) < 2:
            raise ValueError("stroke must contain pointer-down and a terminal point")
        if len(self.points) > MAX_POINTS_PER_STROKE:
            raise ValueError("stroke has too many points")
        ids = [point.point_id for point in self.points]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate point id")
        if self.points[0].event != "down":
            raise ValueError("stroke must start with pointer-down")
        expected_end = "up" if self.termination == "completed" else (
            "cancel" if self.termination == "cancelled" else "move"
        )
        if self.points[-1].event != expected_end:
            raise ValueError(f"stroke must end with {expected_end}")
        if any(point.event != "move" for point in self.points[1:-1]):
            raise ValueError("stroke interior points must be pointer moves")
        times = [point.elapsed_s for point in self.points]
        if any(value is None for value in times) and any(value is not None for value in times):
            raise ValueError("timing must be recorded for all points or no points")
        known_times = [value for value in times if value is not None]
        if any(current < previous for previous, current in zip(known_times, known_times[1:], strict=False)):
            raise ValueError("point times must be monotonic")
        return self


class CaptureSample(StrictModel):
    sample_id: Identifier = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=256)
    classification: Literal["glyph", "sequence"]
    coordinate_reference: CoordinateReference
    guides: WritingGuides
    provenance: CaptureProvenance
    strokes: tuple[CaptureStroke, ...]

    @field_validator("label")
    @classmethod
    def normalized_label(cls, value: str) -> str:
        if unicodedata.normalize("NFC", value) != value:
            raise ValueError("sample label must be NFC normalized")
        if any(char.isspace() for char in value):
            raise ValueError("sample label must not contain whitespace")
        return value

    @model_validator(mode="after")
    def validate_sample(self) -> CaptureSample:
        grapheme_count = len(regex.findall(r"\X", self.label))
        if self.classification == "glyph" and grapheme_count != 1:
            raise ValueError("glyph classification requires exactly one grapheme")
        if self.classification == "sequence" and not 2 <= grapheme_count <= 64:
            raise ValueError("sequence classification requires 2 to 64 graphemes")
        if not self.strokes:
            raise ValueError("sample must contain at least one stroke")
        stroke_ids = [stroke.stroke_id for stroke in self.strokes]
        if len(stroke_ids) != len(set(stroke_ids)):
            raise ValueError("duplicate stroke id")
        height = self.coordinate_reference.height
        if not all(0 <= value <= height for value in (
            self.guides.ascender_y, self.guides.x_height_y,
            self.guides.baseline_y, self.guides.descender_y,
        )):
            raise ValueError("writing guides are outside capture canvas")
        all_points = [point for stroke in self.strokes for point in stroke.points]
        width = self.coordinate_reference.width
        if any(not 0 <= point.x <= width or not 0 <= point.y <= height for point in all_points):
            raise ValueError("point is outside capture canvas")
        has_times = [point.elapsed_s is not None for point in all_points]
        if self.provenance.timing_source == "monotonic" and not all(has_times):
            raise ValueError("monotonic timing source requires all point times")
        if self.provenance.timing_source == "none" and any(has_times):
            raise ValueError("timing source none requires absent point times")
        timed = [point.elapsed_s for point in all_points if point.elapsed_s is not None]
        if any(current < previous for previous, current in zip(timed, timed[1:], strict=False)):
            raise ValueError("sample point times must be monotonic")
        return self


class CaptureSession(StrictModel):
    format: Literal["hp-capture"] = "hp-capture"
    schema_version: Literal["1.0"] = "1.0"
    session_id: Identifier = Field(min_length=1, max_length=128)
    created_at_utc: str
    device: DeviceCapabilities
    samples: tuple[CaptureSample, ...]
    extensions: dict[str, object] = Field(default_factory=dict)

    @field_validator("created_at_utc")
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        return _utc_timestamp(value, "created_at_utc")

    @field_validator("extensions")
    @classmethod
    def namespaced_extensions(cls, value: dict[str, object]) -> dict[str, object]:
        if any("." not in key for key in value):
            raise ValueError("extension keys must be namespaced")
        return value

    @model_validator(mode="after")
    def validate_session(self) -> CaptureSession:
        if not self.samples:
            raise ValueError("capture session must contain at least one sample")
        if len(self.samples) > MAX_SAMPLES_PER_SESSION:
            raise ValueError("capture session has too many samples")
        sample_ids = [sample.sample_id for sample in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("duplicate sample id")
        stroke_ids: list[str] = []
        point_ids: list[str] = []
        pointer_types: set[str] = set()
        has_pressure = False
        for sample in self.samples:
            for stroke in sample.strokes:
                stroke_ids.append(stroke.stroke_id)
                for point in stroke.points:
                    point_ids.append(point.point_id)
                    pointer_types.add(point.pointer_type)
                    has_pressure |= point.pressure is not None
        if len(stroke_ids) != len(set(stroke_ids)):
            raise ValueError("duplicate stroke id in session")
        if len(point_ids) != len(set(point_ids)):
            raise ValueError("duplicate point id in session")
        if len(point_ids) > MAX_POINTS_PER_SESSION:
            raise ValueError("capture session has too many points")
        if not pointer_types <= set(self.device.pointer_types):
            raise ValueError("point pointer type is absent from device capabilities")
        if has_pressure and not self.device.pressure:
            raise ValueError("captured pressure is absent from device capabilities")
        return self
