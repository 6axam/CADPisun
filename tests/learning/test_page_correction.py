from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from handwriting_plotter.adapters.images.opencv import OpenCvPageCorrector
from handwriting_plotter.learning import (
    DecodedImageInfo,
    PageCorners,
    PhotoImportLimits,
    PhotoRepository,
    PixelPoint,
    map_point,
    order_page_corners,
    persist_correction,
)


class FixedDecoder:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def probe(self, content: bytes, limits: PhotoImportLimits) -> DecodedImageInfo:
        return DecodedImageInfo(
            width_px=self.width,
            height_px=self.height,
            detected_format="png",
            media_type="image/png",
            decoder_id="test",
            decoder_version="1",
        )


def _encode(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _synthetic_page() -> tuple[bytes, tuple[tuple[int, int], ...]]:
    image = np.full((640, 840, 3), 28, dtype=np.uint8)
    corners = ((120, 70), (735, 105), (760, 570), (85, 545))
    polygon = np.array(corners, dtype=np.int32)
    cv2.fillConvexPoly(image, polygon, (242, 242, 232))
    for y in range(145, 535, 48):
        cv2.line(image, (120, y), (725, y + 15), (190, 180, 120), 2)
    return _encode(image), corners


def test_corner_order_and_invalid_bow_tie() -> None:
    corners = order_page_corners(
        (
            PixelPoint(x=90, y=80),
            PixelPoint(x=10, y=10),
            PixelPoint(x=95, y=15),
            PixelPoint(x=15, y=90),
        ),
        frame_id="preview",
    )
    assert corners.top_left == PixelPoint(x=10, y=10)
    assert corners.top_right == PixelPoint(x=95, y=15)
    assert corners.bottom_right == PixelPoint(x=90, y=80)
    assert corners.bottom_left == PixelPoint(x=15, y=90)
    with pytest.raises(ValueError, match="PAGE_CORNERS"):
        PageCorners(
            frame_id="preview",
            top_left=PixelPoint(x=0, y=0),
            top_right=PixelPoint(x=10, y=10),
            bottom_right=PixelPoint(x=10, y=0),
            bottom_left=PixelPoint(x=0, y=10),
        )


def test_automatic_proposal_and_no_page_diagnostic() -> None:
    content, expected = _synthetic_page()
    corrector = OpenCvPageCorrector()

    proposal = corrector.propose(content, orientation="none", source_frame_id="source-pixels")

    assert proposal.status == "proposed"
    assert proposal.corners is not None
    assert proposal.confidence is not None
    assert proposal.confidence.origin == "heuristic"
    for actual, target in zip(proposal.corners.points, expected, strict=True):
        assert actual.x == pytest.approx(target[0], abs=8)
        assert actual.y == pytest.approx(target[1], abs=8)
    assert "AUTOMATIC_PROPOSAL_REQUIRES_REVIEW" in proposal.diagnostics

    blank = _encode(np.full((300, 400, 3), 220, dtype=np.uint8))
    missing = corrector.propose(blank, orientation="none", source_frame_id="source-pixels")
    assert missing.status == "not_found"
    assert missing.corners is None
    assert "NO_PAGE_QUADRILATERAL" in missing.diagnostics
    assert "PLANAR_MODEL_ONLY" in missing.diagnostics


def test_homography_round_trip_and_optional_deskew() -> None:
    content, raw = _synthetic_page()
    corners = order_page_corners(
        tuple(PixelPoint(x=x, y=y) for x, y in raw),
        frame_id="source-pixels",
    )
    corrector = OpenCvPageCorrector()
    corrected = corrector.correct(content, corners, orientation="none")

    assert corrected.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert corrected.width_px > corrected.height_px
    for point in corners.points:
        mapped = map_point(corrected.forward_matrix, point)
        restored = map_point(corrected.inverse_matrix, mapped)
        assert restored.x == pytest.approx(point.x, abs=1e-6)
        assert restored.y == pytest.approx(point.y, abs=1e-6)
    deskewed = corrector.correct(content, corners, orientation="none", deskew_degrees=1.25)
    assert deskewed.parameters["deskew_degrees"] == 1.25
    center = PixelPoint(
        x=sum(point.x for point in corners.points) / 4,
        y=sum(point.y for point in corners.points) / 4,
    )
    mapped_center = map_point(deskewed.forward_matrix, center)
    restored_center = map_point(deskewed.inverse_matrix, mapped_center)
    assert restored_center.x == pytest.approx(center.x, abs=1e-6)
    assert restored_center.y == pytest.approx(center.y, abs=1e-6)


def test_orientation_is_composed_into_transform() -> None:
    image = np.zeros((60, 100, 3), dtype=np.uint8)
    content = _encode(image)
    corners = PageCorners(
        frame_id="oriented-preview",
        top_left=PixelPoint(x=0, y=0),
        top_right=PixelPoint(x=59, y=0),
        bottom_right=PixelPoint(x=59, y=99),
        bottom_left=PixelPoint(x=0, y=99),
    )

    corrected = OpenCvPageCorrector().correct(content, corners, orientation="rotate_90")

    assert (corrected.width_px, corrected.height_px) == (60, 100)
    assert corrected.parameters["orientation"] == "rotate_90"
    mapped_top_left = map_point(corrected.forward_matrix, PixelPoint(x=0, y=0))
    assert mapped_top_left.x == pytest.approx(59, abs=1e-6)
    assert mapped_top_left.y == pytest.approx(0, abs=1e-6)


@pytest.mark.parametrize(
    "orientation",
    (
        "none",
        "mirror_horizontal",
        "flip_vertical",
        "rotate_180",
        "rotate_90",
        "mirror_horizontal_rotate_90",
        "flip_vertical_rotate_90",
        "rotate_270",
    ),
)
def test_orientation_matrix_matches_raster_operation(orientation: str) -> None:
    source = np.arange(3 * 4, dtype=np.uint8).reshape((3, 4))

    oriented, matrix = OpenCvPageCorrector._apply_orientation(source, orientation)

    for y in range(source.shape[0]):
        for x in range(source.shape[1]):
            target = map_point(
                tuple(float(value) for value in matrix.reshape(9)),
                PixelPoint(x=x, y=y),
            )
            assert oriented[round(target.y), round(target.x)] == source[y, x]


def test_persisted_correction_keeps_original_and_transform_chain(tmp_path: Path) -> None:
    content, raw = _synthetic_page()
    source_path = tmp_path / "page.png"
    source_path.write_bytes(content)
    repository = PhotoRepository(tmp_path / "store")
    source = repository.import_file(
        source_path,
        FixedDecoder(840, 640),
        imported_at_utc="2026-10-23T12:00:00Z",
        application_version="test",
        source_kind="image_file",
        rights_status="private_user_material",
    )
    corners = order_page_corners(
        tuple(PixelPoint(x=x, y=y) for x, y in raw), frame_id="source-pixels"
    )
    corrector = OpenCvPageCorrector()
    raster = corrector.correct(content, corners, orientation="none")

    correction = persist_correction(
        repository,
        source,
        raster,
        proposal_method="manual-four-corner/1",
        confidence=None,
    )

    assert repository.read_original(correction.record.photo) == content
    assert Path(correction.raster_path).read_bytes() == raster.content
    assert len(correction.record.photo.frames) == 2
    assert len(correction.record.photo.transforms) == 1
    transform = correction.record.photo.transforms[0]
    assert transform.kind == "homography"
    assert transform.output_sha256 == correction.raster_sha256
    assert transform.parameters["proposal_method"] == "manual-four-corner/1"
    assert transform.parameters["planar_only"] is True
    assert repository.load(correction.record.sha256) == correction.record.photo

    repeated = persist_correction(
        repository,
        correction.record,
        raster,
        proposal_method="manual-four-corner/1",
        confidence=None,
    )
    assert repeated.record.sha256 == correction.record.sha256
    assert len(repeated.record.photo.transforms) == 1

    Path(correction.raster_path).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="PHOTO_DERIVATIVE_HASH_MISMATCH"):
        repository.store_derivative(raster.content, suffix="png")
