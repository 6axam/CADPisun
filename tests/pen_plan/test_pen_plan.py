from __future__ import annotations

from types import MappingProxyType
from xml.etree import ElementTree as ET

from handwriting_plotter.adapters.svg.preview import write_preview_svg
from handwriting_plotter.adapters.svg.writer import SVG_NS, write_production_svg
from handwriting_plotter.geometry.curves import Line, Point2, Stroke
from handwriting_plotter.layout.pages import layout_document
from handwriting_plotter.shaping.variants import VariationSpec
from handwriting_plotter.strokes.compile import Checkpoint, Draw, PenDown, PenUp, TravelTo, compile_page
from handwriting_plotter.strokes.simulate import simulate_pen_plan
from handwriting_plotter.strokes.validate import validate_pen_plan
from handwriting_plotter.styles.models import GlyphVariant, JoinSpec, StyleManifest, StyleSnapshot
from handwriting_plotter.text.normalize import normalize


def _page():
    keys = set("ab")
    manifest = StyleManifest.model_validate({
        "format": "hp-style", "schema_version": "1.0", "style_id": "pen-fixture", "revision": "1.0.0",
        "display_name": "fixture", "scripts": ("Latin",),
        "license_record": {"license_id": "test", "name": "test", "redistribution_allowed": True},
        "glyph_frame": "GlyphFrame",
        "metrics": {"x_height_gu": 1000.0, "ascender_gu": 1000.0, "descender_gu": -250.0,
                    "space_advance_gu": 400.0, "line_gap_gu": 500.0, "supported_x_height_mm": (1.0, 10.0)},
        "coverage": tuple(keys), "glyph_files": (), "join_rules": {}, "variation_policy": {}, "file_hashes": {},
        "approved": True, "production_eligible": False, "test_only": True,
    })
    spec = JoinSpec("none", None, (), None, None, False, False)
    variants = {key: (GlyphVariant(key, key, (Stroke("body", (Line(Point2(0, 0), Point2(500, 1000)),), role="body", direction_provenance="authored"),), 600, frozenset({"isolated", "initial", "medial", "final"}), spec, ()),) for key in keys}
    style = StyleSnapshot(manifest, MappingProxyType(variants), "pen-style-hash")
    document = layout_document(normalize("ab ba"), style, seed=1, variation=VariationSpec(0))
    return document.pages[0], document.document_id


def test_t_p01_state_sequence_and_final_up() -> None:
    page, document_id = _page()
    plan = compile_page(page, document_id)
    report = validate_pen_plan(plan)
    assert report.passed
    assert isinstance(plan.operations[-1], Checkpoint) and plan.operations[-1].scope == "page"
    for index, operation in enumerate(plan.operations):
        if isinstance(operation, TravelTo):
            assert index == 1 or isinstance(plan.operations[index - 1], (PenUp, Checkpoint))


def test_t_p02_each_group_has_travel_down_draw_up() -> None:
    page, document_id = _page()
    operations = compile_page(page, document_id).operations
    for index, operation in enumerate(operations):
        if isinstance(operation, Draw):
            assert isinstance(operations[index - 1], PenDown)
            assert isinstance(operations[index + 1], PenUp)


def test_t_p03_logical_simulation_completes() -> None:
    page, document_id = _page()
    report = simulate_pen_plan(compile_page(page, document_id))
    assert report.completion_state == "complete"
    assert report.drawn_length_mm > 0
    assert report.pen_lifts == 4


def test_t_e01_production_svg_is_valid_and_has_physical_size() -> None:
    page, document_id = _page()
    root = ET.fromstring(write_production_svg(page, compile_page(page, document_id)))
    assert root.attrib["width"] == "210.000mm"
    assert root.attrib["height"] == "297.000mm"
    assert root.attrib["data-role"] == "production"


def test_t_e02_production_svg_contains_only_draw_paths() -> None:
    page, document_id = _page()
    root = ET.fromstring(write_production_svg(page, compile_page(page, document_id)))
    paths = root.findall(f"{{{SVG_NS}}}path")
    assert len(paths) == 4
    assert all("stroke-dasharray" not in path.attrib for path in paths)
    assert not root.findall(f"{{{SVG_NS}}}text")


def test_t_e03_preview_is_unambiguously_diagnostic() -> None:
    page, document_id = _page()
    root = ET.fromstring(write_preview_svg(page, compile_page(page, document_id)))
    assert root.attrib["data-role"] == "diagnostic-preview"
    assert root.findall(f"{{{SVG_NS}}}text")
    assert any(path.attrib.get("data-role") == "travel" for path in root.findall(f"{{{SVG_NS}}}path"))

