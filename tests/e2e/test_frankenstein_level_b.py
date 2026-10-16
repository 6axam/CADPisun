from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from handwriting_plotter.domain.models import strict_json_loads
from handwriting_plotter.gui.document import load_project_file
from handwriting_plotter.devtools.frankenstein_level_b import (
    EXPECTED_SOURCE_COVERAGE,
    STYLE_ID,
    STYLE_REVISION,
    TEXT,
    WORDS,
    build_review_bundle,
)


def _all_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_five_glyph_personal_style_generates_complete_deterministic_review_bundle(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_result = build_review_bundle(first)
    second_result = build_review_bundle(second)
    first_files = _all_files(first)
    second_files = _all_files(second)

    assert first_result.style_revision_hash == second_result.style_revision_hash
    assert first_result.generated_document_id == second_result.generated_document_id
    assert first_files == second_files
    assert (first / "generated" / "input.txt").read_text(encoding="utf-8") == TEXT

    validation = strict_json_loads((first / "validation.json").read_bytes())
    assert tuple(validation["required_words"]) == WORDS
    assert validation["fixture_kind"] == "synthetic"
    assert validation["human_handwriting_quality_verified"] is False
    assert validation["coverage_keys"] == ["а", "и", "м", "н", "о"]
    assert validation["m_variant_count"] == 2
    assert validation["source_coverage_count"] == EXPECTED_SOURCE_COVERAGE
    assert validation["pen_plan_draw_count"] == 16
    assert validation["production_svg_parsed"]
    assert validation["diagnostic_svg_parsed"]
    assert validation["gcode_roundtrip_passed"]
    assert validation["deterministic_second_build"]
    assert validation["project_reopen_passed"]
    assert validation["cached_generation_restored"]
    assert validation["fresh_reopen_build_matches"]
    assert validation["simulation_only"] and not validation["hardware_verified"]

    review = strict_json_loads((first / "review-bundle.json").read_bytes())
    assert review["complete"]
    assert review["style_id"] == STYLE_ID
    assert review["style_revision"] == STYLE_REVISION
    assert review["style_revision_hash"] == first_result.style_revision_hash
    for artifact in review["artifacts"]:
        content = (first / artifact["path"]).read_bytes()
        assert len(content) == artifact["bytes"]
        assert sha256(content).hexdigest() == artifact["sha256"]

    captures = sorted((first / "captures").glob("*.json"))
    processed = sorted((first / "processed").glob("*.json"))
    normalized = sorted((first / "normalized").glob("*.json"))
    annotations = sorted((first / "annotations").glob("*.json"))
    assert len(captures) == len(processed) == len(normalized) == len(annotations) == 6
    for capture in captures:
        data = strict_json_loads(capture.read_bytes())
        assert data["samples"][0]["provenance"]["source"] == "synthetic_fixture"
        assert data["extensions"]["cadpisun.frankenstein"]["quality_claim"] == "none"

    style_manifest = strict_json_loads((first / "stylepack" / "manifest.json").read_bytes())
    assert style_manifest["style_id"] == STYLE_ID
    assert style_manifest["revision"] == STYLE_REVISION
    assert style_manifest["coverage"] == ["а", "и", "м", "н", "о"]
    assert style_manifest["test_only"] is True
    assert style_manifest["approved"] is False
    assert style_manifest["production_eligible"] is False
    for relative, expected_hash in style_manifest["file_hashes"].items():
        assert sha256((first / "stylepack" / relative).read_bytes()).hexdigest() == expected_hash

    report = json.loads((first / "generated" / "report.json").read_text(encoding="utf-8"))
    assert report["complete"]
    assert report["pages"][0]["gcode_roundtrip_passed"]
    assert report["machine"]["simulation_only"]
    assert report["machine"]["hardware_verified"] is False
    assert report["blockers"] == ["BLK-STYLE-001"]

    reopened = load_project_file(first / "project.hplot.json")
    assert reopened.snapshot.objects[0].text == TEXT
    assert reopened.snapshot.objects[0].style_id == STYLE_ID
    assert reopened.snapshot.objects[0].style_revision == STYLE_REVISION
    assert reopened.generation_result is not None
    assert reopened.generation_result.files["page-0001.svg"] == (
        first / "generated" / "page-0001.svg"
    ).read_bytes()
