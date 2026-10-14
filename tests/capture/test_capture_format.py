from __future__ import annotations

import json
import math
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


def replace(model, **changes):  # noqa: ANN001, ANN202
    data = model.model_dump(mode="python")
    data.update(changes)
    return type(model).model_validate(data, strict=True)
from handwriting_plotter.capture.repository import (
    MAX_CAPTURE_BYTES,
    CaptureRepository,
    capture_sha256,
    load_capture_bytes,
    serialize_capture,
)


def sample_session() -> CaptureSession:
    frame = CoordinateReference(width=640.0, height=480.0, device_pixel_ratio=1.5)
    guides = WritingGuides(ascender_y=80.0, x_height_y=160.0, baseline_y=320.0, descender_y=400.0)
    provenance = CaptureProvenance(
        source="synthetic_fixture",
        captured_at_utc="2026-10-14T10:00:00Z",
        timing_source="monotonic",
        application_version="test",
    )
    first = CaptureStroke(
        stroke_id="stroke-1",
        points=(
            CapturePoint(point_id="p1", event="down", x=100.0, y=300.0, elapsed_s=0.125,
                         pressure=None, pointer_type="mouse"),
            CapturePoint(point_id="p2", event="move", x=110.0, y=280.0, elapsed_s=0.140,
                         pressure=None, pointer_type="mouse"),
            CapturePoint(point_id="p3", event="up", x=120.0, y=260.0, elapsed_s=0.155,
                         pressure=None, pointer_type="mouse"),
        ),
    )
    second = CaptureStroke(
        stroke_id="stroke-2",
        points=(
            CapturePoint(point_id="p4", event="down", x=130.0, y=260.0, elapsed_s=0.200,
                         pressure=None, pointer_type="mouse"),
            CapturePoint(point_id="p5", event="up", x=145.0, y=300.0, elapsed_s=0.230,
                         pressure=None, pointer_type="mouse"),
        ),
    )
    return CaptureSession(
        session_id="session-1",
        created_at_utc="2026-10-14T10:00:00Z",
        device=DeviceCapabilities(pointer_types=("mouse",), pressure=False),
        samples=(CaptureSample(
            sample_id="sample-1",
            label="ї",
            classification="glyph",
            coordinate_reference=frame,
            guides=guides,
            provenance=provenance,
            strokes=(first, second),
        ),),
    )


def test_capture_round_trip_preserves_order_coordinates_and_missing_pressure(tmp_path: Path) -> None:
    original = sample_session()
    encoded = serialize_capture(original)
    reopened = load_capture_bytes(encoded)

    assert reopened == original
    points = reopened.samples[0].strokes[0].points
    assert [(point.x, point.y) for point in points] == [(100.0, 300.0), (110.0, 280.0), (120.0, 260.0)]
    assert all(point.pressure is None for point in points)
    assert json.loads(encoded)["format"] == "hp-capture"
    assert json.loads(encoded)["schema_version"] == "1.0"

    repository = CaptureRepository(tmp_path)
    record = repository.store(original)
    assert record.sha256 == capture_sha256(original)
    assert repository.load(record.sha256) == original
    assert repository.store(original).path == record.path
    assert not list(tmp_path.rglob("*.tmp"))


def test_capture_repository_never_overwrites_hash_content(tmp_path: Path) -> None:
    repository = CaptureRepository(tmp_path)
    session = sample_session()
    record = repository.store(session)
    record.path.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="CAPTURE_HASH_MISMATCH"):
        repository.store(session)
    with pytest.raises(ValueError, match="CAPTURE_HASH_MISMATCH"):
        repository.load(record.sha256)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data | {"schema_version": "2.0"}, "UNSUPPORTED_CAPTURE_SCHEMA"),
        (lambda data: data | {"format": "other"}, "UNSUPPORTED_CAPTURE_FORMAT"),
        (lambda data: data | {"unexpected": True}, "extra"),
    ],
)
def test_capture_rejects_unknown_schema_format_and_fields(mutation, message: str) -> None:  # noqa: ANN001
    data = json.loads(serialize_capture(sample_session()))
    with pytest.raises((ValueError, ValidationError), match=message):
        load_capture_bytes(json.dumps(mutation(data), ensure_ascii=False).encode())


