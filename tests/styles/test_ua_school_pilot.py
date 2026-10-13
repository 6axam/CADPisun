from __future__ import annotations

from pathlib import Path

from handwriting_plotter.application.service import GenerationRequest, HandwritingPlotterService
from handwriting_plotter.geometry.bounds import curve_bounds
from handwriting_plotter.layout.pages import PageSpec
from handwriting_plotter.shaping.schedule import WordShaper
from handwriting_plotter.shaping.variants import VariationSpec
from handwriting_plotter.styles.repository import FileStyleRepository
from handwriting_plotter.text.normalize import normalize


ROOT = Path(__file__).parents[2]
STYLE_ROOT = ROOT / "assets" / "styles"
WORDS = ("Україна", "ґрунт", "мама", "привіт", "школа", "пишу", "ймовірність")
WORDS_V020 = WORDS + ("машина", "мишка", "тиша", "шишки", "написання")
REQUESTED = set("авгґдеєиіїйлмнопрстушщя")
CORPUS_EXTRAS = set("кьУ")


def _style():
    return FileStyleRepository(STYLE_ROOT).load("ua-school-v1-pilot", "0.1.0")


def _style_v020():
    return FileStyleRepository(STYLE_ROOT).load("ua-school-v1-pilot", "0.2.0")


def test_pilot_has_exact_review_corpus_coverage_and_is_not_production() -> None:
    style = _style()
    assert set(style.variants_by_key) == REQUESTED | CORPUS_EXTRAS
    assert all(character in style.variants_by_key for word in WORDS for character in word)
    assert style.manifest.test_only
    assert style.manifest.approved
    assert not style.manifest.production_eligible
    for key in ("а", "е", "и", "м", "о", "т"):
        assert len(style.variants_by_key[key]) == 2


def test_pilot_word_pairs_join_without_geometry_rejection() -> None:
    style = _style()
    for word in WORDS:
        shaped = WordShaper().shape(
            normalize(word).graphemes,
            style,
            seed=20261013,
            x_height_mm=4.0,
            pen_width_mm=0.35,
            variation=VariationSpec(0),
        )
        assert shaped.diagnostics == ()
        connector_count = sum(
            stroke.role == "connector"
            for group in shaped.execution_groups
            for stroke in group.strokes
        )
        expected = len(word) - 1 - (1 if word[0] == "У" else 0)
        assert connector_count == expected


def test_pilot_defers_all_critical_marks_until_after_body_chain() -> None:
    style = _style()
    for word in ("Україна", "ґрунт", "привіт", "ймовірність"):
        shaped = WordShaper().shape(
            normalize(word).graphemes,
            style,
            seed=1,
            x_height_mm=4.0,
            variation=VariationSpec(0),
        )
        groups = shaped.execution_groups
        for mark_index, group in enumerate(groups):
            for stroke in group.strokes:
                if stroke.role != "mark":
                    continue
                assert any(
                    body_index < mark_index
                    and any(
                        candidate.role == "body" and set(candidate.source_refs) == set(stroke.source_refs)
                        for candidate in body_group.strokes
                    )
                    for body_index, body_group in enumerate(groups)
                )


def test_pilot_generates_svg_penplan_motion_and_virtual_gcode(tmp_path: Path) -> None:
    service = HandwritingPlotterService(STYLE_ROOT)
    page = PageSpec(x_height_mm=4.0, line_pitch_mm=10.0)
    result = service.build("\n".join(WORDS), GenerationRequest(
        style_id="ua-school-v1-pilot",
        style_revision="0.1.0",
        seed=20261013,
        realism=0,
        page_spec=page,
    ))
    assert result.report["complete"]
    assert result.report["diagnostics"] == []
    assert result.report["blockers"] == ["BLK-STYLE-001"]
    assert b"<path" in result.files["page-0001.svg"]
    assert b"<text" not in result.files["page-0001.svg"]
    gcode = result.files["page-0001.gcode"]
    assert gcode.startswith(b"G21\nG90\nG94\n")
    assert b"G0 " not in gcode and b"M3" not in gcode and b"M5" not in gcode


