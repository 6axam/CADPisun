from __future__ import annotations

from types import MappingProxyType

import pytest

from handwriting_plotter.geometry.curves import Line, Point2, Stroke
from handwriting_plotter.layout.pages import PageSpec, layout_document
from handwriting_plotter.shaping.variants import VariationSpec
from handwriting_plotter.styles.models import GlyphVariant, JoinSpec, StyleManifest, StyleSnapshot
from handwriting_plotter.text.normalize import normalize


def _style(advance: float = 600) -> StyleSnapshot:
    keys = set("abcdefghijklmnopqrstuvwxyz.-")
    manifest = StyleManifest.model_validate({
        "format": "hp-style", "schema_version": "1.0", "style_id": "layout-fixture", "revision": "1.0.0",
        "display_name": "fixture", "scripts": ("Latin",),
        "license_record": {"license_id": "test", "name": "test", "redistribution_allowed": True},
        "glyph_frame": "GlyphFrame",
        "metrics": {"x_height_gu": 1000.0, "ascender_gu": 1000.0, "descender_gu": -250.0,
                    "space_advance_gu": 400.0, "line_gap_gu": 500.0, "supported_x_height_mm": (1.0, 10.0)},
        "coverage": tuple(sorted(keys)), "glyph_files": (), "join_rules": {}, "variation_policy": {},
        "file_hashes": {}, "approved": True, "production_eligible": False, "test_only": True,
    })
    spec = JoinSpec("none", None, (), None, None, False, False)
    variants = {}
    for key in keys:
        stroke = Stroke("body", (Line(Point2(0, 0), Point2(advance * 0.8, 1000)),), role="body", direction_provenance="authored")
        variants[key] = (GlyphVariant(key + "-1", key, (stroke,), advance, frozenset({"isolated", "initial", "medial", "final"}), spec, ()),)
    return StyleSnapshot(manifest, MappingProxyType(variants), "layout-style-hash")


def test_t_l01_short_line_inside_margins() -> None:
    result = layout_document(normalize("hello world"), _style(), seed=1, variation=VariationSpec(0))
    assert len(result.pages) == 1
    bounds = result.pages[0].ink_bounds
    assert bounds is not None
    assert 15 <= bounds.min_x <= bounds.max_x <= 195
    assert 15 <= bounds.min_y <= bounds.max_y <= 282


def test_t_l02_multiline_and_hard_breaks() -> None:
    result = layout_document(normalize("hello\n\nworld"), _style(), seed=1, variation=VariationSpec(0))
    assert len(result.pages[0].lines) == 2
    assert result.pages[0].lines[1].baseline_y_mm - result.pages[0].lines[0].baseline_y_mm >= 18


def test_t_l03_ten_pages_have_complete_source_coverage() -> None:
    spec = PageSpec(width_mm=40, height_mm=30, margin_left_mm=5, margin_right_mm=5, margin_top_mm=5, margin_bottom_mm=5, x_height_mm=3.5, line_pitch_mm=7)
    text = "\f".join("hello" for _ in range(10))
    source = normalize(text)
    result = layout_document(source, _style(), seed=1, page_spec=spec, variation=VariationSpec(0))
    assert len(result.pages) == 10
    assert set(result.source_coverage) == {item.id for item in source.graphemes}


def test_t_l04_oversized_word_splits_by_grapheme() -> None:
    spec = PageSpec(width_mm=20, height_mm=100, margin_left_mm=5, margin_right_mm=5, margin_top_mm=5, margin_bottom_mm=5, x_height_mm=3.5, line_pitch_mm=7)
    result = layout_document(normalize("abcdefghij"), _style(), seed=1, page_spec=spec, variation=VariationSpec(0))
    assert len(result.pages[0].lines) >= 2
    assert sum(len(word.shape.grapheme_ids) for line in result.pages[0].lines for word in line.words) == 10


def test_t_l05_single_oversized_glyph_fails() -> None:
    spec = PageSpec(width_mm=10, height_mm=100, margin_left_mm=4, margin_right_mm=4, margin_top_mm=5, margin_bottom_mm=5, x_height_mm=3.5)
    with pytest.raises(ValueError, match="GLYPH_TOO_WIDE"):
        layout_document(normalize("a"), _style(advance=2000), seed=1, page_spec=spec, variation=VariationSpec(0))


def test_t_l06_nbsp_overflow_is_not_silently_split() -> None:
    spec = PageSpec(width_mm=20, height_mm=100, margin_left_mm=5, margin_right_mm=5, margin_top_mm=5, margin_bottom_mm=5, x_height_mm=3.5)
    with pytest.raises(ValueError, match="NONBREAKABLE_OVERFLOW"):
        layout_document(normalize("hello\u00a0world"), _style(), seed=1, page_spec=spec, variation=VariationSpec(0))


def test_t_l07_negative_bearing_is_accounted_for() -> None:
    result = layout_document(normalize("a"), _style(), seed=1, variation=VariationSpec(0))
    assert result.pages[0].ink_bounds.min_x >= 15

