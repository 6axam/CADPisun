"""Qt-free contracts and immutable persistence for notebook paper classification."""

from __future__ import annotations

from typing import Literal, Protocol

from handwriting_plotter.learning.models import ConfidenceValue, NotebookPhoto, RulingEstimate
from handwriting_plotter.learning.repository import PhotoRecord, PhotoRepository

PaperClassification = Literal["unknown", "blank", "squared", "ruled", "mixed"]


class RulingClassifier(Protocol):
    """Classify a selected pixel frame without inventing grid geometry."""

    def classify(self, content: bytes, *, frame_id: str) -> RulingEstimate: ...


class RulingGeometryEstimator(Protocol):
    """Estimate image-space ruling geometry for an already classified frame."""

    def estimate(
        self,
        content: bytes,
        *,
        frame_id: str,
        classification: PaperClassification,
    ) -> RulingEstimate: ...


def manual_ruling_estimate(
    classification: PaperClassification, *, frame_id: str
) -> RulingEstimate:
    """Represent a local user's explicit paper-type decision."""

    return RulingEstimate(
        frame_id=frame_id,
        classification=classification,
        status="overridden",
        method="manual-ruling-classification/1",
        confidence=ConfidenceValue(
            value=1.0,
            origin="human",
            meaning="local user selected the notebook paper classification",
        ),
    )


def manual_ruling_geometry(
    classification: Literal["squared", "ruled"],
    *,
    frame_id: str,
    origin_x_px: float | None = None,
    origin_y_px: float,
    cell_pitch_x_px: float | None = None,
    cell_pitch_y_px: float | None = None,
    ruling_pitch_px: float | None = None,
    horizontal_angle_deg: float = 0.0,
    vertical_angle_deg: float | None = None,
) -> RulingEstimate:
    """Save user-entered pixel geometry without assuming a physical paper size."""

    if classification == "squared":
        if origin_x_px is None or cell_pitch_x_px is None or cell_pitch_y_px is None:
            raise ValueError("SQUARED_GEOMETRY_REQUIRES_GRID_VALUES")
        return RulingEstimate(
            frame_id=frame_id,
            classification=classification,
            status="overridden",
            method="manual-ruling-geometry/1",
            confidence=ConfidenceValue(
                value=1.0,
                origin="human",
                meaning="local user adjusted notebook grid geometry in pixels",
            ),
            origin_x_px=origin_x_px,
            origin_y_px=origin_y_px,
            cell_pitch_x_px=cell_pitch_x_px,
            cell_pitch_y_px=cell_pitch_y_px,
            horizontal_angle_deg=horizontal_angle_deg,
            vertical_angle_deg=90.0 if vertical_angle_deg is None else vertical_angle_deg,
        )
    if ruling_pitch_px is None:
        raise ValueError("RULED_GEOMETRY_REQUIRES_PITCH")
    return RulingEstimate(
        frame_id=frame_id,
        classification=classification,
        status="overridden",
        method="manual-ruling-geometry/1",
        confidence=ConfidenceValue(
            value=1.0,
            origin="human",
            meaning="local user adjusted notebook ruling geometry in pixels",
        ),
        origin_y_px=origin_y_px,
        ruling_pitch_px=ruling_pitch_px,
        horizontal_angle_deg=horizontal_angle_deg,
    )


def persist_ruling_estimate(
    repository: PhotoRepository,
    source: PhotoRecord,
    estimate: RulingEstimate,
) -> PhotoRecord:
    """Write a new photo manifest while preserving source and derivative assets."""

    frame_ids = {frame.frame_id for frame in source.photo.frames}
    if estimate.frame_id not in frame_ids:
        raise ValueError("RULING_FRAME_NOT_FOUND")
    # Keep tuple-backed model fields in Python mode: strict validation deliberately
    # rejects JSON lists so malformed manifests cannot enter the repository.
    payload = source.photo.model_dump(mode="python")
    payload["ruling"] = estimate
    # Geometry revisions change the denominator of any pitch-based scale.  A
    # calibration must be deliberately reapplied instead of silently surviving.
    payload["calibration"] = None
    updated = NotebookPhoto.model_validate(payload, strict=True)
    return repository.store(updated, repository.read_original(source.photo))
