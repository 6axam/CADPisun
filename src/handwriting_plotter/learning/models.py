"""Versioned models for immutable photographed-handwriting sources."""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _safe_relative(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("PHOTO_PATH_MUST_BE_SAFE_RELATIVE")
    return path.as_posix()


def _utc_timestamp(value: str, name: str) -> str:
    if not value.endswith("Z"):
        raise ValueError(f"{name} must use UTC Z notation")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError(f"{name} must be UTC")
    return value


class ConfidenceValue(StrictModel):
    value: float = Field(ge=0.0, le=1.0)
    origin: Literal["heuristic", "model", "calibrated", "human"]
    meaning: str = Field(min_length=1, max_length=256)
    calibration_ref: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def calibrated_values_have_reference(self) -> ConfidenceValue:
        if self.origin == "calibrated" and self.calibration_ref is None:
            raise ValueError("CALIBRATED_CONFIDENCE_REQUIRES_REFERENCE")
        return self


class PixelFrame(StrictModel):
    frame_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    origin: Literal["top_left"] = "top_left"
    x_direction: Literal["right"] = "right"
    y_direction: Literal["down"] = "down"
    units: Literal["px"] = "px"


class PageDimensions(StrictModel):
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    width_mm: float | None = Field(default=None, gt=0.0)
    height_mm: float | None = Field(default=None, gt=0.0)
    physical_scale_source: Literal["unknown", "user_entered", "verified_reference"] = "unknown"

    @model_validator(mode="after")
    def physical_dimensions_are_explicit(self) -> PageDimensions:
        if (self.width_mm is None) != (self.height_mm is None):
            raise ValueError("PHYSICAL_PAGE_DIMENSIONS_MUST_BE_PAIRED")
        if self.physical_scale_source == "unknown" and self.width_mm is not None:
            raise ValueError("UNKNOWN_SCALE_CANNOT_HAVE_MM_DIMENSIONS")
        if self.physical_scale_source != "unknown" and self.width_mm is None:
            raise ValueError("KNOWN_SCALE_REQUIRES_MM_DIMENSIONS")
        return self


class PixelPoint(StrictModel):
    x: float = Field(ge=0.0)
    y: float = Field(ge=0.0)

    @field_validator("x", "y")
    @classmethod
    def finite_coordinate(cls, value: float) -> float:
        return _finite(value, "pixel coordinate")


class ImageTransform(StrictModel):
    transform_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    kind: Literal["orientation", "rotation", "crop", "homography", "deskew", "other"]
    algorithm_id: str = Field(min_length=1, max_length=256)
    input_sha256: str
    output_sha256: str
    input_frame_id: str = Field(min_length=1, max_length=128)
    output_frame_id: str = Field(min_length=1, max_length=128)
    forward_matrix: tuple[float, float, float, float, float, float, float, float, float]
    inverse_matrix: tuple[float, float, float, float, float, float, float, float, float]
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_sha256", "output_sha256")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("INVALID_PHOTO_HASH")
        return value

    @field_validator("forward_matrix", "inverse_matrix")
    @classmethod
    def finite_matrix(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if not all(math.isfinite(item) for item in value):
            raise ValueError("TRANSFORM_MATRIX_MUST_BE_FINITE")
        return value

    @field_validator("parameters")
    @classmethod
    def bounded_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 64 or any(len(key) > 128 for key in value):
            raise ValueError("TRANSFORM_PARAMETERS_TOO_LARGE")
        try:
            encoded = canonical_json_bytes(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("TRANSFORM_PARAMETERS_MUST_BE_CANONICAL_JSON") from exc
        if len(encoded) > 64 * 1024:
            raise ValueError("TRANSFORM_PARAMETERS_TOO_LARGE")
        return value

    @model_validator(mode="after")
    def matrices_are_inverses(self) -> ImageTransform:
        a = self.forward_matrix
        b = self.inverse_matrix
        product = tuple(sum(a[row * 3 + k] * b[k * 3 + col] for k in range(3))
                        for row in range(3) for col in range(3))
        scale = product[8]
        if abs(scale) < 1e-12:
            raise ValueError("TRANSFORM_MATRIX_NOT_INVERTIBLE")
        normalized = tuple(item / scale for item in product)
        identity = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
        if any(abs(left - right) > 1e-6 for left, right in zip(normalized, identity, strict=True)):
            raise ValueError("TRANSFORM_INVERSE_MISMATCH")
        return self


class PhotoRegion(StrictModel):
    region_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    kind: Literal["page", "text", "header", "paragraph", "line", "word", "grapheme", "ligature", "other"]
    frame_id: str = Field(min_length=1, max_length=128)
    polygon: tuple[PixelPoint, ...] = Field(min_length=3, max_length=4096)
    parent_id: str | None = Field(default=None, min_length=1, max_length=128)
    confidence: ConfidenceValue | None = None

    @model_validator(mode="after")
    def polygon_has_area(self) -> PhotoRegion:
        coordinates = [(item.x, item.y) for item in self.polygon]
        if len(set(coordinates)) < 3:
            raise ValueError("REGION_POLYGON_REQUIRES_DISTINCT_POINTS")
        area_twice = sum(
            left[0] * right[1] - right[0] * left[1]
            for left, right in zip(coordinates, (*coordinates[1:], coordinates[0]), strict=True)
        )
        if abs(area_twice) <= 1e-9:
            raise ValueError("REGION_POLYGON_HAS_NO_AREA")
        return self


class RulingEstimate(StrictModel):
    frame_id: str = Field(min_length=1, max_length=128)
    classification: Literal["unknown", "blank", "squared", "ruled", "mixed"] = "unknown"
    status: Literal["not_evaluated", "proposed", "confirmed", "overridden"] = "not_evaluated"
    method: str = Field(default="not_evaluated", min_length=1, max_length=256)
    confidence: ConfidenceValue | None = None
    cell_pitch_x_px: float | None = Field(default=None, gt=0.0)
    cell_pitch_y_px: float | None = Field(default=None, gt=0.0)
    ruling_pitch_px: float | None = Field(default=None, gt=0.0)
    origin_x_px: float | None = None
    origin_y_px: float | None = None
    horizontal_angle_deg: float | None = Field(default=None, ge=-45.0, le=45.0)
    vertical_angle_deg: float | None = Field(default=None, ge=45.0, le=135.0)
    horizontal_residual_px: float | None = Field(default=None, ge=0.0)
    vertical_residual_px: float | None = Field(default=None, ge=0.0)

    @field_validator(
        "cell_pitch_x_px",
        "cell_pitch_y_px",
        "ruling_pitch_px",
        "origin_x_px",
        "origin_y_px",
        "horizontal_angle_deg",
        "vertical_angle_deg",
        "horizontal_residual_px",
        "vertical_residual_px",
    )
    @classmethod
    def finite_optional(cls, value: float | None) -> float | None:
        return None if value is None else _finite(value, "ruling geometry")

    @model_validator(mode="after")
    def unevaluated_is_unknown(self) -> RulingEstimate:
        geometry = (
            self.cell_pitch_x_px,
            self.cell_pitch_y_px,
            self.ruling_pitch_px,
            self.origin_x_px,
            self.origin_y_px,
            self.horizontal_angle_deg,
            self.vertical_angle_deg,
            self.horizontal_residual_px,
            self.vertical_residual_px,
        )
        if self.status == "not_evaluated" and (
            self.classification != "unknown" or self.confidence is not None or any(item is not None for item in geometry)
        ):
            raise ValueError("UNEVALUATED_RULING_MUST_BE_EMPTY")
        if any(item is not None for item in geometry) and self.classification not in {"squared", "ruled"}:
            raise ValueError("RULING_GEOMETRY_REQUIRES_RULED_OR_SQUARED_PAPER")
        if self.classification == "ruled" and any(
            item is not None
            for item in (self.cell_pitch_x_px, self.cell_pitch_y_px, self.origin_x_px, self.vertical_angle_deg, self.vertical_residual_px)
        ):
            raise ValueError("RULED_PAPER_CANNOT_DECLARE_GRID_GEOMETRY")
        return self


class PhysicalScaleCalibration(StrictModel):
    """Explicit pixel-to-millimetre scale for one immutable photo frame."""

    frame_id: str = Field(min_length=1, max_length=128)
    source: Literal["user_entered", "verified_reference", "notebook_cell_preset"]
    method: str = Field(min_length=1, max_length=256)
    mm_per_px_x: float | None = Field(default=None, gt=0.0)
    mm_per_px_y: float | None = Field(default=None, gt=0.0)
    uncertainty_mm_per_px_x: float | None = Field(default=None, ge=0.0)
    uncertainty_mm_per_px_y: float | None = Field(default=None, ge=0.0)
    reference_pitch_mm: float | None = Field(default=None, gt=0.0)

    @field_validator(
        "mm_per_px_x",
        "mm_per_px_y",
        "uncertainty_mm_per_px_x",
        "uncertainty_mm_per_px_y",
        "reference_pitch_mm",
    )
    @classmethod
    def finite_optional_scale(cls, value: float | None) -> float | None:
        return None if value is None else _finite(value, "physical scale")

    @model_validator(mode="after")
    def scale_is_explicit(self) -> PhysicalScaleCalibration:
        if self.mm_per_px_x is None and self.mm_per_px_y is None:
            raise ValueError("PHYSICAL_SCALE_REQUIRES_AXIS")
        if self.uncertainty_mm_per_px_x is not None and self.mm_per_px_x is None:
            raise ValueError("SCALE_UNCERTAINTY_REQUIRES_X_SCALE")
        if self.uncertainty_mm_per_px_y is not None and self.mm_per_px_y is None:
            raise ValueError("SCALE_UNCERTAINTY_REQUIRES_Y_SCALE")
        if self.source == "notebook_cell_preset" and self.reference_pitch_mm != 5.0:
            raise ValueError("NOTEBOOK_CELL_PRESET_REQUIRES_5_MM")
        return self


class PhotoImportMetadata(StrictModel):
    original_filename: str = Field(min_length=1, max_length=512)
    imported_at_utc: str
    application_version: str = Field(min_length=1, max_length=64)
    source_kind: Literal["camera_photo", "scan", "image_file", "unknown"] = "unknown"
    detected_format: str = Field(pattern=r"^[a-z0-9][a-z0-9.+-]{0,31}$")
    media_type: str = Field(pattern=r"^image/[a-z0-9][a-z0-9.+-]{0,63}$")
    encoded_bytes: int = Field(gt=0)
    decoder_id: str = Field(min_length=1, max_length=128)
    decoder_version: str = Field(min_length=1, max_length=128)
    embedded_orientation: Literal[
        "none", "mirror_horizontal", "flip_vertical", "rotate_180", "rotate_90",
        "mirror_horizontal_rotate_90", "flip_vertical_rotate_90", "rotate_270",
    ] = "none"
    rights_status: Literal["unknown", "private_user_material", "authorized"] = "unknown"
    consent_ref: str | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("original_filename")
    @classmethod
    def basename_only(cls, value: str) -> str:
        if "\x00" in value or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("ORIGINAL_FILENAME_MUST_BE_BASENAME")
        return value

    @field_validator("imported_at_utc")
    @classmethod
    def valid_import_time(cls, value: str) -> str:
        return _utc_timestamp(value, "imported_at_utc")

    @model_validator(mode="after")
    def authorized_material_has_reference(self) -> PhotoImportMetadata:
        if self.rights_status == "authorized" and self.consent_ref is None:
            raise ValueError("AUTHORIZED_PHOTO_REQUIRES_CONSENT_REFERENCE")
        return self


class NotebookPhoto(StrictModel):
    format: Literal["hp-notebook-photo"] = "hp-notebook-photo"
    schema_version: Literal["1.0"] = "1.0"
    source_id: str
    original_sha256: str
    original_relative_path: str
    metadata: PhotoImportMetadata
    page_dimensions: PageDimensions
    frames: tuple[PixelFrame, ...]
    transforms: tuple[ImageTransform, ...] = ()
    regions: tuple[PhotoRegion, ...] = ()
    ruling: RulingEstimate
    calibration: PhysicalScaleCalibration | None = None

    @field_validator("source_id")
    @classmethod
    def safe_source_id(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("INVALID_PHOTO_SOURCE_ID")
        return value

    @field_validator("original_sha256")
    @classmethod
    def valid_original_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("INVALID_PHOTO_HASH")
        return value

    @field_validator("original_relative_path")
    @classmethod
    def safe_original_path(cls, value: str) -> str:
        return _safe_relative(value)

    @model_validator(mode="after")
    def references_are_consistent(self) -> NotebookPhoto:
        if not self.frames:
            raise ValueError("PHOTO_REQUIRES_PIXEL_FRAME")
        frame_ids = [item.frame_id for item in self.frames]
        if len(frame_ids) != len(set(frame_ids)):
            raise ValueError("DUPLICATE_PIXEL_FRAME")
        frames = {item.frame_id: item for item in self.frames}
        source_frame = self.frames[0]
        if (source_frame.width_px, source_frame.height_px) != (
            self.page_dimensions.width_px, self.page_dimensions.height_px,
        ):
            raise ValueError("SOURCE_FRAME_DIMENSIONS_MISMATCH")

        transform_ids = [item.transform_id for item in self.transforms]
        if len(transform_ids) != len(set(transform_ids)):
            raise ValueError("DUPLICATE_IMAGE_TRANSFORM")
        for item in self.transforms:
            if item.input_frame_id not in frames or item.output_frame_id not in frames:
                raise ValueError("TRANSFORM_FRAME_NOT_FOUND")

        region_ids = [item.region_id for item in self.regions]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("DUPLICATE_PHOTO_REGION")
        region_set = set(region_ids)
        parents: dict[str, str] = {}
        for item in self.regions:
            frame = frames.get(item.frame_id)
            if frame is None:
                raise ValueError("REGION_FRAME_NOT_FOUND")
            if item.parent_id is not None:
                if item.parent_id == item.region_id or item.parent_id not in region_set:
                    raise ValueError("INVALID_REGION_PARENT")
                parents[item.region_id] = item.parent_id
            if any(point.x > frame.width_px or point.y > frame.height_px for point in item.polygon):
                raise ValueError("REGION_OUTSIDE_PIXEL_FRAME")
        for region_id in region_ids:
            seen: set[str] = set()
            cursor = region_id
            while cursor in parents:
                if cursor in seen:
                    raise ValueError("REGION_PARENT_CYCLE")
                seen.add(cursor)
                cursor = parents[cursor]
        if self.ruling.frame_id not in frames:
            raise ValueError("RULING_FRAME_NOT_FOUND")
        if self.calibration is not None and self.calibration.frame_id not in frames:
            raise ValueError("CALIBRATION_FRAME_NOT_FOUND")
        return self
