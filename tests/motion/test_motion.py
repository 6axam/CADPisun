from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from handwriting_plotter.adapters.gcode.parser import compare_decoded, decode_virtual_gcode
from handwriting_plotter.adapters.gcode.virtual_xyz import emit_virtual_gcode
from handwriting_plotter.geometry.curves import Cubic, Line, Point2, Stroke
from handwriting_plotter.layout.pages import layout_document
from handwriting_plotter.motion.limits import validate_motion_limits
from handwriting_plotter.motion.planning import MoveLinear, SetPen, expanded_operations, plan_virtual_page
from handwriting_plotter.motion.profiles import load_profile
from handwriting_plotter.motion.registration import virtual_registration
from handwriting_plotter.shaping.variants import VariationSpec
from handwriting_plotter.strokes.compile import compile_page
from handwriting_plotter.styles.models import GlyphVariant, JoinSpec, StyleManifest, StyleSnapshot
from handwriting_plotter.text.normalize import normalize


PROFILE_PATH = Path(__file__).parents[2] / "profiles" / "virtual-cartesian-z-v1.json"


def _inputs(short: bool = False):
    manifest = StyleManifest.model_validate({
        "format": "hp-style", "schema_version": "1.0", "style_id": "motion-fixture", "revision": "1.0.0",
        "display_name": "fixture", "scripts": ("Latin",),
        "license_record": {"license_id": "test", "name": "test", "redistribution_allowed": True},
        "glyph_frame": "GlyphFrame",
        "metrics": {"x_height_gu": 1000.0, "ascender_gu": 1000.0, "descender_gu": -250.0,
                    "space_advance_gu": 400.0, "line_gap_gu": 500.0, "supported_x_height_mm": (1.0, 10.0)},
        "coverage": ("a",), "glyph_files": (), "join_rules": {}, "variation_policy": {}, "file_hashes": {},
        "approved": True, "production_eligible": False, "test_only": True,
    })
    geometry = Line(Point2(0, 0), Point2(0.01, 0.01)) if short else Cubic(Point2(0, 0), Point2(100, 500), Point2(400, 500), Point2(500, 1000))
    variant = GlyphVariant("a", "a", (Stroke("body", (geometry,), role="body", direction_provenance="authored"),), 600, frozenset({"isolated"}), JoinSpec("none", None, (), None, None, False, False), ())
    style = StyleSnapshot(manifest, MappingProxyType({"a": (variant,)}), "motion-style-hash")
    document = layout_document(normalize("a"), style, seed=1, variation=VariationSpec(0))
    profile = load_profile(PROFILE_PATH)
    pen_plan = compile_page(document.pages[0], document.document_id)
    registration = virtual_registration(document.pages[0].page_id, profile)
    return profile, pen_plan, registration


def test_t_m01_page_to_work_reflects_y_and_stays_bounded() -> None:
    profile, pen_plan, registration = _inputs()
    motion = plan_virtual_page(pen_plan, profile, registration)
    assert not validate_motion_limits(motion, profile)
    assert motion.bounds_all_moves[0].x >= 0 and motion.bounds_all_moves[1].y <= 297


def test_t_m02_pen_actuation_expands_once_and_separates_axes() -> None:
    profile, pen_plan, registration = _inputs()
    motion = plan_virtual_page(pen_plan, profile, registration)
    set_pens = [item for item in motion.operations if isinstance(item, SetPen)]
    assert [item.target_state for item in set_pens] == ["DOWN", "UP"]
    assert all(len(item.expansion) == 2 for item in set_pens)
    assert all(isinstance(item, MoveLinear) for item in expanded_operations(motion) if isinstance(item, MoveLinear))


def test_t_m03_gcode_roundtrip_matches_expanded_plan() -> None:
    profile, pen_plan, registration = _inputs()
    motion = plan_virtual_page(pen_plan, profile, registration)
    artifact = emit_virtual_gcode(motion)
    decoded = decode_virtual_gcode(artifact.content, profile)
    assert not compare_decoded(motion, decoded)
    assert artifact.simulation_only


def test_t_m04_resolution_and_profile_hash_failures() -> None:
    profile, pen_plan, registration = _inputs(short=True)
    with pytest.raises(ValueError, match="RESOLUTION_INSUFFICIENT"):
        plan_virtual_page(pen_plan, profile, registration)
    profile, pen_plan, registration = _inputs()
    with pytest.raises(ValueError, match="MISMATCH"):
        plan_virtual_page(pen_plan, profile, replace(registration, profile_revision_hash="bad"))


@pytest.mark.parametrize("payload", [
    b"G21\nG90\nG94\nG0 X1 Y1 F10\n",
    b"G21\nG90\nG94\nM3\n",
    b"G21\nG90\nG94\nG1 X1 Y1 Z2 F10\n",
    b"G21\nG90\nG94\nG1 X1 Y1 F10\x00\n",
])
def test_t_m05_control_and_unknown_commands_are_rejected(payload: bytes) -> None:
    with pytest.raises(ValueError):
        decode_virtual_gcode(payload, load_profile(PROFILE_PATH))


def test_t_m06_every_g1_has_explicit_feed_and_no_g0_or_m_codes() -> None:
    profile, pen_plan, registration = _inputs()
    lines = emit_virtual_gcode(plan_virtual_page(pen_plan, profile, registration)).content.decode().splitlines()
    assert all(" F" in line for line in lines if line.startswith("G1"))
    assert not any(line.startswith(("G0 ", "M")) for line in lines)


def test_t_m07_profile_is_explicitly_simulation_only() -> None:
    profile = load_profile(PROFILE_PATH)
    assert profile.simulation_only and profile.transport_kind == "none"

