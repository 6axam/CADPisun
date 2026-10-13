from __future__ import annotations

from pathlib import Path

from handwriting_plotter.application.service import GenerationRequest, HandwritingPlotterService
from handwriting_plotter.layout.pages import PageSpec
from handwriting_plotter.shaping.schedule import WordShaper
from handwriting_plotter.shaping.variants import VariationSpec
from handwriting_plotter.styles.repository import FileStyleRepository
from handwriting_plotter.text.normalize import normalize


ROOT = Path(__file__).parents[2]
STYLE_ROOT = ROOT / "assets" / "styles"
WORDS = ("Україна", "ґрунт", "мама", "привіт", "школа", "пишу", "ймовірність")
REQUESTED = set("авгґдеєиіїйлмнопрстушщя")
CORPUS_EXTRAS = set("кьУ")


def _style():
    return FileStyleRepository(STYLE_ROOT).load("ua-school-v1-pilot", "0.1.0")


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
