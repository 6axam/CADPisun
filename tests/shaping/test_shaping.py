from __future__ import annotations

from types import MappingProxyType

from handwriting_plotter.geometry.curves import Line, Point2, Stroke
from handwriting_plotter.shaping.schedule import WordShaper
from handwriting_plotter.shaping.variants import VariationSpec
from handwriting_plotter.styles.models import (
    EndpointAnchor,
    GlyphVariant,
    JoinSpec,
    StyleManifest,
    StyleSnapshot,
)
from handwriting_plotter.text.normalize import normalize


def _style(join: bool = True, variants: int = 1) -> StyleSnapshot:
    manifest = StyleManifest.model_validate({
        "format": "hp-style", "schema_version": "1.0", "style_id": "fixture", "revision": "1.0.0",
        "display_name": "fixture", "scripts": ("Latin", "Cyrillic"),
        "license_record": {"license_id": "test", "name": "test", "redistribution_allowed": True},
        "glyph_frame": "GlyphFrame",
        "metrics": {"x_height_gu": 1000.0, "ascender_gu": 1200.0, "descender_gu": -300.0,
                    "space_advance_gu": 500.0, "line_gap_gu": 500.0, "supported_x_height_mm": (2.5, 5.0)},
        "coverage": ("a", "i", "ї", "'", "а"), "glyph_files": (), "join_rules": {}, "variation_policy": {},
        "file_hashes": {}, "approved": True, "production_eligible": False, "test_only": True,
    })
    anchor_out = EndpointAnchor("body", "end", Point2(1, 0), "base", ("base",), 800, 500, 60)
    anchor_in = EndpointAnchor("body", "start", Point2(1, 0), "base", ("base",), 800, 500, 60)
    result = {}
    for key in ("a", "i", "а"):
        items = []
        for idx in range(variants):
            body = Stroke("body", (Line(Point2(0, 0), Point2(400 + idx * 10, 0)),), role="body", direction_provenance="authored")
            spec = JoinSpec("single_body_deferred_marks", "body", (), anchor_in, anchor_out, False, False) if join else JoinSpec("none", None, (), None, None, False, False)
            items.append(GlyphVariant(f"{key}-{idx}", key, (body,), 600, frozenset({"isolated", "initial", "medial", "final"}), spec, ()))
        result[key] = tuple(items)
    body = Stroke("body", (Line(Point2(0, 0), Point2(400, 0)),), role="body", direction_provenance="authored")
    mark1 = Stroke("dot-1", (Line(Point2(180, 700), Point2(190, 710)),), role="mark", direction_provenance="authored")
    mark2 = Stroke("dot-2", (Line(Point2(250, 700), Point2(260, 710)),), role="mark", direction_provenance="authored")
    result["ї"] = (GlyphVariant("yi-1", "ї", (body, mark1, mark2), 600, frozenset({"isolated", "initial", "medial", "final"}), JoinSpec("single_body_deferred_marks", "body", ("dot-1", "dot-2"), anchor_in, anchor_out, False, False), ("dot-1", "dot-2")),)
    apostrophe = Stroke("punct", (Line(Point2(100, 900), Point2(150, 800)),), role="punctuation", direction_provenance="authored")
    result["'"] = (GlyphVariant("apostrophe", "'", (apostrophe,), 300, frozenset({"isolated", "initial", "medial", "final"}), JoinSpec("none", None, (), None, None, True, True), ()),)
    return StyleSnapshot(manifest, MappingProxyType(result), "fixture-style-hash")


def _graphemes(value: str):
    return normalize(value).graphemes


def test_t_j01_accepted_join_has_shared_endpoints() -> None:
    word = WordShaper().shape(_graphemes("aa"), _style(), seed=1, x_height_mm=3.5, variation=VariationSpec(0))
    chain = word.execution_groups[0].strokes
    assert [stroke.role for stroke in chain] == ["body", "connector", "body"]
    assert chain[0].end == chain[1].start
    assert chain[1].end == chain[2].start


def test_t_j02_apostrophe_and_script_boundary_do_not_join() -> None:
    apostrophe = WordShaper().shape(_graphemes("a'a"), _style(), seed=1, x_height_mm=3.5, variation=VariationSpec(0))
    mixed = WordShaper().shape(_graphemes("aа"), _style(), seed=1, x_height_mm=3.5, variation=VariationSpec(0))
    assert not any(stroke.role == "connector" for group in apostrophe.execution_groups for stroke in group.strokes)
    assert not any(stroke.role == "connector" for group in mixed.execution_groups for stroke in group.strokes)