def test_v020_preserves_v010_and_covers_the_extended_frozen_corpus() -> None:
    old = _style()
    revised = _style_v020()
    assert old.revision_hash == "9d764931b9e96630197292afc3185f3be49c3ce62a1814ae4e420d03951e3aae"
    assert old.manifest.revision == "0.1.0"
    assert revised.manifest.revision == "0.2.0"
    assert set(revised.variants_by_key) == REQUESTED | CORPUS_EXTRAS
    assert all(character in revised.variants_by_key for word in WORDS_V020 for character in word)
    assert revised.manifest.test_only and revised.manifest.approved
    assert not revised.manifest.production_eligible


def test_v020_problem_letters_have_distinct_full_height_authored_skeletons() -> None:
    style = _style_v020()
    signatures: dict[str, tuple[tuple[float, float], ...]] = {}
    for key in "ипнмтшщ":
        variant = next(
            item for item in style.variants_by_key[key]
            if "initial" in item.context_tags
        )
        body = next(stroke for stroke in variant.strokes if stroke.id == "body")
        bounds = curve_bounds(body.segments[0])
        for segment in body.segments[1:]:
            bounds = bounds.union(curve_bounds(segment))
        assert bounds.max_y >= 650
        signatures[key] = tuple(
            (round(segment.p1.x / variant.advance_gu, 3), round(segment.p1.y / 1000, 3))
            for segment in body.segments
        )
    assert len(set(signatures.values())) == len(signatures)


def test_v020_context_forms_and_marks_preserve_authored_lift_semantics() -> None:
    style = _style_v020()
    for key in "пмтшщ":
        initial = next(item for item in style.variants_by_key[key] if "initial" in item.context_tags)
        medial = next(item for item in style.variants_by_key[key] if "medial" in item.context_tags)
        final = next(item for item in style.variants_by_key[key] if "final" in item.context_tags)
        assert not initial.join_spec.no_join_before
        assert medial.join_spec.no_join_before
        assert final.join_spec.no_join_before and final.join_spec.no_join_after
        assert final.join_spec.exit is None
    expected_marks = {"ї": {"dot-left", "dot-right"}, "й": {"breve"}, "ґ": {"top-hook"}}
    for key, names in expected_marks.items():
        variant = next(item for item in style.variants_by_key[key] if "initial" in item.context_tags)
        assert {stroke.id for stroke in variant.strokes if stroke.role == "mark"} == names
        assert set(variant.join_spec.deferred_marks) == names


def test_v020_corpus_shapes_at_supported_review_sizes_without_geometry_rejection() -> None:
    style = _style_v020()
    intentional_lifts = 0
    for size in (3.0, 3.6, 4.0):
        for word in WORDS_V020:
            shaped = WordShaper().shape(
                normalize(word).graphemes,
                style,
                seed=20261013,
                x_height_mm=size,
                pen_width_mm=0.35,
                variation=VariationSpec(0),
            )
            assert all(item.endswith(":JOIN_FORBIDDEN") for item in shaped.diagnostics)
            intentional_lifts += len(shaped.diagnostics)
    assert intentional_lifts > 0


def test_v020_generates_verified_svg_penplan_motion_and_virtual_gcode() -> None:
    service = HandwritingPlotterService(STYLE_ROOT)
    result = service.build("\n".join(WORDS_V020), GenerationRequest(
        style_id="ua-school-v1-pilot",
        style_revision="0.2.0",
        seed=20261013,
        realism=0,
        page_spec=PageSpec(x_height_mm=3.6, line_pitch_mm=8.5),
    ))
    assert result.report["complete"]
    assert result.report["blockers"] == ["BLK-STYLE-001"]
    assert result.report["machine"]["simulation_only"]
    assert not result.report["machine"]["hardware_verified"]
    assert all(item.endswith(":JOIN_FORBIDDEN") for item in result.report["diagnostics"])
    svg = result.files["page-0001.svg"]
    assert b"<path" in svg and b"<text" not in svg and b"font" not in svg
    gcode = result.files["page-0001.gcode"]
    assert gcode.startswith(b"G21\nG90\nG94\n")
    assert b"G0 " not in gcode and b"M3" not in gcode and b"M5" not in gcode
