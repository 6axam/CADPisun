from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from handwriting_plotter.adapters.images.opencv import OpenCvRulingGeometryEstimator
from handwriting_plotter.learning import (
    DecodedImageInfo,
    PhotoImportLimits,
    PhotoRepository,
    manual_ruling_geometry,
    persist_ruling_estimate,
)


class FixedDecoder:
    def probe(self, content: bytes, limits: PhotoImportLimits) -> DecodedImageInfo:
        return DecodedImageInfo(
            width_px=800,
            height_px=600,
            detected_format="png",
            media_type="image/png",
            decoder_id="test",
            decoder_version="1",
        )


def _paper(*, squared: bool, angle_deg: float = 0.0, occlude: bool = False) -> bytes:
    height, width = 600, 800
    image = np.full((height, width, 3), 245, dtype=np.uint8)
    center = (width // 2, height // 2)
    angle = np.deg2rad(angle_deg)

    def rotate(point: tuple[int, int]) -> tuple[int, int]:
        x, y = point[0] - center[0], point[1] - center[1]
        return (
            round(center[0] + x * np.cos(angle) - y * np.sin(angle)),
            round(center[1] + x * np.sin(angle) + y * np.cos(angle)),
        )

    for y in range(50, height, 40):
        cv2.line(image, rotate((25, y)), rotate((width - 25, y)), (190, 155, 100), 2)
    if squared:
        for x in range(40, width, 40):
            cv2.line(image, rotate((x, 25)), rotate((x, height - 25)), (190, 155, 100), 2)
    if occlude:
        cv2.rectangle(image, (100, 210), (620, 310), (35, 35, 35), -1)
        for x in range(80, 650, 90):
            cv2.line(image, (x, 180), (x + 45, 190), (10, 10, 10), 4)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def test_finds_ruled_pitch_phase_and_direction_through_occlusion() -> None:
    estimate = OpenCvRulingGeometryEstimator().estimate(
        _paper(squared=False, angle_deg=4.0, occlude=True),
        frame_id="source-pixels",
        classification="ruled",
    )

    assert estimate.ruling_pitch_px == pytest.approx(40.0, abs=1.0)
    assert estimate.origin_y_px is not None
    assert estimate.horizontal_angle_deg == pytest.approx(4.0, abs=0.5)
    assert estimate.horizontal_residual_px is not None
    assert estimate.horizontal_residual_px < 2.0
    assert estimate.confidence is not None
    assert estimate.confidence.origin == "heuristic"


def test_finds_known_clean_phase() -> None:
    estimate = OpenCvRulingGeometryEstimator().estimate(
        _paper(squared=False), frame_id="source-pixels", classification="ruled"
    )

    assert estimate.ruling_pitch_px == pytest.approx(40.0, abs=0.5)
    # Printed horizontal lines begin at y=50, so their phase is 50 mod 40 = 10.
    assert estimate.origin_y_px == pytest.approx(10.0, abs=2.0)


def test_finds_grid_pitches_directions_and_intersections_under_crossing_ink() -> None:
    estimate = OpenCvRulingGeometryEstimator().estimate(
        _paper(squared=True, angle_deg=-5.0, occlude=True),
        frame_id="source-pixels",
        classification="squared",
    )

    assert estimate.cell_pitch_x_px == pytest.approx(40.0, abs=1.0)
    assert estimate.cell_pitch_y_px == pytest.approx(40.0, abs=1.0)
    assert estimate.origin_x_px is not None
    assert estimate.origin_y_px is not None
    assert estimate.horizontal_angle_deg == pytest.approx(-5.0, abs=0.5)
    assert estimate.vertical_angle_deg == pytest.approx(85.0, abs=0.5)
    assert estimate.horizontal_residual_px is not None
    assert estimate.vertical_residual_px is not None
    assert max(estimate.horizontal_residual_px, estimate.vertical_residual_px) < 2.0


def test_sparse_table_borders_do_not_become_notebook_geometry() -> None:
    image = np.full((600, 800, 3), 245, dtype=np.uint8)
    for y in (120, 300, 480):
        cv2.line(image, (40, y), (760, y), (35, 35, 35), 3)
    for x in (100, 400, 700):
        cv2.line(image, (x, 40), (x, 560), (35, 35, 35), 3)
    ok, encoded = cv2.imencode(".png", image)
    assert ok

    with pytest.raises(ValueError, match="HORIZONTAL_RULING_NOT_FOUND"):
        OpenCvRulingGeometryEstimator().estimate(
            encoded.tobytes(), frame_id="source-pixels", classification="ruled"
        )


def test_manual_geometry_is_immutable_and_does_not_assume_millimetres(tmp_path: Path) -> None:
    content = _paper(squared=True)
    path = tmp_path / "grid.png"
    path.write_bytes(content)
    repository = PhotoRepository(tmp_path / "store")
    source = repository.import_file(
        path,
        FixedDecoder(),
        imported_at_utc="2026-10-24T12:00:00Z",
        application_version="test",
        source_kind="image_file",
        rights_status="private_user_material",
    )
    estimate = manual_ruling_geometry(
        "squared",
        frame_id="source-pixels",
        origin_x_px=8.0,
        origin_y_px=12.0,
        cell_pitch_x_px=40.0,
        cell_pitch_y_px=40.0,
    )
    stored = persist_ruling_estimate(repository, source, estimate)

    assert stored.photo.ruling.status == "overridden"
    assert stored.photo.ruling.cell_pitch_x_px == 40.0
    assert stored.photo.ruling.cell_pitch_y_px == 40.0
    assert stored.photo.ruling.ruling_pitch_px is None
    assert repository.read_original(stored.photo) == content
