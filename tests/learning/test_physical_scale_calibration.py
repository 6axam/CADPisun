from __future__ import annotations

from pathlib import Path

import pytest

from handwriting_plotter.learning import (
    DecodedImageInfo,
    PhotoImportLimits,
    PhotoRepository,
    PixelPoint,
    RulingEstimate,
    calibration_from_ruling_pitch,
    grid_relative_to_pixel,
    persist_physical_scale_calibration,
    pixel_to_metric,
    ruling_pixel_to_metric,
    ruling_pixel_to_relative,
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


def _grid() -> RulingEstimate:
    return RulingEstimate(
        frame_id="source-pixels",
        classification="squared",
        status="proposed",
        method="test-grid/1",
        cell_pitch_x_px=40.0,
        cell_pitch_y_px=40.0,
        origin_x_px=0.0,
        origin_y_px=0.0,
        horizontal_angle_deg=0.0,
        vertical_angle_deg=90.0,
    )


def test_grid_relative_and_explicit_5_mm_preset_round_trip() -> None:
    ruling = _grid()
    calibration = calibration_from_ruling_pitch(ruling)
    point = PixelPoint(x=100.0, y=140.0)

    relative = ruling_pixel_to_relative(ruling, frame_id="source-pixels", point=point)
    restored = grid_relative_to_pixel(
        ruling,
        frame_id="source-pixels",
        x_cells=relative.x_cells or 0.0,
        y_cells=relative.y_rules,
    )
    metric = ruling_pixel_to_metric(
        ruling, calibration, frame_id="source-pixels", point=point
    )

    assert calibration.source == "notebook_cell_preset"
    assert calibration.reference_pitch_mm == 5.0
    assert calibration.mm_per_px_x == pytest.approx(0.125)
    assert calibration.mm_per_px_y == pytest.approx(0.125)
    assert relative.x_cells == pytest.approx(2.5)
    assert relative.y_rules == pytest.approx(3.5)
    assert restored.x == pytest.approx(point.x)
    assert restored.y == pytest.approx(point.y)
    assert metric.x_mm == pytest.approx(12.5)
    assert metric.y_mm == pytest.approx(17.5)


def test_ruled_preset_calibrates_only_the_measured_axis() -> None:
    ruling = RulingEstimate(
        frame_id="source-pixels",
        classification="ruled",
        status="proposed",
        method="test-ruled/1",
        ruling_pitch_px=40.0,
        origin_y_px=0.0,
        horizontal_angle_deg=0.0,
    )

    calibration = calibration_from_ruling_pitch(ruling)
    relative = ruling_pixel_to_relative(
        ruling, frame_id="source-pixels", point=PixelPoint(x=100.0, y=140.0)
    )
    metric = ruling_pixel_to_metric(
        ruling,
        calibration,
        frame_id="source-pixels",
        point=PixelPoint(x=100.0, y=140.0),
    )

    assert relative.x_cells is None
    assert relative.y_rules == pytest.approx(3.5)
    assert calibration.mm_per_px_x is None
    assert calibration.mm_per_px_y == pytest.approx(0.125)
    assert metric.x_mm is None
    assert metric.y_mm == pytest.approx(17.5)


def test_non_preset_value_is_explicit_user_input_and_frame_bound() -> None:
    calibration = calibration_from_ruling_pitch(
        _grid(), pitch_mm=4.0, source="user_entered"
    )

    assert calibration.source == "user_entered"
    assert calibration.reference_pitch_mm == 4.0
    assert calibration.mm_per_px_x == pytest.approx(0.1)
    with pytest.raises(ValueError, match="CALIBRATION_FRAME_MISMATCH"):
        pixel_to_metric(calibration, frame_id="other-frame", point=PixelPoint(x=1.0, y=1.0))


def test_metric_conversion_follows_skewed_ruling_axes() -> None:
    ruling = RulingEstimate(
        frame_id="source-pixels",
        classification="squared",
        status="proposed",
        method="test-skewed-grid/1",
        cell_pitch_x_px=40.0,
        cell_pitch_y_px=40.0,
        origin_x_px=0.0,
        origin_y_px=0.0,
        horizontal_angle_deg=30.0,
        vertical_angle_deg=120.0,
    )
    calibration = calibration_from_ruling_pitch(ruling)
    point = grid_relative_to_pixel(
        ruling, frame_id="source-pixels", x_cells=2.0, y_cells=3.0
    )

    metric = ruling_pixel_to_metric(
        ruling, calibration, frame_id="source-pixels", point=point
    )

    assert metric.x_mm == pytest.approx(10.0)
    assert metric.y_mm == pytest.approx(15.0)


def test_calibration_persists_without_modifying_original_bytes(tmp_path: Path) -> None:
    content = b"synthetic-source"
    path = tmp_path / "page.png"
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
    # The stored source begins with unknown ruling; replace it with a geometry
    # manifest to model the TASK 05 → TASK 06 dependency explicitly.
    payload = source.photo.model_dump(mode="python")
    payload["ruling"] = _grid()
    geometry_record = repository.store(
        type(source.photo).model_validate(payload, strict=True), content
    )
    stored = persist_physical_scale_calibration(
        repository, geometry_record, calibration_from_ruling_pitch(_grid())
    )

    assert stored.photo.calibration is not None
    assert stored.photo.calibration.mm_per_px_y == pytest.approx(0.125)
    assert repository.read_original(stored.photo) == content
    assert repository.load(stored.sha256) == stored.photo
