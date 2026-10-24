"""Qt-free contracts and immutable persistence for notebook paper classification."""

from __future__ import annotations

from typing import Literal, Protocol

from handwriting_plotter.learning.models import ConfidenceValue, NotebookPhoto, RulingEstimate
from handwriting_plotter.learning.repository import PhotoRecord, PhotoRepository

PaperClassification = Literal["unknown", "blank", "squared", "ruled", "mixed"]


class RulingClassifier(Protocol):
    """Classify a selected pixel frame without inventing grid geometry."""

    def classify(self, content: bytes, *, frame_id: str) -> RulingEstimate: ...


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
    updated = NotebookPhoto.model_validate(payload, strict=True)
    return repository.store(updated, repository.read_original(source.photo))
