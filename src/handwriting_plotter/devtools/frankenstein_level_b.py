#!/usr/bin/env python3
"""Generate the explicit synthetic-only Project Frankenstein Level B review bundle."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree

from handwriting_plotter.application.resources import style_root
from handwriting_plotter.capture.annotation import AnnotationStore, GlyphAnnotation, StrokeRoleAssignment
from handwriting_plotter.capture.drafts import DraftCatalog, DraftEvent, DraftStore, VariantDraft
from handwriting_plotter.capture.metrics import (
    GlyphMetricOverride,
    MetricProfileStore,
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
from handwriting_plotter.domain.models import canonical_json_bytes
from handwriting_plotter.gui.backend import GuiBackend
from handwriting_plotter.gui.document import (
    ProjectSnapshot,
    TextObject,
    load_project_file,
    save_project,
)
from handwriting_plotter.storage.files import publish_bundle
from handwriting_plotter.styles.repository import CompositeStyleRepository

STYLE_ID = "frankenstein-synthetic"
STYLE_REVISION = "0.1.0"
WORDS = ("мама", "мимо", "мана", "мина")
TEXT = "\n".join(WORDS)
EXPECTED_SOURCE_COVERAGE = sum(map(len, WORDS)) + len(WORDS) - 1
FIXTURE_TIME = "2026-10-16T08:00:00Z"
GUIDES = WritingGuides(
    ascender_y=30.0,
    x_height_y=90.0,
    baseline_y=220.0,
    descender_y=270.0,
)

COORDINATES: tuple[tuple[str, str, tuple[tuple[float, float], ...]], ...] = (
    ("а", "a-isolated-1", ((30, 220), (43, 155), (55, 90), (68, 155), (82, 220))),
    ("м", "m-isolated-1", ((30, 220), (45, 110), (60, 185), (75, 110), (92, 220))),
    ("м", "m-isolated-2", ((30, 220), (47, 105), (63, 178), (79, 116), (96, 220))),
    ("и", "i-isolated-1", ((30, 220), (44, 130), (64, 207), (80, 120), (96, 220))),
    ("н", "n-isolated-1", ((30, 220), (30, 110), (55, 180), (82, 110), (82, 220))),
    ("о", "o-isolated-1", ((30, 190), (48, 135), (78, 145), (88, 190), (58, 210), (30, 190))),
)


@dataclass(frozen=True, slots=True)
class ReviewBundleResult:
    output: Path
    style_revision_hash: str
    generated_document_id: str
    artifact_hashes: dict[str, str]


def _sample(label: str, variant_id: str, coordinates: tuple[tuple[float, float], ...]) -> CaptureSample:
    points = tuple(
        CapturePoint(
            point_id=f"{variant_id}-p{index}",
            event="down" if index == 0 else "up" if index == len(coordinates) - 1 else "move",
            x=float(x),
            y=float(y),
            elapsed_s=index * 0.02,
            pointer_type="mouse",
        )
        for index, (x, y) in enumerate(coordinates)
    )
    return CaptureSample(
        sample_id=f"sample-{variant_id}",
        label=label,
        classification="glyph",
        coordinate_reference=CoordinateReference(width=400.0, height=300.0),
        guides=GUIDES,
        provenance=CaptureProvenance(
            source="synthetic_fixture",
            captured_at_utc=FIXTURE_TIME,
            timing_source="monotonic",
            application_version="frankenstein-level-b-fixture",
        ),
        strokes=(CaptureStroke(stroke_id=f"stroke-{variant_id}", points=points),),
    )


def _record_style(studio_root: Path):  # noqa: ANN202
    raw_repository = CaptureRepository(studio_root)
    processed_repository = ProcessedRepository(studio_root)
    normalized_repository = NormalizedRepository(studio_root)
    annotation_store = AnnotationStore(studio_root)
    profile = StyleMetricProfile.from_sample(
        STYLE_ID, _sample(*COORDINATES[0]), preview_x_height_mm=3.5
    )
    MetricProfileStore(studio_root).save(profile)
    artifacts: list[tuple[str, Path, Path, Path, Path]] = []
    variants: list[VariantDraft] = []

    for index, (label, variant_id, coordinates) in enumerate(COORDINATES, 1):
        sample = _sample(label, variant_id, coordinates)
        session = CaptureSession(
            session_id=f"session-{variant_id}",
            created_at_utc=FIXTURE_TIME,
            device=DeviceCapabilities(pointer_types=("mouse",)),
            samples=(sample,),
            extensions={
                "cadpisun.frankenstein": {
                    "synthetic_fixture": True,
                    "quality_claim": "none",
                    "variant_id": variant_id,
                }
            },
        )
        raw = raw_repository.store(session)
        processed = processed_repository.store(process_sample(
            sample,
            raw.sha256,
            ProcessingParameters(max_deviation_px=0.5, resample_spacing_px=2.0),
        ))
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
                advance_gu=800.0,
                left_bearing_gu=50.0,
                minimum_right_bearing_gu=50.0,
            ),
        )
        normalized = normalized_repository.store(glyph)
        stroke_id = glyph.strokes[0].id
        annotation = GlyphAnnotation(
            source_normalized_sha256=normalized.sha256,
            source_processed_sha256=processed.sha256,
            variant_id=variant_id,
            label=label,
            context_tags=frozenset({"isolated", "initial", "medial", "final"}),
            stroke_order=(stroke_id,),
            stroke_roles=(StrokeRoleAssignment(stroke_id=stroke_id, role="body"),),
            join_mode="none",
            no_join_before=True,
            no_join_after=True,
            review_status="reviewed",
        )
        annotation_path = annotation_store.save(annotation)
        variants.append(VariantDraft(
            variant_id=variant_id,
            sample_id=sample.sample_id,
            capture_sha256=raw.sha256,
            label=label,
            context_tag="isolated",
            review_status="accepted",
            preferred=variant_id == "m-isolated-1",
            history=(
                DraftEvent(revision=1, action="captured", occurred_at_utc=FIXTURE_TIME),
                DraftEvent(revision=2, action="accepted", occurred_at_utc=FIXTURE_TIME),
            ),
        ))
        artifacts.append((variant_id, raw.path, processed.path, normalized.path, annotation_path))

    catalog = DraftCatalog(
        style_id=STYLE_ID,
        display_name="Project Frankenstein synthetic fixture",
        variants=tuple(variants),
    )
    DraftStore(studio_root).save(catalog)
    return profile, catalog, tuple(artifacts)


def _project() -> ProjectSnapshot:
    return ProjectSnapshot(
        project_id="frankenstein-level-b-synthetic-project",
        name="Project Frankenstein Level B synthetic review",
        objects=(TextObject(
            object_id="frankenstein-test-words",
            name="Required Ukrainian words",
            text=TEXT,
            x_mm=20.0,
            y_mm=25.0,
            frame_x_mm=20.0,
            frame_y_mm=25.0,
            frame_width_mm=100.0,
            frame_height_mm=60.0,
            x_height_mm=3.5,
            line_pitch_mm=9.0,
            style_id=STYLE_ID,
            style_revision=STYLE_REVISION,
            seed=11011,
            realism=0.35,
        ),),
    )


def _validate_generated(result, snapshot, style, *, project_reopen_passed: bool) -> dict:  # noqa: ANN001
    required = {
        "page-0001.svg",
        "page-0001.preview.svg",
        "page-0001.plan.json",
        "page-0001.motion.json",
        "page-0001.gcode",
        "report.json",
        "job-manifest.json",
    }
    if not required <= set(result.files):
        raise ValueError("REVIEW_BUNDLE_MISSING_GENERATED_ARTIFACT")
    for name in ("page-0001.svg", "page-0001.preview.svg"):
        root = ElementTree.fromstring(result.files[name])
        if not root.tag.endswith("svg") or not any(item.tag.endswith("path") for item in root.iter()):
            raise ValueError(f"INVALID_SVG:{name}")
    plan = json.loads(result.files["page-0001.plan.json"])
    draw_count = sum(item.get("op") == "draw" for item in plan["operations"])
    if draw_count < 16:
        raise ValueError("PEN_PLAN_LOST_GLYPH_STROKES")
    if result.report["source_coverage_count"] != EXPECTED_SOURCE_COVERAGE:
        raise ValueError("SOURCE_COVERAGE_MISMATCH")
    if not result.report["pages"][0]["gcode_roundtrip_passed"]:
        raise ValueError("GCODE_ROUNDTRIP_FAILED")
    if tuple(style.variants_by_key) != ("а", "и", "м", "н", "о"):
        raise ValueError("STYLE_COVERAGE_MISMATCH")
    if len(style.variants_by_key["м"]) != 2:
        raise ValueError("MULTIPLE_VARIANT_ACCEPTANCE_MISSING")
    return {
        "format": "hp-frankenstein-validation",
        "schema_version": "1.0",
        "fixture_kind": "synthetic",
        "human_handwriting_quality_verified": False,
        "required_words": WORDS,
        "input_matches_required_words": snapshot.objects[0].text == TEXT,
        "style_reference": f"{STYLE_ID}@{STYLE_REVISION}",
        "style_revision_hash": style.revision_hash,
        "coverage_keys": tuple(style.variants_by_key),
        "m_variant_count": len(style.variants_by_key["м"]),
        "source_coverage_count": result.report["source_coverage_count"],
        "pen_plan_draw_count": draw_count,
        "production_svg_parsed": True,
        "diagnostic_svg_parsed": True,
        "gcode_roundtrip_passed": True,
        "simulation_only": True,
        "hardware_verified": False,
        "deterministic_second_build": True,
        "project_reopen_passed": project_reopen_passed,
        "cached_generation_restored": project_reopen_passed,
        "fresh_reopen_build_matches": project_reopen_passed,
    }


def build_review_bundle(output: Path, *, overwrite: bool = False) -> ReviewBundleResult:
    """Build and atomically publish one fully validated synthetic review bundle."""
    with tempfile.TemporaryDirectory(prefix="cadpisun-frankenstein-") as directory:
        studio_root = Path(directory) / "studio"
        _, catalog, source_artifacts = _record_style(studio_root)
        published = PersonalStylePackBuilder(studio_root).publish(
            StylePackBuildRequest(
                style_id=STYLE_ID,
                revision=STYLE_REVISION,
                display_name="Project Frankenstein synthetic fixture",
                author_id="synthetic-integration-fixture",
                user_confirmed_review=True,
            ),
            catalog,
        )
        user_styles = studio_root / "styles"
        repository = CompositeStyleRepository((style_root(), user_styles))
        style = repository.load(STYLE_ID, STYLE_REVISION)
        snapshot = _project()
        backend = GuiBackend(style_roots=(style_root(), user_styles))
        first = backend.build(snapshot)
        second = GuiBackend(style_roots=(style_root(), user_styles)).build(snapshot)
        if first.files != second.files or first.report != second.report:
            raise ValueError("NONDETERMINISTIC_END_TO_END_OUTPUT")
        project_path = studio_root / "frankenstein-level-b.hplot.json"
        save_project(project_path, snapshot, first)
        reopened = load_project_file(project_path)
        if reopened.snapshot != snapshot or reopened.generation_result is None:
            raise ValueError("PROJECT_REOPEN_FAILED")
        if reopened.generation_result.files != first.files:
            raise ValueError("PROJECT_CACHE_RESTORE_MISMATCH")
        reopened_result = GuiBackend(style_roots=(style_root(), user_styles)).build(reopened.snapshot)
        if reopened_result.files != first.files:
            raise ValueError("PROJECT_REOPEN_GENERATION_MISMATCH")
        validation = _validate_generated(
            first, snapshot, style, project_reopen_passed=True
        )

        files: dict[str, bytes] = {
            "README.md": (
                "# Project Frankenstein Level B review bundle\n\n"
                "This bundle is generated from deterministic synthetic pointer traces. "
                "It validates integration only and makes no claim about human handwriting quality.\n\n"
                "The style is test-only, non-production, simulation-only, and not hardware verified.\n"
            ).encode("utf-8"),
            "project.hplot.json": project_path.read_bytes(),
            "validation.json": canonical_json_bytes(validation),
        }
        for variant_id, raw, processed, normalized, annotation in source_artifacts:
            files[f"captures/{variant_id}.hp-capture.json"] = raw.read_bytes()
            files[f"processed/{variant_id}.hp-processed.json"] = processed.read_bytes()
            files[f"normalized/{variant_id}.hp-normalized.json"] = normalized.read_bytes()
            files[f"annotations/{variant_id}.hp-annotation.json"] = annotation.read_bytes()
        for path in sorted(published.package_path.rglob("*")):
            if path.is_file():
                files[f"stylepack/{path.relative_to(published.package_path).as_posix()}"] = path.read_bytes()
        for name, content in first.files.items():
            files[f"generated/{name}"] = content
        records = tuple(
            {"path": name, "sha256": sha256(content).hexdigest(), "bytes": len(content)}
            for name, content in sorted(files.items())
        )
        files["review-bundle.json"] = canonical_json_bytes({
            "format": "hp-frankenstein-review-bundle",
            "schema_version": "1.0",
            "fixture_kind": "synthetic",
            "human_handwriting_quality_verified": False,
            "complete": True,
            "style_id": STYLE_ID,
            "style_revision": STYLE_REVISION,
            "style_revision_hash": published.revision_hash,
            "generated_document_id": first.document_id,
            "artifacts": records,
        })
        publish_bundle(output, files, overwrite=overwrite)
        return ReviewBundleResult(
            output=output,
            style_revision_hash=published.revision_hash,
            generated_document_id=first.document_id,
            artifact_hashes={name: sha256(content).hexdigest() for name, content in files.items()},
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = build_review_bundle(args.output, overwrite=args.overwrite)
    print(json.dumps({
        "output": str(result.output),
        "style_revision_hash": result.style_revision_hash,
        "generated_document_id": result.generated_document_id,
        "artifact_count": len(result.artifact_hashes),
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
