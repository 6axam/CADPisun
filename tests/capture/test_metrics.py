from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from handwriting_plotter.capture.metrics import (
    GlyphMetricOverride,
    MetricProfileStore,
    NormalizedRepository,
    StyleMetricProfile,
    load_normalized_bytes,
    metric_profile_sha256,
    normalize_processed_glyph,
    serialize_normalized,
)
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
    process_sample,
)
from handwriting_plotter.capture.repository import CaptureRepository


GUIDES = WritingGuides(ascender_y=30.0, x_height_y=90.0, baseline_y=220.0, descender_y=270.0)


def _sample(label: str, coordinates: tuple[tuple[float, float], ...]) -> CaptureSample:
    points = tuple(CapturePoint(
        point_id=f"{label}-p-{index}",
        event="down" if index == 0 else "up" if index == len(coordinates) - 1 else "move",
        x=x,
        y=y,
        elapsed_s=index * 0.01,
        pointer_type="mouse",
    ) for index, (x, y) in enumerate(coordinates))
    return CaptureSample(
        sample_id=f"sample-{label}",
        label=label,
        classification="glyph",
        coordinate_reference=CoordinateReference(width=400.0, height=300.0),
        guides=GUIDES,
        provenance=CaptureProvenance(
            source="synthetic_fixture", captured_at_utc="2026-10-15T08:00:00Z",
            timing_source="monotonic", application_version="test",
        ),
        strokes=(CaptureStroke(stroke_id=f"stroke-{label}", points=points),),
    )


def _persist_processed(root: Path, sample: CaptureSample):
    session = CaptureSession(
        session_id=f"session-{sample.label}",
        created_at_utc="2026-10-15T08:00:00Z",
        device=DeviceCapabilities(pointer_types=("mouse",)),
        samples=(sample,),
    )
    raw = CaptureRepository(root).store(session)
    processed = process_sample(
        sample, raw.sha256,
        ProcessingParameters(max_deviation_px=0.5, resample_spacing_px=1.0),
    )
    return raw, ProcessedRepository(root).store(processed)


def test_five_glyphs_share_baseline_x_height_and_preserve_relative_height(tmp_path: Path) -> None:
    samples = {
        "а": _sample("а", ((30.0, 220.0), (55.0, 90.0), (80.0, 220.0))),
        "м": _sample("м", ((30.0, 220.0), (45.0, 110.0), (60.0, 180.0), (75.0, 110.0), (90.0, 220.0))),
        "н": _sample("н", ((30.0, 220.0), (30.0, 110.0), (80.0, 220.0))),
        "о": _sample("о", ((30.0, 190.0), (50.0, 140.0), (80.0, 190.0), (50.0, 205.0), (30.0, 190.0))),
        "и": _sample("и", ((30.0, 220.0), (45.0, 130.0), (65.0, 210.0), (80.0, 120.0))),
    }
    profile = StyleMetricProfile.from_sample("personal", samples["а"])
    glyphs = {}
    for label, sample in samples.items():
        _, processed = _persist_processed(tmp_path, sample)
        glyphs[label] = normalize_processed_glyph(
            processed.processed, processed.sha256, sample, profile,
            variant_id=f"{label}-isolated-1", label=label,
        )

    assert profile.x_height_gu == 1000.0
    assert profile.scale_gu_per_px == pytest.approx(1000 / 130)
    assert all(glyph.metric_profile_sha256 == metric_profile_sha256(profile) for glyph in glyphs.values())
    assert all(glyph.units == "gu" for glyph in glyphs.values())
    assert glyphs["а"].bounds.min_y_gu == pytest.approx(0.0)
    assert glyphs["а"].bounds.max_y_gu == pytest.approx(1000.0)
    assert glyphs["м"].bounds.min_y_gu == pytest.approx(0.0)
    assert glyphs["о"].bounds.max_y_gu - glyphs["о"].bounds.min_y_gu < 600.0
    assert glyphs["о"].bounds.max_y_gu < glyphs["а"].bounds.max_y_gu


def test_manual_bearings_advance_baseline_and_physical_preview_are_explicit(tmp_path: Path) -> None:
    sample = _sample("а", ((30.0, 220.0), (55.0, 90.0), (80.0, 220.0)))
    _, processed = _persist_processed(tmp_path, sample)
    profile = StyleMetricProfile.from_sample("personal", sample, preview_x_height_mm=4.0)
    override = GlyphMetricOverride(
        variant_id="a-custom", advance_gu=1100.0, left_bearing_gu=100.0,
        minimum_right_bearing_gu=80.0, baseline_offset_gu=20.0,
    )

    glyph = normalize_processed_glyph(
        processed.processed, processed.sha256, sample, profile,
        variant_id="a-custom", label="а", context_tag="initial", override=override,
    )

    assert glyph.left_bearing_gu == pytest.approx(100.0)
    assert glyph.bounds.min_x_gu == pytest.approx(100.0)
    assert glyph.advance_gu == 1100.0
    assert glyph.right_bearing_gu >= 80.0
    assert glyph.bounds.min_y_gu == pytest.approx(20.0)
    physical = glyph.physical_preview_strokes()[0]
    assert physical.start.y == pytest.approx(-0.08)  # 20 gu at 4 mm x-height
    assert glyph.preview_x_height_mm == 4.0


