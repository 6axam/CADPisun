from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from handwriting_plotter.adapters.images.opencv import OpenCvInkSeparator
from handwriting_plotter.learning import (
    DecodedImageInfo,
    PhotoImportLimits,
    PhotoRepository,
    RulingEstimate,
    InkMaskRaster,
    persist_ink_mask,
    select_ink_mask_variant,
)


def _ruled() -> RulingEstimate:
    return RulingEstimate(
        frame_id="source-pixels",
        classification="ruled",
        status="proposed",
        method="fixture/1",
        ruling_pitch_px=30.0,
        origin_y_px=30.0,
        horizontal_angle_deg=0.0,
    )


def _fixture() -> bytes:
    image = np.full((180, 320, 3), 245, dtype=np.uint8)
    for y in range(30, 180, 30):
        cv2.line(image, (5, y), (315, y), (195, 165, 105), 1)
    cv2.line(image, (80, 90), (275, 90), (25, 25, 25), 3)
    cv2.circle(image, (120, 145), 3, (80, 30, 100), -1)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def _decode_mask(content: bytes):
    mask = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert mask is not None
    return mask


def test_cleaned_mask_removes_rule_but_keeps_crossing_ink_and_dot() -> None:
    raster = OpenCvInkSeparator().separate(_fixture(), frame_id="source-pixels", ruling=_ruled())
    raw = _decode_mask(raster.raw_png)
    cleaned = _decode_mask(raster.cleaned_png)

    assert raw[30, 220] == 255
    assert cleaned[30, 220] == 0
    assert raw[90, 180] == 255
    assert cleaned[90, 180] == 255
    assert cleaned[145, 120] == 255
    assert raster.diagnostics == ("RULING_REMOVAL_CONSERVATIVE", "DARK_INTERSECTIONS_PROTECTED")


def test_without_geometry_cleaned_mask_is_the_reviewable_raw_fallback() -> None:
    unknown = RulingEstimate(frame_id="source-pixels")
    raster = OpenCvInkSeparator().separate(_fixture(), frame_id="source-pixels", ruling=unknown)
    assert raster.raw_png == raster.cleaned_png
    assert raster.diagnostics == ("NO_RULING_GEOMETRY_RAW_EQUALS_CLEANED",)


class FixedDecoder:
    def probe(self, content: bytes, limits: PhotoImportLimits) -> DecodedImageInfo:
        return DecodedImageInfo(320, 180, "png", "image/png", "test", "1")


def test_masks_are_content_addressed_and_manual_raw_override_is_persisted(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    content = _fixture()
    source.write_bytes(content)
    repository = PhotoRepository(tmp_path / "store")
    record = repository.import_file(
        source,
        FixedDecoder(),
        imported_at_utc="2026-10-24T12:00:00Z",
        application_version="test",
        source_kind="image_file",
        rights_status="private_user_material",
    )
    raster = OpenCvInkSeparator().separate(content, frame_id="source-pixels", ruling=_ruled())
    stored = persist_ink_mask(repository, record, raster)
    assert stored.photo.ink_mask is not None
    assert repository._safe_child(stored.photo.ink_mask.raw_relative_path).is_file()
    assert repository._safe_child(stored.photo.ink_mask.cleaned_relative_path).is_file()

    overridden = select_ink_mask_variant(repository, stored, "raw")
    assert overridden.photo.ink_mask is not None
    assert overridden.photo.ink_mask.status == "overridden"
    assert overridden.photo.ink_mask.selected_variant == "raw"
    assert repository.read_original(overridden.photo) == content
