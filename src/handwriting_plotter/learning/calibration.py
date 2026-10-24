"""Explicit pixel, ruling-relative, and physical-scale conversions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from handwriting_plotter.learning.models import (
    NotebookPhoto,
    PhysicalScaleCalibration,
    PixelPoint,
    RulingEstimate,
)
from handwriting_plotter.learning.repository import PhotoRecord, PhotoRepository


@dataclass(frozen=True, slots=True)
class RulingRelativePosition:
    """Position in notebook cell/rule units; unavailable axes stay ``None``."""

    x_cells: float | None
    y_rules: float


@dataclass(frozen=True, slots=True)
class MetricPosition:
    """Physical coordinates; an absent axis has no calibrated millimetre value."""

    x_mm: float | None
    y_mm: float | None


def calibration_from_ruling_pitch(
    ruling: RulingEstimate,
    *,
    pitch_mm: float = 5.0,
    source: Literal["user_entered", "notebook_cell_preset"] = "notebook_cell_preset",
) -> PhysicalScaleCalibration:
    """Calibrate only axes supported by measured ruling geometry.

    The default is deliberately an explicit 5 mm notebook-cell preset. It never
    runs as part of detection, so a pixel pitch remains physically unknown until
    this function is called by the user.
    """

    if pitch_mm <= 0.0 or not math.isfinite(pitch_mm):
        raise ValueError("INVALID_REFERENCE_PITCH_MM")
    if ruling.classification == "squared":
        if ruling.cell_pitch_x_px is None or ruling.cell_pitch_y_px is None:
            raise ValueError("GRID_GEOMETRY_REQUIRED_FOR_CALIBRATION")
        return PhysicalScaleCalibration(
            frame_id=ruling.frame_id,
            source=source,
            method="notebook-cell-preset/1" if source == "notebook_cell_preset" else "manual-cell-pitch/1",
            mm_per_px_x=pitch_mm / ruling.cell_pitch_x_px,
            mm_per_px_y=pitch_mm / ruling.cell_pitch_y_px,
            reference_pitch_mm=pitch_mm,
        )
    if ruling.classification == "ruled":
        if ruling.ruling_pitch_px is None:
            raise ValueError("RULING_GEOMETRY_REQUIRED_FOR_CALIBRATION")
        return PhysicalScaleCalibration(
            frame_id=ruling.frame_id,
            source=source,
            method="notebook-rule-preset/1" if source == "notebook_cell_preset" else "manual-rule-pitch/1",
            mm_per_px_y=pitch_mm / ruling.ruling_pitch_px,
            reference_pitch_mm=pitch_mm,
        )
    raise ValueError("RULING_GEOMETRY_NOT_APPLICABLE")


def ruling_pixel_to_relative(
    ruling: RulingEstimate, *, frame_id: str, point: PixelPoint
) -> RulingRelativePosition:
    """Map a pixel to line/cell units without requiring a physical calibration."""

    if ruling.frame_id != frame_id:
        raise ValueError("RULING_FRAME_MISMATCH")
    horizontal_coordinate = _normal_coordinate(
        point, ruling.horizontal_angle_deg, vertical=False
    )
    if ruling.classification == "ruled":
        if ruling.ruling_pitch_px is None or ruling.origin_y_px is None:
            raise ValueError("RULING_GEOMETRY_REQUIRED")
        return RulingRelativePosition(
            x_cells=None,
            y_rules=(horizontal_coordinate - ruling.origin_y_px) / ruling.ruling_pitch_px,
        )
    if ruling.classification == "squared":
        if (
            ruling.cell_pitch_x_px is None
            or ruling.cell_pitch_y_px is None
            or ruling.origin_x_px is None
            or ruling.origin_y_px is None
        ):
            raise ValueError("GRID_GEOMETRY_REQUIRED")
        vertical_coordinate = _normal_coordinate(point, ruling.vertical_angle_deg, vertical=True)
        return RulingRelativePosition(
            x_cells=(vertical_coordinate - ruling.origin_x_px) / ruling.cell_pitch_x_px,
            y_rules=(horizontal_coordinate - ruling.origin_y_px) / ruling.cell_pitch_y_px,
        )
    raise ValueError("RULING_GEOMETRY_NOT_APPLICABLE")


def grid_relative_to_pixel(
    ruling: RulingEstimate, *, frame_id: str, x_cells: float, y_cells: float
) -> PixelPoint:
    """Return the grid intersection for relative coordinates in a squared frame."""

    if ruling.frame_id != frame_id:
        raise ValueError("RULING_FRAME_MISMATCH")
    if ruling.classification != "squared" or any(
        item is None
        for item in (
            ruling.cell_pitch_x_px,
            ruling.cell_pitch_y_px,
            ruling.origin_x_px,
            ruling.origin_y_px,
            ruling.horizontal_angle_deg,
            ruling.vertical_angle_deg,
        )
    ):
        raise ValueError("GRID_GEOMETRY_REQUIRED")
    x_coordinate = ruling.origin_x_px + x_cells * ruling.cell_pitch_x_px
    y_coordinate = ruling.origin_y_px + y_cells * ruling.cell_pitch_y_px
    h_normal = _normal(ruling.horizontal_angle_deg, vertical=False)
    v_normal = _normal(ruling.vertical_angle_deg, vertical=True)
    determinant = v_normal[0] * h_normal[1] - v_normal[1] * h_normal[0]
    if abs(determinant) < 1e-9:
        raise ValueError("RULING_AXES_NOT_INVERTIBLE")
    return PixelPoint(
        x=(x_coordinate * h_normal[1] - v_normal[1] * y_coordinate) / determinant,
        y=(v_normal[0] * y_coordinate - x_coordinate * h_normal[0]) / determinant,
    )


def pixel_to_metric(
    calibration: PhysicalScaleCalibration, *, frame_id: str, point: PixelPoint
) -> MetricPosition:
    """Convert only explicitly calibrated pixel axes to millimetres."""

    if calibration.frame_id != frame_id:
        raise ValueError("CALIBRATION_FRAME_MISMATCH")
    return MetricPosition(
        x_mm=None if calibration.mm_per_px_x is None else point.x * calibration.mm_per_px_x,
        y_mm=None if calibration.mm_per_px_y is None else point.y * calibration.mm_per_px_y,
    )


def ruling_pixel_to_metric(
    ruling: RulingEstimate,
    calibration: PhysicalScaleCalibration,
    *,
    frame_id: str,
    point: PixelPoint,
) -> MetricPosition:
    """Map a pixel to millimetres in the measured ruling coordinate system.

    The physical origin is the stored grid/rule origin, rather than the image's
    upper-left pixel. This keeps the conversion valid for a skewed notebook
    frame. An axis stays unavailable when ruled paper has no measured vertical
    family or the calibration deliberately omitted that scale.
    """

    if ruling.frame_id != frame_id or calibration.frame_id != frame_id:
        raise ValueError("CALIBRATION_RULING_FRAME_MISMATCH")
    horizontal_coordinate = _normal_coordinate(
        point, ruling.horizontal_angle_deg, vertical=False
    )
    if ruling.origin_y_px is None:
        raise ValueError("RULING_GEOMETRY_REQUIRED")
    y_mm = (
        None
        if calibration.mm_per_px_y is None
        else (horizontal_coordinate - ruling.origin_y_px) * calibration.mm_per_px_y
    )
    if ruling.classification != "squared":
        return MetricPosition(x_mm=None, y_mm=y_mm)
    if ruling.origin_x_px is None:
        raise ValueError("GRID_GEOMETRY_REQUIRED")
    vertical_coordinate = _normal_coordinate(point, ruling.vertical_angle_deg, vertical=True)
    return MetricPosition(
        x_mm=(
            None
            if calibration.mm_per_px_x is None
            else (vertical_coordinate - ruling.origin_x_px) * calibration.mm_per_px_x
        ),
        y_mm=y_mm,
    )


def persist_physical_scale_calibration(
    repository: PhotoRepository,
    source: PhotoRecord,
    calibration: PhysicalScaleCalibration,
) -> PhotoRecord:
    """Publish a new manifest with an explicit frame-bound physical scale."""

    if calibration.frame_id not in {frame.frame_id for frame in source.photo.frames}:
        raise ValueError("CALIBRATION_FRAME_NOT_FOUND")
    payload = source.photo.model_dump(mode="python")
    payload["calibration"] = calibration
    updated = NotebookPhoto.model_validate(payload, strict=True)
    return repository.store(updated, repository.read_original(source.photo))


def _normal_coordinate(point: PixelPoint, angle_deg: float | None, *, vertical: bool) -> float:
    if angle_deg is None:
        raise ValueError("RULING_DIRECTION_REQUIRED")
    normal = _normal(angle_deg, vertical=vertical)
    return normal[0] * point.x + normal[1] * point.y


def _normal(angle_deg: float, *, vertical: bool) -> tuple[float, float]:
    radians = math.radians(angle_deg)
    return (math.sin(radians), -math.cos(radians)) if vertical else (
        -math.sin(radians), math.cos(radians)
    )
