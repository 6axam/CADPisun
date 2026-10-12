from __future__ import annotations

from types import MappingProxyType

import pytest

from handwriting_plotter.styles.models import GlyphVariant, JoinSpec, StyleManifest, StyleSnapshot
from handwriting_plotter.text.breaks import find_breaks, script_of
from handwriting_plotter.text.coverage import check_coverage
from handwriting_plotter.text.normalize import normalize


def _snapshot(keys: set[str]) -> StyleSnapshot:
    manifest = StyleManifest.model_validate({
        "format": "hp-style", "schema_version": "1.0", "style_id": "fixture", "revision": "1.0.0",
        "display_name": "fixture", "scripts": ("Cyrillic", "Latin"),
        "license_record": {"license_id": "test", "name": "test", "redistribution_allowed": True},
        "glyph_frame": "GlyphFrame",
        "metrics": {"x_height_gu": 1000.0, "ascender_gu": 1200.0, "descender_gu": -300.0,
                    "space_advance_gu": 900.0, "line_gap_gu": 500.0, "supported_x_height_mm": (2.5, 5.0)},
        "coverage": tuple(keys), "glyph_files": (), "join_rules": {}, "variation_policy": {}, "file_hashes": {},
        "approved": True, "production_eligible": False, "test_only": True,
    })
    spec = JoinSpec("none", None, (), None, None, False, False)
    variants = {key: (GlyphVariant(key + "-1", key, (), 500, frozenset({"isolated"}), spec, ()),) for key in keys}
    return StyleSnapshot(manifest, MappingProxyType(variants), "fixture-hash")


def test_t_u01_full_literal_coverage() -> None:
    document = normalize("Україна English 123")
    keys = {g.nfc for g in document.graphemes if not g.nfc.isspace()}
    report = check_coverage(document, _snapshot(keys))
    assert report.passed
    assert len(report.supported_grapheme_ids) + len(report.control_grapheme_ids) == len(document.graphemes)


@pytest.mark.parametrize("composed,decomposed", [("ї", "і\u0308"), ("й", "и\u0306"), ("ё", "е\u0308")])
def test_t_u02_nfc_and_nfd_match_with_source_spans(composed: str, decomposed: str) -> None:
    first = normalize(composed)
    second = normalize(decomposed)
    assert first.normalized_text == second.normalized_text
    assert second.graphemes[0].original_spans == ((0, 1), (1, 2))


def test_t_u03_unicode_lookalikes_remain_distinct() -> None:
    document = normalize("ІIіiаa")
    assert [g.nfc for g in document.graphemes] == ["І", "I", "і", "i", "а", "a"]
    assert [script_of(g.nfc) for g in document.graphemes] == ["Cyrillic", "Latin", "Cyrillic", "Latin", "Cyrillic", "Latin"]


def test_t_u04_controls_breaks_and_crlf_mapping() -> None:
    document = normalize("a\tb\u00a0c\u202fd\r\ne\ff")
    tokens = find_breaks(document)
    assert [token.kind for token in tokens] == ["word", "space", "word", "space", "word", "space", "word", "hard_break", "word", "page_break", "word"]
    newline = next(g for g in document.graphemes if g.nfc == "\n")
    assert newline.original_spans == ((7, 9),)


def test_t_u05_unknown_glyph_and_controls_report_positions() -> None:
    document = normalize("а🙂")
    report = check_coverage(document, _snapshot({"а"}))
    assert report.missing[0].key == "🙂"
    assert report.missing[0].code_points == ("U+1F642",)
    with pytest.raises(ValueError, match="UNSUPPORTED_CONTROL"):
        normalize("a\x00b")
    with pytest.raises(ValueError, match="UNSUPPORTED_SCRIPT_DIRECTION"):
        normalize("a\u202eb")


def test_t_u06_empty_whitespace_and_resource_limit() -> None:
    with pytest.raises(ValueError, match="EMPTY_DOCUMENT"):
        normalize(" \n\t")
    with pytest.raises(ValueError, match="RESOURCE_LIMIT"):
        normalize("a" * (1024 * 1024 + 1))

