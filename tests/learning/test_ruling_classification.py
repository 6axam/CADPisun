from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from handwriting_plotter.adapters.images.opencv import OpenCvRulingClassifier
from handwriting_plotter.learning import (
    DecodedImageInfo,
    PhotoImportLimits,
    PhotoRepository,
    RulingEstimate,
    manual_ruling_estimate,
    persist_ruling_estimate,
)


class FixedDecoder:
    def probe(self, content: bytes, limits: PhotoImportLimits) -> DecodedImageInfo:
        return DecodedImageInfo(
            width_px=520,
            height_px=360,
            detected_format="png",
            media_type="image/png",
            decoder_id="test",
            decoder_version="1",
        )


def _encode(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _paper(kind: str) -> bytes:
    image = np.full((360, 520, 3), 245, dtype=np.uint8)
    if kind in {"ruled", "squared"}:
        for y in range(30, 350, 30):
            cv2.line(image, (10, y), (510, y), (190, 155, 100), 1)
        # Short handwriting remains beneath the repeated paper lines.
        for x in range(40, 440, 65):
            cv2.line(image, (x, 92), (x + 35, 98), (35, 35, 35), 2)
    if kind == "squared":
        for x in range(20, 510, 30):
            cv2.line(image, (x, 10), (x, 350), (190, 155, 100), 1)
    if kind == "mixed":
        # A sparse table plus dense marks is deliberately neither notebook grid nor rules.
        for start, end in (((30, 60), (490, 60)), ((30, 250), (490, 250)), ((100, 20), (100, 340)), ((400, 20), (400, 340))):
            cv2.line(image, start, end, (50, 50, 50), 2)
        generator = np.random.default_rng(41)
        for x, y in generator.integers([20, 80], [500, 230], size=(500, 2)):
            cv2.circle(image, (int(x), int(y)), 2, (30, 30, 30), -1)
    if kind == "unknown":
        cv2.line(image, (50, 100), (420, 120), (30, 30, 30), 3)
    return _encode(image)


@pytest.mark.parametrize("kind", ("blank", "ruled", "squared", "mixed", "unknown"))
def test_classifier_handles_synthetic_paper_and_interference(kind: str) -> None:
    estimate = OpenCvRulingClassifier().classify(_paper(kind), frame_id="source-pixels")

    assert estimate.classification == kind
    assert estimate.status == "proposed"
    assert estimate.method == "opencv-ruling-classifier/1"
    assert estimate.confidence is not None
    assert estimate.confidence.origin == "heuristic"
    assert estimate.cell_pitch_x_px is None
    assert estimate.cell_pitch_y_px is None
    assert estimate.ruling_pitch_px is None


def test_manual_override_is_explicit_and_persists_as_new_manifest(tmp_path: Path) -> None:
    content = _paper("ruled")
    source_path = tmp_path / "paper.png"
    source_path.write_bytes(content)
    repository = PhotoRepository(tmp_path / "store")
    source = repository.import_file(
        source_path,
        FixedDecoder(),
        imported_at_utc="2026-10-24T12:00:00Z",
        application_version="test",
        source_kind="image_file",
        rights_status="private_user_material",
    )
    proposal = OpenCvRulingClassifier().classify(content, frame_id="source-pixels")
    proposed = persist_ruling_estimate(repository, source, proposal)
    overridden = persist_ruling_estimate(
        repository,
        proposed,
        manual_ruling_estimate("squared", frame_id="source-pixels"),
    )

    assert source.photo.ruling.status == "not_evaluated"
    assert proposed.photo.ruling.classification == "ruled"
    assert overridden.photo.ruling.classification == "squared"
    assert overridden.photo.ruling.status == "overridden"
    assert overridden.photo.ruling.confidence is not None
    assert overridden.photo.ruling.confidence.origin == "human"
    assert repository.read_original(overridden.photo) == content
    assert repository.load(overridden.sha256) == overridden.photo


def test_persist_rejects_an_estimate_for_an_unknown_frame(tmp_path: Path) -> None:
    content = _paper("blank")
    source_path = tmp_path / "paper.png"
    source_path.write_bytes(content)
    repository = PhotoRepository(tmp_path / "store")
    source = repository.import_file(
        source_path,
        FixedDecoder(),
        imported_at_utc="2026-10-24T12:00:00Z",
        application_version="test",
        source_kind="image_file",
        rights_status="private_user_material",
    )

    with pytest.raises(ValueError, match="RULING_FRAME_NOT_FOUND"):
        persist_ruling_estimate(
            repository,
            source,
            RulingEstimate(
                frame_id="missing",
                classification="blank",
                status="proposed",
                method="test/1",
            ),
        )