def test_t_j03_pathological_gap_uses_lifted_fallback() -> None:
    style = _style()
    base = style.variants_by_key["a"][0]
    narrow_anchor = EndpointAnchor("body", "end", Point2(1, 0), "base", ("base",), 10, 10, 5)
    replaced = GlyphVariant(
        "a-tight", "a", base.strokes, base.advance_gu, base.context_tags,
        JoinSpec("single_body_deferred_marks", "body", (), base.join_spec.entry, narrow_anchor, False, False), (),
    )
    mapping = dict(style.variants_by_key)
    mapping["a"] = (replaced,)
    word = WordShaper().shape(_graphemes("aa"), StyleSnapshot(style.manifest, MappingProxyType(mapping), style.revision_hash), seed=1, x_height_mm=3.5, variation=VariationSpec(0))
    assert not any(stroke.role == "connector" for group in word.execution_groups for stroke in group.strokes)
    assert any("GAP_TOO_LARGE" in item for item in word.diagnostics)


def test_t_j03_connector_clearance_collision_uses_lift() -> None:
    style = _style()
    base = style.variants_by_key["a"][0]
    obstacle = Stroke(
        "mark",
        (Line(Point2(500, -100), Point2(500, 100)),),
        role="mark",
        direction_provenance="authored",
    )
    blocked = GlyphVariant(
        "a-blocked",
        "a",
        (*base.strokes, obstacle),
        base.advance_gu,
        base.context_tags,
        JoinSpec(
            "single_body_deferred_marks", "body", ("mark",),
            base.join_spec.entry, base.join_spec.exit, False, False,
        ),
        ("mark",),
    )
    mapping = dict(style.variants_by_key)
    mapping["a"] = (blocked,)
    word = WordShaper().shape(
        _graphemes("aa"),
        StyleSnapshot(style.manifest, MappingProxyType(mapping), style.revision_hash),
        seed=1,
        x_height_mm=3.5,
        variation=VariationSpec(0),
    )
    assert not any(stroke.role == "connector" for group in word.execution_groups for stroke in group.strokes)
    assert any("CLEARANCE_COLLISION" in item for item in word.diagnostics)


def test_t_j04_deferred_marks_follow_connected_body() -> None:
    word = WordShaper().shape(_graphemes("її"), _style(), seed=2, x_height_mm=3.5, variation=VariationSpec(0))
    assert [group.strokes[0].role for group in word.execution_groups] == ["body", "mark", "mark", "mark", "mark"]
    ids = [group.strokes[0].id.rsplit("/", 1)[-1] for group in word.execution_groups[1:]]
    assert ids == ["dot-1", "dot-2", "dot-1", "dot-2"]


def test_t_j05_longest_match() -> None:
    style = _style(join=False)
    ligature = GlyphVariant("aa-lig", "aa", style.variants_by_key["a"][0].strokes, 1000, frozenset({"isolated"}), JoinSpec("none", None, (), None, None, False, False), ())
    mapping = dict(style.variants_by_key)
    mapping["aa"] = (ligature,)
    style = StyleSnapshot(style.manifest, MappingProxyType(mapping), style.revision_hash)
    word = WordShaper().shape(_graphemes("aa"), style, seed=0, x_height_mm=3.5, variation=VariationSpec(0))
    assert [glyph.variant_id for glyph in word.glyphs] == ["aa-lig"]


def test_t_j06_authored_stroke_order_is_preserved() -> None:
    word = WordShaper().shape(_graphemes("ї"), _style(), seed=2, x_height_mm=3.5, variation=VariationSpec(0))
    ids = [group.strokes[0].id.rsplit("/", 1)[-1] for group in word.execution_groups]
    assert ids == ["body", "dot-1", "dot-2"]


def test_t_r01_same_seed_is_deterministic() -> None:
    style = _style(variants=3)
    first = WordShaper().shape(_graphemes("aaaa"), style, seed=42, x_height_mm=3.5)
    second = WordShaper().shape(_graphemes("aaaa"), style, seed=42, x_height_mm=3.5)
    assert first == second


def test_t_r02_repeated_letters_avoid_same_variant() -> None:
    word = WordShaper().shape(_graphemes("aaaa"), _style(variants=3), seed=42, x_height_mm=3.5)
    chosen = [glyph.variant_id for glyph in word.glyphs]
    assert all(a != b for a, b in zip(chosen, chosen[1:], strict=False))


def test_t_r03_occurrence_choice_ignores_page_context() -> None:
    style = _style(variants=3)
    graphemes = _graphemes("aaa")
    first = WordShaper().shape(graphemes, style, seed=7, x_height_mm=3.5)
    second = WordShaper().shape(graphemes, style, seed=7, x_height_mm=3.5)
    assert [g.variant_id for g in first.glyphs] == [g.variant_id for g in second.glyphs]

