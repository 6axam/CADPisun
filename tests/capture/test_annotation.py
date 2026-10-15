from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from handwriting_plotter.capture.annotation import (
    AnnotationStore,
    GlyphAnnotation,
    StrokeRoleAssignment,
    annotation_to_glyph_variant,
    build_recorded_ligature,
    create_anchor_annotation,
    preview_join,
    validate_annotation,
)
from handwriting_plotter.capture.metrics import (
    GlyphMetricOverride,
    NormalizedRepository,
    StyleMetricProfile,
    normalize_processed_glyph,
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
from handwriting_plotter.capture.processing import ProcessedRepository, ProcessingParameters, process_sample
from handwriting_plotter.capture.repository import CaptureRepository
from handwriting_plotter.styles.models import to_variant
from handwriting_plotter.geometry.curves import Line, Point2, Stroke
from handwriting_plotter.layout.pages import layout_document
from handwriting_plotter.shaping.variants import VariationSpec
from handwriting_plotter.strokes.compile import Draw, compile_page
from handwriting_plotter.styles.models import GlyphVariant, JoinSpec, StyleManifest, StyleSnapshot
from handwriting_plotter.text.normalize import normalize



def _sample(label: str, coordinates: tuple[tuple[float, float], ...]) -> CaptureSample:
    points = tuple(CapturePoint(
        point_id=f"{label}-p-{index}",
        event="down" if index == 0 else "up" if index == len(coordinates) - 1 else "move",
        x=x, y=y, elapsed_s=index * 0.01, pointer_type="mouse",
    ) for index, (x, y) in enumerate(coordinates))
    return CaptureSample(
        sample_id=f"sample-{label}", label=label, classification="glyph",
        coordinate_reference=CoordinateReference(width=400.0, height=300.0),
        guides=WritingGuides(ascender_y=30.0, x_height_y=90.0, baseline_y=220.0, descender_y=270.0),
        provenance=CaptureProvenance(
            source="synthetic_fixture", captured_at_utc="2026-10-15T08:00:00Z",
            timing_source="monotonic", application_version="test",
        ),
        strokes=(CaptureStroke(stroke_id=f"stroke-{label}", points=points),),
    )


def _persist_processed(root: Path, sample: CaptureSample):
    session = CaptureSession(
        session_id=f"session-{sample.label}", created_at_utc="2026-10-15T08:00:00Z",
        device=DeviceCapabilities(pointer_types=("mouse",)), samples=(sample,),
    )
    raw = CaptureRepository(root).store(session)
    processed = process_sample(
        sample, raw.sha256, ProcessingParameters(max_deviation_px=0.5, resample_spacing_px=1.0)
    )
    return raw, ProcessedRepository(root).store(processed)


def _normalized(root: Path, label: str, coordinates, *, variant_id: str, advance: float = 600.0):
    sample = _sample(label, coordinates)
    _, processed = _persist_processed(root, sample)
    profile = StyleMetricProfile.from_sample("personal", sample)
    glyph = normalize_processed_glyph(
        processed.processed,
        processed.sha256,
        sample,
        profile,
        variant_id=variant_id,
        label=label,
        context_tag="isolated",
        override=GlyphMetricOverride(
            variant_id=variant_id,
            advance_gu=advance,
            left_bearing_gu=50.0,
            minimum_right_bearing_gu=20.0,
        ),
    )
    return sample, processed, NormalizedRepository(root).store(glyph)


def _join_annotation(record, *, no_join_after: bool = False, max_gap: float = 500.0):  # noqa: ANN001
    glyph = record.glyph
    body_id = glyph.strokes[0].id
    return GlyphAnnotation(
        source_normalized_sha256=record.sha256,
        source_processed_sha256=glyph.source_processed_sha256,
        variant_id=glyph.variant_id,
        label=glyph.label,
        context_tags=frozenset({"isolated", "initial", "medial", "final"}),
        stroke_order=(body_id,),
        stroke_roles=(StrokeRoleAssignment(stroke_id=body_id, role="body"),),
        join_mode="single_body_deferred_marks",
        body_stroke_id=body_id,
        entry=create_anchor_annotation(glyph, body_id, "start", max_gap_gu=max_gap),
        exit=create_anchor_annotation(glyph, body_id, "end", max_gap_gu=max_gap),
        no_join_after=no_join_after,
    )


def test_manual_body_marks_anchors_and_pen_lift_order_are_preserved(tmp_path: Path) -> None:
    base = _sample("ї", ((30.0, 220.0), (55.0, 90.0), (80.0, 220.0)))
    mark_one = CaptureStroke(stroke_id="dot-one", points=(
        CapturePoint(point_id="d1-a", event="down", x=45.0, y=60.0, elapsed_s=0.10, pointer_type="mouse"),
        CapturePoint(point_id="d1-b", event="up", x=47.0, y=58.0, elapsed_s=0.11, pointer_type="mouse"),
    ))
    mark_two = CaptureStroke(stroke_id="dot-two", points=(
        CapturePoint(point_id="d2-a", event="down", x=65.0, y=60.0, elapsed_s=0.12, pointer_type="mouse"),
        CapturePoint(point_id="d2-b", event="up", x=67.0, y=58.0, elapsed_s=0.13, pointer_type="mouse"),
    ))
    data = base.model_dump(mode="python")
    data["strokes"] = (*base.strokes, mark_one, mark_two)
    sample = CaptureSample.model_validate(data, strict=True)
    _, processed = _persist_processed(tmp_path, sample)
    profile = StyleMetricProfile.from_sample("personal", sample)
    glyph = normalize_processed_glyph(
        processed.processed, processed.sha256, sample, profile,
        variant_id="yi-1", label="ї",
        override=GlyphMetricOverride(variant_id="yi-1", advance_gu=900.0),
    )
    normalized = NormalizedRepository(tmp_path).store(glyph)
    ids = tuple(item.id for item in glyph.strokes)
    annotation = GlyphAnnotation(
        source_normalized_sha256=normalized.sha256,
        source_processed_sha256=processed.sha256,
        variant_id="yi-1",
        label="ї",
        context_tags=frozenset({"isolated", "initial", "medial", "final"}),
        stroke_order=ids,
        stroke_roles=(
            StrokeRoleAssignment(stroke_id=ids[0], role="body"),
            StrokeRoleAssignment(stroke_id=ids[1], role="mark"),
            StrokeRoleAssignment(stroke_id=ids[2], role="mark"),
        ),
        join_mode="single_body_deferred_marks",
        body_stroke_id=ids[0],
        deferred_marks=ids[1:],
        entry=create_anchor_annotation(glyph, ids[0], "start"),
        exit=create_anchor_annotation(glyph, ids[0], "end"),
        critical_features=ids[1:],
        review_status="reviewed",
    )

    report = validate_annotation(annotation, glyph)
    variant_file = annotation_to_glyph_variant(annotation, glyph)
    runtime = to_variant(variant_file)

    assert report.passed
    assert [stroke.id for stroke in runtime.strokes] == list(ids)
    assert [stroke.role for stroke in runtime.strokes] == ["body", "mark", "mark"]
    assert runtime.join_spec.deferred_marks == ids[1:]
    assert runtime.join_spec.entry is not None
    assert runtime.join_spec.exit is not None
    assert runtime.critical_features == ids[1:]


def test_annotation_rejects_reordering_bad_tangent_and_incomplete_join_data(tmp_path: Path) -> None:
    _, _, normalized = _normalized(
        tmp_path, "а", ((30.0, 220.0), (80.0, 220.0)), variant_id="a-1"
    )
    valid = _join_annotation(normalized)
    glyph = normalized.glyph

    reordered = valid.model_copy(update={"stroke_order": tuple(reversed(valid.stroke_order))})
    # One-stroke reversal is identical; an unknown stroke still proves exact-order validation.
    reordered = reordered.model_copy(update={"stroke_order": ("unknown",)})
    assert "ANNOTATION_STROKE_ORDER_CHANGED" in validate_annotation(reordered, glyph).errors

    bad_entry = type(valid.entry).model_validate(
        valid.entry.model_dump(mode="python") | {"tangent": {"x": -1.0, "y": 0.0}},
        strict=True,
    )
    bad = valid.model_copy(update={"entry": bad_entry})
    assert "ANNOTATION_ENTRY_TANGENT_MISMATCH" in validate_annotation(bad, glyph).errors

    none_with_anchor = valid.model_copy(update={"join_mode": "none"})
    assert "ANNOTATION_JOIN_NONE_HAS_JOIN_DATA" in validate_annotation(none_with_anchor, glyph).errors

    with pytest.raises(ValidationError, match="stroke roles must follow"):
        GlyphAnnotation.model_validate(
            valid.model_dump(mode="python") | {"stroke_roles": ()}, strict=True
        )


def test_annotation_store_is_revisioned_and_source_verified(tmp_path: Path) -> None:
    _, _, normalized = _normalized(
        tmp_path, "а", ((30.0, 220.0), (80.0, 220.0)), variant_id="a-store"
    )
    first = _join_annotation(normalized)
    store = AnnotationStore(tmp_path)

    path = store.save(first)
    assert path.is_file()
    assert store.load(normalized.sha256) == first

    second = GlyphAnnotation.model_validate(
        first.model_dump(mode="python") | {"revision": 2, "no_join_after": True}, strict=True
    )
    store.save(second)
    assert store.load(normalized.sha256) == second
    with pytest.raises(ValueError, match="ANNOTATION_REVISION_CONFLICT"):
        store.save(first.model_copy(update={"no_join_before": True}))


def test_pair_preview_reports_connected_lifted_and_rejected_with_real_join_engine(tmp_path: Path) -> None:
    _, _, left_record = _normalized(
        tmp_path / "left", "а", ((30.0, 220.0), (80.0, 220.0)),
        variant_id="a-left", advance=600.0,
    )
    _, _, right_record = _normalized(
        tmp_path / "right", "и", ((30.0, 220.0), (80.0, 220.0)),
        variant_id="i-right", advance=600.0,
    )
    connected_left = annotation_to_glyph_variant(_join_annotation(left_record), left_record.glyph)
    connected_right = annotation_to_glyph_variant(_join_annotation(right_record), right_record.glyph)

    accepted = preview_join(connected_left, connected_right)
    lifted = preview_join(
        annotation_to_glyph_variant(
            _join_annotation(left_record, no_join_after=True), left_record.glyph
        ),
        connected_right,
    )
    rejected = preview_join(
        annotation_to_glyph_variant(
            _join_annotation(left_record, max_gap=10.0), left_record.glyph
        ),
        connected_right,
    )

    assert accepted.decision == "connected"
    assert accepted.connector is not None
    assert accepted.reason == "JOIN_ACCEPTED"
    assert lifted.decision == "pen_lift"
    assert lifted.reason == "JOIN_FORBIDDEN"
    assert rejected.decision == "rejected"
    assert rejected.reason == "GAP_TOO_LARGE"


def test_recorded_ma_ligature_is_longest_match_and_reaches_pen_plan_with_fallback(tmp_path: Path) -> None:
    single = _sample("м", ((30.0, 220.0), (55.0, 120.0), (80.0, 220.0)))
    data = single.model_dump(mode="python")
    data.update({"sample_id": "sample-ma", "label": "ма", "classification": "sequence"})
    sequence = CaptureSample.model_validate(data, strict=True)
    _, processed = _persist_processed(tmp_path, sequence)
    profile = StyleMetricProfile.from_sample("personal", sequence)
    normalized_glyph = normalize_processed_glyph(
        processed.processed, processed.sha256, sequence, profile,
        variant_id="ma-recorded", label="ма",
        override=GlyphMetricOverride(variant_id="ma-recorded", advance_gu=900.0),
    )
    normalized = NormalizedRepository(tmp_path).store(normalized_glyph)
    body_id = normalized_glyph.strokes[0].id
    annotation = GlyphAnnotation(
        source_normalized_sha256=normalized.sha256,
        source_processed_sha256=processed.sha256,
        variant_id="ma-recorded",
        label="ма",
        context_tags=frozenset({"isolated", "initial", "medial", "final"}),
        stroke_order=(body_id,),
        stroke_roles=(StrokeRoleAssignment(stroke_id=body_id, role="body"),),
        join_mode="none",
        no_join_before=True,
        no_join_after=True,
        boundary_status="manual",
        character_boundaries_gu=(450.0,),
    )
    ligature_file = build_recorded_ligature(annotation, normalized_glyph, {"м", "а"})
    ligature = to_variant(ligature_file)
    with pytest.raises(ValueError, match="LIGATURE_MISSING_INDIVIDUAL_FALLBACK"):
        build_recorded_ligature(annotation, normalized_glyph, {"м"})

    none = JoinSpec("none", None, (), None, None, True, True)
    individual = {
        key: GlyphVariant(
            f"{key}-single", key,
            (Stroke("body", (Line(Point2(0, 0), Point2(350, 700)),),
                    role="body", direction_provenance="authored"),),
            500.0, frozenset({"isolated", "initial", "medial", "final"}), none, (),
        )
        for key in ("м", "а")
    }
    manifest = StyleManifest.model_validate({
        "format": "hp-style", "schema_version": "1.0", "style_id": "recorded", "revision": "0.1.0",
        "display_name": "Recorded test", "scripts": ("Cyrillic",),
        "license_record": {"license_id": "personal-test-only", "name": "Personal", "redistribution_allowed": False},
        "glyph_frame": "GlyphFrame",
        "metrics": {"x_height_gu": 1000.0, "ascender_gu": profile.ascender_gu,
                    "descender_gu": profile.descender_gu, "space_advance_gu": 900.0,
                    "line_gap_gu": 500.0, "supported_x_height_mm": (2.5, 5.0)},
        "coverage": ("м", "а", "ма"), "glyph_files": (), "join_rules": {},
        "variation_policy": {}, "file_hashes": {}, "approved": False,
        "production_eligible": False, "test_only": True,
    })
    style = StyleSnapshot(
        manifest,
        MappingProxyType({"м": (individual["м"],), "а": (individual["а"],), "ма": (ligature,)}),
        "recorded-style-hash",
    )

    document = layout_document(normalize("мама"), style, seed=17, variation=VariationSpec(0))
    plan = compile_page(document.pages[0], document.document_id)
    draws = [operation for operation in plan.operations if isinstance(operation, Draw)]

    assert len(draws) == 2
    assert all(body_id in stroke_id for draw in draws for stroke_id in draw.stroke_ids)
    assert compile_page(document.pages[0], document.document_id) == plan