def test_normalization_never_rescales_from_individual_bbox(tmp_path: Path) -> None:
    tall = _sample("а", ((20.0, 220.0), (50.0, 90.0), (80.0, 220.0)))
    short = _sample("о", ((20.0, 200.0), (50.0, 150.0), (80.0, 200.0)))
    profile = StyleMetricProfile.from_sample("personal", tall)
    _, tall_processed = _persist_processed(tmp_path, tall)
    _, short_processed = _persist_processed(tmp_path, short)

    tall_glyph = normalize_processed_glyph(
        tall_processed.processed, tall_processed.sha256, tall, profile,
        variant_id="tall", label="а",
    )
    short_glyph = normalize_processed_glyph(
        short_processed.processed, short_processed.sha256, short, profile,
        variant_id="short", label="о",
    )

    tall_height = tall_glyph.bounds.max_y_gu - tall_glyph.bounds.min_y_gu
    short_height = short_glyph.bounds.max_y_gu - short_glyph.bounds.min_y_gu
    assert tall_height == pytest.approx(1000.0)
    assert short_height == pytest.approx(50 * profile.scale_gu_per_px)
    assert short_height < tall_height


def test_profile_and_normalized_artifacts_round_trip_with_verified_sources(tmp_path: Path) -> None:
    sample = _sample("а", ((30.0, 220.0), (55.0, 90.0), (80.0, 220.0)))
    _, processed = _persist_processed(tmp_path, sample)
    profile = StyleMetricProfile.from_sample("personal", sample)
    profile_path = MetricProfileStore(tmp_path).save(profile)
    assert profile_path.is_file()
    assert MetricProfileStore(tmp_path).load("personal") == profile
    glyph = normalize_processed_glyph(
        processed.processed, processed.sha256, sample, profile,
        variant_id="a-1", label="а",
    )
    repository = NormalizedRepository(tmp_path)

    record = repository.store(glyph)

    assert repository.load(processed.sha256, record.sha256) == glyph
    assert repository.list_for_processed(processed.sha256) == (record,)
    assert load_normalized_bytes(serialize_normalized(glyph)) == glyph
    assert not list(tmp_path.rglob("*.tmp"))

    altered = json.loads(serialize_normalized(glyph))
    altered["bounds"]["min_x_gu"] += 1.0
    with pytest.raises(ValidationError, match="NORMALIZED_BOUNDS_MISMATCH"):
        load_normalized_bytes(json.dumps(altered).encode())

    conflicting = StyleMetricProfile.model_validate(
        profile.model_dump(mode="python") | {"revision": 3}, strict=True
    )
    with pytest.raises(ValueError, match="METRIC_PROFILE_REVISION_CONFLICT"):
        MetricProfileStore(tmp_path).save(conflicting)

    record.path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="NORMALIZED_HASH_MISMATCH"):
        repository.load(processed.sha256, record.sha256)


def test_normalization_rejects_small_advance_wrong_frame_and_invalid_profile(tmp_path: Path) -> None:
    sample = _sample("а", ((30.0, 220.0), (55.0, 90.0), (80.0, 220.0)))
    _, processed = _persist_processed(tmp_path, sample)
    profile = StyleMetricProfile.from_sample("personal", sample)

    with pytest.raises(ValueError, match="ADVANCE_TOO_SMALL_FOR_GLYPH"):
        normalize_processed_glyph(
            processed.processed, processed.sha256, sample, profile,
            variant_id="a-small", label="а",
            override=GlyphMetricOverride(variant_id="a-small", advance_gu=100.0),
        )
    mismatched = profile.model_copy(update={"source_frame_width_px": 500.0})
    with pytest.raises(ValueError, match="METRIC_FRAME_MISMATCH"):
        normalize_processed_glyph(
            processed.processed, processed.sha256, sample, mismatched,
            variant_id="a-frame", label="а",
        )
    with pytest.raises(ValidationError, match="1000 gu"):
        StyleMetricProfile.model_validate(
            profile.model_dump(mode="python") | {"x_height_gu": 900.0}, strict=True
        )
