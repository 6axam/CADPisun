from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from handwriting_plotter.capture.models import (
    CapturePoint,
    CaptureProvenance,
    CaptureSample,
    CaptureSession,
    CaptureStroke,
    CoordinateReference,
    DeviceCapabilities,
    WritingGuides,
)
from handwriting_plotter.capture.processing import (
    ProcessedRepository,
    ProcessingParameters,
    load_processed_bytes,
    process_sample,
    serialize_processed,
)
from handwriting_plotter.capture.repository import CaptureRepository
from handwriting_plotter.geometry.curves import Cubic, Quadratic


SOURCE_HASH = sha256(b"immutable raw fixture").hexdigest()


def _sample(*strokes: tuple[tuple[float, float], ...]) -> CaptureSample:
    elapsed = 0.0
    captured = []
    for stroke_index, coordinates in enumerate(strokes):
        points = []
        for point_index, (x, y) in enumerate(coordinates):
            event = "down" if point_index == 0 else "up" if point_index == len(coordinates) - 1 else "move"
            points.append(CapturePoint(
                point_id=f"p-{stroke_index}-{point_index}", event=event, x=x, y=y,
                elapsed_s=elapsed, pointer_type="mouse",
            ))
            elapsed += 0.01
        captured.append(CaptureStroke(stroke_id=f"stroke-{stroke_index}", points=tuple(points)))
    return CaptureSample(
        sample_id="sample-curves",
        label="м",
        classification="glyph",
        coordinate_reference=CoordinateReference(width=400.0, height=300.0),
        guides=WritingGuides(ascender_y=30.0, x_height_y=90.0, baseline_y=220.0, descender_y=270.0),
        provenance=CaptureProvenance(
            source="synthetic_fixture", captured_at_utc="2026-10-14T12:00:00Z",
            timing_source="monotonic", application_version="test",
        ),
        strokes=tuple(captured),
    )


def _store_source(tmp_path: Path, sample: CaptureSample):
    session = CaptureSession(
        session_id="session-processing",
        created_at_utc="2026-10-14T12:00:00Z",
        device=DeviceCapabilities(pointer_types=("mouse",)),
        samples=(sample,),
    )
    return CaptureRepository(tmp_path).store(session)


def test_two_tolerances_link_same_raw_and_respect_certified_error() -> None:
    sample = _sample((
        (20.0, 220.0), (35.0, 180.0), (55.0, 145.0), (80.0, 125.0),
        (110.0, 120.0), (140.0, 135.0), (165.0, 170.0), (180.0, 220.0),
    ))
    fine = process_sample(sample, SOURCE_HASH, ProcessingParameters(
        max_deviation_px=0.35, resample_spacing_px=0.5,
    ))
    coarse = process_sample(sample, SOURCE_HASH, ProcessingParameters(
        max_deviation_px=2.0, resample_spacing_px=1.0,
    ))

    assert fine.source_capture_sha256 == coarse.source_capture_sha256 == SOURCE_HASH
    assert fine.source_sample_id == coarse.source_sample_id == sample.sample_id
    assert fine.processed_id != coarse.processed_id
    assert all(report.certified_max_deviation_px <= fine.parameters.max_deviation_px
               for report in fine.reports)
    assert all(report.certified_max_deviation_px <= coarse.parameters.max_deviation_px
               for report in coarse.reports)
    assert sum(report.output_segments for report in fine.reports) >= sum(
        report.output_segments for report in coarse.reports
    )
    for raw, processed in zip(sample.strokes, coarse.to_strokes(), strict=True):
        assert processed.start.x == raw.points[0].x
        assert processed.start.y == raw.points[0].y
        assert processed.end.x == raw.points[-1].x
        assert processed.end.y == raw.points[-1].y
        assert processed.direction_provenance == "captured"


def test_processing_preserves_boundaries_corner_loop_and_small_mark() -> None:
    sample = _sample(
        ((20.0, 200.0), (80.0, 200.0), (80.0, 100.0), (140.0, 100.0)),
        ((200.0, 170.0), (230.0, 120.0), (260.0, 170.0), (230.0, 220.0), (200.0, 170.0)),
        ((300.0, 80.0), (300.0, 80.0)),
    )
    processed = process_sample(sample, SOURCE_HASH, ProcessingParameters(max_deviation_px=0.5))
    runtime = processed.to_strokes()

    assert [stroke.id for stroke in runtime] == [stroke.stroke_id for stroke in sample.strokes]
    assert len(runtime[0].segments) >= 3  # the two right-angle corners remain explicit
    assert runtime[1].start == runtime[1].end  # closed loop remains closed
    assert len(runtime[1].segments) >= 2
    assert runtime[2].role == "mark"
    assert runtime[2].start == runtime[2].end
    assert processed.reports[2].fitting == "point-mark"