def test_capture_rejects_malformed_duplicate_and_oversized_json() -> None:
    with pytest.raises(ValueError):
        load_capture_bytes(b'{"format":"hp-capture"')
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_capture_bytes(b'{"format":"hp-capture","format":"hp-capture"}')
    with pytest.raises(ValueError, match="CAPTURE_FILE_TOO_LARGE"):
        load_capture_bytes(b" " * (MAX_CAPTURE_BYTES + 1))


def test_capture_rejects_nonfinite_coordinates_and_out_of_canvas_points() -> None:
    with pytest.raises(ValidationError):
        CapturePoint(point_id="p", event="down", x=math.inf, y=0.0, pointer_type="mouse")

    data = json.loads(serialize_capture(sample_session()))
    data["samples"][0]["strokes"][0]["points"][1]["x"] = 641.0
    with pytest.raises(ValidationError, match="outside capture canvas"):
        load_capture_bytes(json.dumps(data).encode())


def test_capture_rejects_invalid_strokes_times_and_duplicate_identifiers() -> None:
    session = sample_session()
    stroke = session.samples[0].strokes[0]
    with pytest.raises(ValidationError, match="stroke must end"):
        CaptureStroke(stroke_id="bad", points=stroke.points[:-1])

    bad_time = replace(stroke.points[1], elapsed_s=0.100)
    with pytest.raises(ValidationError, match="monotonic"):
        CaptureStroke(stroke_id="bad-time", points=(stroke.points[0], bad_time, stroke.points[2]))

    duplicate_point = replace(stroke.points[1], point_id=stroke.points[0].point_id)
    with pytest.raises(ValidationError, match="duplicate point id"):
        CaptureStroke(stroke_id="duplicate-point", points=(stroke.points[0], duplicate_point, stroke.points[2]))

    duplicate_stroke = replace(session.samples[0].strokes[1], stroke_id=stroke.stroke_id)
    with pytest.raises(ValidationError, match="duplicate stroke id"):
        CaptureSample(
            sample_id="duplicate-stroke",
            label="ї",
            classification="glyph",
            coordinate_reference=session.samples[0].coordinate_reference,
            guides=session.samples[0].guides,
            provenance=session.samples[0].provenance,
            strokes=(stroke, duplicate_stroke),
        )

    with pytest.raises(ValidationError, match="duplicate sample id"):
        CaptureSession(
            session_id="duplicate-sample",
            created_at_utc=session.created_at_utc,
            device=session.device,
            samples=(session.samples[0], session.samples[0]),
        )


def test_capture_requires_honest_timing_pressure_and_label_classification() -> None:
    session = sample_session()
    sample = session.samples[0]
    untimed = replace(sample.strokes[0].points[0], elapsed_s=None)
    with pytest.raises(ValidationError, match="all points or no points"):
        replace(sample.strokes[0], points=(untimed, *sample.strokes[0].points[1:]))

    with pytest.raises(ValidationError, match="pressure capability"):
        replace(sample.strokes[0].points[0], pressure=0.0)

    pen_down = CapturePoint(
        point_id="pen-zero", event="down", x=1.0, y=2.0, elapsed_s=0.0,
        pressure=0.0, pointer_type="pen",
    )
    assert pen_down.pressure == 0.0
    assert pen_down.elapsed_s == 0.0

    with pytest.raises(ValidationError, match="glyph classification"):
        replace(sample, label="ма")
    assert replace(sample, label="ма", classification="sequence").label == "ма"


def test_capture_rejects_invalid_guides_and_excessive_point_count(monkeypatch) -> None:
    with pytest.raises(ValidationError, match="guide order"):
        WritingGuides(ascender_y=10.0, x_height_y=200.0, baseline_y=100.0, descender_y=300.0)

    import handwriting_plotter.capture.models as capture_models

    monkeypatch.setattr(capture_models, "MAX_POINTS_PER_STROKE", 2)
    with pytest.raises(ValidationError, match="too many points"):
        replace(sample_session().samples[0].strokes[0], stroke_id="too-many")

