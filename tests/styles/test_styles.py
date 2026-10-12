from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from handwriting_plotter.adapters.importers.svg_paths import import_centerline_svg
from handwriting_plotter.styles.repository import FileStyleRepository


def _write_style(root: Path, *, bad_hash: bool = False, duplicate: bool = False) -> Path:
    package = root / "draft"
    (package / "glyphs").mkdir(parents=True)
    (package / "licenses").mkdir()
    license_data = "Test data only.\n"
    (package / "licenses" / "test.txt").write_text(license_data, encoding="utf-8")
    glyph = {
        "format": "hp-glyph",
        "schema_version": "1.0",
        "variant_id": "a-1",
        "key": "a",
        "strokes": [{
            "id": "body", "role": "body", "direction_provenance": "authored", "source_refs": [],
            "segments": [{"kind": "line", "p0": {"x": 0.0, "y": 0.0}, "p1": {"x": 500.0, "y": 1000.0}}],
        }],
        "advance_gu": 600.0,
        "context_tags": ["isolated"],
        "join_spec": {"mode": "none"},
        "provenance": {"license_id": "test", "source_method": "manual_vector"},
        "review_status": "approved",
        "critical_features": [],
    }
    glyph_bytes = json.dumps(glyph, ensure_ascii=False, sort_keys=True).encode()
    (package / "glyphs" / "a.json").write_bytes(glyph_bytes)
    files = ["glyphs/a.json"]
    if duplicate:
        (package / "glyphs" / "a-copy.json").write_bytes(glyph_bytes)
        files.append("glyphs/a-copy.json")
    hashes = {name: sha256((package / name).read_bytes()).hexdigest() for name in files}
    hashes["licenses/test.txt"] = sha256(license_data.encode()).hexdigest()
    if bad_hash:
        hashes["glyphs/a.json"] = "0" * 64
    manifest = {
        "format": "hp-style", "schema_version": "1.0", "style_id": "test-style", "revision": "1.0.0",
        "display_name": "Test only", "scripts": ["Latin"],
        "license_record": {"license_id": "test", "name": "Test", "redistribution_allowed": True},
        "glyph_frame": "GlyphFrame",
        "metrics": {"x_height_gu": 1000.0, "ascender_gu": 1200.0, "descender_gu": -300.0,
                    "space_advance_gu": 900.0, "line_gap_gu": 500.0, "supported_x_height_mm": [2.5, 5.0]},
        "coverage": ["a"], "glyph_files": files, "join_rules": {}, "variation_policy": {},
        "file_hashes": hashes, "approved": True, "production_eligible": False, "test_only": True,
    }
    (package / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return package


def test_t_s01_loads_verified_test_style(tmp_path: Path) -> None:
    package = _write_style(tmp_path)
    repository = FileStyleRepository(tmp_path / "published")
    snapshot = repository.publish(package)
    loaded = repository.load("test-style", "1.0.0")
    assert loaded.revision_hash == snapshot.revision_hash
    assert loaded.variants_by_key["a"][0].strokes[0].id == "body"


def test_t_s02_rejects_hash_mismatch(tmp_path: Path) -> None:
    package = _write_style(tmp_path, bad_hash=True)
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        FileStyleRepository(tmp_path / "published").publish(package)


def test_t_s03_rejects_duplicate_variant_id(tmp_path: Path) -> None:
    package = _write_style(tmp_path, duplicate=True)
    with pytest.raises(ValueError, match="DUPLICATE_VARIANT_ID"):
        FileStyleRepository(tmp_path / "published").publish(package)


def test_t_s04_svg_import_preserves_subpath_order() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><path fill="none" d="M0 0 L10 0 Q15 5 20 0 M30 0 C35 0 35 10 40 10"/></svg>'
    strokes = import_centerline_svg(svg)
    assert [stroke.id for stroke in strokes] == ["svg-1-0", "svg-1-1"]
    assert [segment.kind for segment in strokes[0].segments] == ["line", "quadratic"]


def test_t_s05_svg_import_rejects_entities_arcs_and_filled_paths() -> None:
    with pytest.raises(Exception):
        import_centerline_svg(b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>')
    with pytest.raises(ValueError, match="UNSUPPORTED_PATH_COMMAND"):
        import_centerline_svg(b'<svg width="10" height="10" viewBox="0 0 10 10"><path fill="none" d="M0 0 A2 2 0 0 0 4 4"/></svg>')
    with pytest.raises(ValueError, match="filled-path"):
        import_centerline_svg(b'<svg width="10" height="10" viewBox="0 0 10 10"><path fill="black" d="M0 0 L1 1"/></svg>')


def test_svg_group_rotation_and_inherited_fill() -> None:
    svg = b'<svg width="10" height="10" viewBox="0 0 10 10" fill="none"><g transform="translate(2 3)"><path transform="rotate(90)" d="M0 0 L1 0"/></g></svg>'
    stroke = import_centerline_svg(svg)[0]
    assert stroke.start.x == pytest.approx(2)
    assert stroke.start.y == pytest.approx(3)
    assert stroke.end.x == pytest.approx(2)
    assert stroke.end.y == pytest.approx(4)