def test_processing_filters_duplicates_and_fits_curves_when_within_budget() -> None:
    sample = _sample(((10.0, 210.0), (10.001, 210.001), (40.0, 150.0),
                      (90.0, 110.0), (150.0, 150.0), (180.0, 210.0)))
    result = process_sample(sample, SOURCE_HASH, ProcessingParameters(
        max_deviation_px=3.0, duplicate_epsilon_px=0.01, resample_spacing_px=2.0,
    ))
    report = result.reports[0]

    assert report.duplicate_filtered_points == len(sample.strokes[0].points) - 1
    assert report.certified_max_deviation_px <= 3.0
    assert report.fitting in {"bezier", "polyline"}
    if report.fitting == "bezier":
        assert any(isinstance(segment, Cubic) for segment in result.to_strokes()[0].segments)


def test_processing_is_stable_and_can_fit_quadratic_geometry() -> None:
    coordinates = tuple(
        (float(x), 100.0 + (x - 50.0) ** 2 / 100.0) for x in range(0, 101, 10)
    )
    sample = _sample(coordinates)
    parameters = ProcessingParameters(max_deviation_px=10.0, resample_spacing_px=2.0)

    first = process_sample(sample, SOURCE_HASH, parameters)
    second = process_sample(sample, SOURCE_HASH, parameters)

    assert serialize_processed(first) == serialize_processed(second)
    assert any(isinstance(segment, Quadratic) for segment in first.to_strokes()[0].segments)
    assert first.reports[0].certified_max_deviation_px <= parameters.max_deviation_px


def test_processed_repository_round_trip_keeps_parameters_and_raw_untouched(tmp_path: Path) -> None:
    sample = _sample(((20.0, 220.0), (70.0, 100.0), (140.0, 220.0)))
    original = sample.model_dump_json()
    source = _store_source(tmp_path, sample)
    parameters = ProcessingParameters(max_deviation_px=0.8, smoothing_passes=1)
    processed = process_sample(sample, source.sha256, parameters)
    repository = ProcessedRepository(tmp_path)

    record = repository.store(processed)

    assert repository.load(source.sha256, record.sha256) == processed
    assert load_processed_bytes(serialize_processed(processed)) == processed
    assert repository.list_for_source(source.sha256) == (record,)
    assert processed.parameters == parameters
    assert sample.model_dump_json() == original
    assert not list(tmp_path.rglob("*.tmp"))


def test_processed_repository_requires_verified_raw_source(tmp_path: Path) -> None:
    sample = _sample(((20.0, 220.0), (70.0, 100.0), (140.0, 220.0)))
    processed = process_sample(sample, SOURCE_HASH, ProcessingParameters(max_deviation_px=1.0))

    with pytest.raises(FileNotFoundError, match="CAPTURE_NOT_FOUND"):
        ProcessedRepository(tmp_path).store(processed)


def test_processing_rejects_invalid_tolerance_and_tampered_derivative(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ProcessingParameters(max_deviation_px=0.0)

    sample = _sample(((10.0, 10.0), (20.0, 20.0)))
    source = _store_source(tmp_path, sample)
    processed = process_sample(
        sample, source.sha256,
        ProcessingParameters(max_deviation_px=0.5),
    )
    repository = ProcessedRepository(tmp_path)
    record = repository.store(processed)
    record.path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="PROCESSED_HASH_MISMATCH"):
        repository.load(source.sha256, record.sha256)


def test_processing_enforces_resampling_budget(monkeypatch) -> None:
    import handwriting_plotter.capture.processing as processing

    monkeypatch.setattr(processing, "MAX_PROCESSING_POINTS", 4)
    sample = _sample(((10.0, 10.0), (100.0, 100.0), (200.0, 200.0)))
    with pytest.raises(ValueError, match="PROCESSING_POINT_BUDGET_EXCEEDED"):
        process_sample(
            sample, SOURCE_HASH,
            ProcessingParameters(max_deviation_px=1.0, resample_spacing_px=1.0),
        )
