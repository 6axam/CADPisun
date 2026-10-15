from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from handwriting_plotter.capture.annotation import AnnotationStore, GlyphAnnotation, StrokeRoleAssignment
from handwriting_plotter.capture.drafts import DraftCatalog, DraftEvent, VariantDraft
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
from handwriting_plotter.capture.style_builder import PersonalStylePackBuilder, StylePackBuildRequest
from handwriting_plotter.gui.styles import discover_styles
from handwriting_plotter.styles.repository import CompositeStyleRepository, FileStyleRepository


def _reviewed_draft(root: Path) -> DraftCatalog:
    sample = CaptureSample(
        sample_id="sample-a",
        label="а",
        classification="glyph",
        coordinate_reference=CoordinateReference(width=400.0, height=300.0),
        guides=WritingGuides(
            ascender_y=30.0, x_height_y=90.0, baseline_y=220.0, descender_y=270.0
        ),
        provenance=CaptureProvenance(
            source="synthetic_fixture",
            captured_at_utc="2026-10-15T12:00:00Z",
            timing_source="monotonic",
            application_version="test",
        ),
        strokes=(CaptureStroke(stroke_id="body", points=(
            CapturePoint(
                point_id="p0", event="down", x=30.0, y=220.0,
                elapsed_s=0.0, pointer_type="mouse",
            ),
            CapturePoint(
                point_id="p1", event="move", x=55.0, y=90.0,
                elapsed_s=0.1, pointer_type="mouse",
            ),
            CapturePoint(
                point_id="p2", event="up", x=80.0, y=220.0,
                elapsed_s=0.2, pointer_type="mouse",
            ),
        )),),
    )
    raw = CaptureRepository(root).store(CaptureSession(
        session_id="session-a",
        created_at_utc="2026-10-15T12:00:00Z",
        device=DeviceCapabilities(pointer_types=("mouse",)),
        samples=(sample,),
    ))
    processed = ProcessedRepository(root).store(process_sample(
        sample,
        raw.sha256,
        ProcessingParameters(max_deviation_px=0.5, resample_spacing_px=1.0),
    ))
    profile = StyleMetricProfile.from_sample("personal", sample)
    glyph = normalize_processed_glyph(
        processed.processed,
        processed.sha256,
        sample,
        profile,
        variant_id="a-isolated-1",
        label="а",
        context_tag="isolated",
        override=GlyphMetricOverride(variant_id="a-isolated-1", advance_gu=900.0),
    )
    normalized = NormalizedRepository(root).store(glyph)
    AnnotationStore(root).save(GlyphAnnotation(
        source_normalized_sha256=normalized.sha256,
        source_processed_sha256=processed.sha256,
        variant_id="a-isolated-1",
        label="а",
        context_tags=frozenset({"isolated"}),
        stroke_order=("body",),
        stroke_roles=(StrokeRoleAssignment(stroke_id="body", role="body"),),
        join_mode="none",
        review_status="reviewed",
    ))
    return DraftCatalog(
        style_id="personal",
        display_name="My writing",
        variants=(VariantDraft(
            variant_id="a-isolated-1",
            sample_id="sample-a",
            capture_sha256=raw.sha256,
            label="а",
            context_tag="isolated",
            review_status="accepted",
            preferred=True,
            history=(
                DraftEvent(
                    revision=1, action="captured", occurred_at_utc="2026-10-15T12:00:00Z"
                ),
                DraftEvent(
                    revision=2, action="accepted", occurred_at_utc="2026-10-15T12:01:00Z"
                ),
            ),
        ),),
    )


def _request(*, revision: str = "0.1.0", confirmed: bool = True) -> StylePackBuildRequest:
    return StylePackBuildRequest(
        style_id="personal",
        revision=revision,
        display_name="My writing",
        author_id="local-author",
        user_confirmed_review=confirmed,
    )


def test_reviewed_capture_publishes_loadable_immutable_test_style(tmp_path: Path) -> None:
    catalog = _reviewed_draft(tmp_path)
    builder = PersonalStylePackBuilder(tmp_path)

    missing_confirmation = builder.validate(_request(confirmed=False), catalog)
    assert "USER_REVIEW_CONFIRMATION_REQUIRED" in missing_confirmation.errors

    published = builder.publish(_request(), catalog)
    loaded = FileStyleRepository(tmp_path / "styles").load("personal", "0.1.0")

    assert published.revision_hash == loaded.revision_hash
    assert published.coverage == ("а",)
    assert loaded.manifest.test_only is True
    assert loaded.manifest.production_eligible is False
    assert loaded.manifest.approved is False
    assert loaded.variants_by_key["а"][0].variant_id == "a-isolated-1"
    glyph_file = loaded.manifest.glyph_files[0]
    assert (published.package_path / glyph_file).is_file()
    assert {
        "provenance.json", "review/coverage.json", "review/pairs.json"
    } <= set(loaded.manifest.file_hashes)
    assert published.package_path.parent.parent == tmp_path / "styles"
    assert (tmp_path / "drafts" / "stylepacks" / "personal").is_dir()
    with pytest.raises(ValueError, match="REVISION_CONFLICT"):
        builder.publish(_request(), catalog)


def test_user_pack_is_discoverable_with_builtins_and_ambiguous_refs_are_rejected(tmp_path: Path) -> None:
    catalog = _reviewed_draft(tmp_path)
    published = PersonalStylePackBuilder(tmp_path).publish(_request(), catalog)

    summaries = discover_styles(tmp_path / "styles")
    personal = next(item for item in summaries if item.reference == ("personal", "0.1.0"))
    assert personal.valid and personal.source == "user"
    assert any(item.source == "built-in" and item.valid for item in summaries)

    duplicate_root = tmp_path / "duplicate-styles"
    target = duplicate_root / "personal" / "0.1.0"
    target.parent.mkdir(parents=True)
    shutil.copytree(published.package_path, target)
    repository = CompositeStyleRepository((tmp_path / "styles", duplicate_root))
    with pytest.raises(ValueError, match="AMBIGUOUS_STYLE_REFERENCE"):
        repository.load("personal", "0.1.0")
    with pytest.raises(FileNotFoundError, match="STYLE_NOT_FOUND"):
        repository.load("missing", "9.9.9")
