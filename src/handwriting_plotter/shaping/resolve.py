"""Longest eligible glyph-key resolution."""

from __future__ import annotations

from dataclasses import dataclass

from handwriting_plotter.styles.models import GlyphVariant, StyleSnapshot
from handwriting_plotter.text.breaks import script_of
from handwriting_plotter.text.normalize import Grapheme


@dataclass(frozen=True, slots=True)
class GlyphMatch:
    key: str
    graphemes: tuple[Grapheme, ...]
    candidates: tuple[GlyphVariant, ...]
    context: str
    occurrence_id: str


def _context(index: int, length: int, scripts: list[str]) -> str:
    same_before = index > 0 and scripts[index - 1] == scripts[index] and scripts[index] in {"Latin", "Cyrillic"}
    same_after = index + length < len(scripts) and scripts[index + length] == scripts[index] and scripts[index] in {"Latin", "Cyrillic"}
    if same_before and same_after:
        return "medial"
    if same_after:
        return "initial"
    if same_before:
        return "final"
    return "isolated"


def resolve(graphemes: tuple[Grapheme, ...], style: StyleSnapshot) -> tuple[GlyphMatch, ...]:
    scripts = [script_of(item.nfc) for item in graphemes]
    output: list[GlyphMatch] = []
    index = 0
    while index < len(graphemes):
        matches: list[tuple[int, str]] = []
        for length in range(1, min(8, len(graphemes) - index) + 1):
            key = "".join(item.nfc for item in graphemes[index:index + length])
            candidate_scripts = scripts[index:index + length]
            if length > 1 and (
                len(set(candidate_scripts)) != 1
                or candidate_scripts[0] not in {"Latin", "Cyrillic"}
                or not all(item.nfc.isalpha() for item in graphemes[index:index + length])
            ):
                continue
            if key in style.variants_by_key:
                matches.append((length, key))
        if not matches:
            raise ValueError(f"MISSING_GLYPH:{graphemes[index].nfc}:{graphemes[index].id}")
        length, key = max(matches, key=lambda pair: (pair[0], pair[1]))
        context = _context(index, length, scripts)
        all_candidates = style.variants_by_key[key]
        contextual = tuple(item for item in all_candidates if context in item.context_tags)
        candidates = contextual or tuple(item for item in all_candidates if "isolated" in item.context_tags)
        if not candidates:
            raise ValueError(f"NO_ELIGIBLE_VARIANT:{key}:{context}")
        consumed = graphemes[index:index + length]
        occurrence_id = "occ:" + "+".join(item.id for item in consumed)
        output.append(GlyphMatch(key, consumed, tuple(sorted(candidates, key=lambda item: item.variant_id)), context, occurrence_id))
        index += length
    return tuple(output)

