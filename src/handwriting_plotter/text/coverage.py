"""Whole-job literal glyph coverage before layout or export."""

from __future__ import annotations

from dataclasses import dataclass

from handwriting_plotter.styles.models import StyleSnapshot

from .normalize import NormalizedDocument


LAYOUT_CONTROLS = {" ", "\u00a0", "\u202f", "\t", "\n", "\f"}


@dataclass(frozen=True, slots=True)
class MissingGlyph:
    key: str
    code_points: tuple[str, ...]
    grapheme_id: str
    original_spans: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class TextCoverageReport:
    supported_grapheme_ids: tuple[str, ...]
    control_grapheme_ids: tuple[str, ...]
    missing: tuple[MissingGlyph, ...]

    @property
    def passed(self) -> bool:
        return not self.missing


def check_coverage(document: NormalizedDocument, style: StyleSnapshot) -> TextCoverageReport:
    keys = style.variants_by_key
    supported: list[str] = []
    controls: list[str] = []
    missing: list[MissingGlyph] = []
    graphemes = document.graphemes
    index = 0
    while index < len(graphemes):
        item = graphemes[index]
        if item.nfc in LAYOUT_CONTROLS:
            controls.append(item.id)
            index += 1
            continue
        match_length = 0
        for length in range(1, min(8, len(graphemes) - index) + 1):
            candidate = "".join(part.nfc for part in graphemes[index:index + length])
            if candidate in keys:
                match_length = length
        if match_length:
            supported.extend(part.id for part in graphemes[index:index + match_length])
            index += match_length
            continue
        missing.append(
            MissingGlyph(
                item.nfc,
                tuple(f"U+{ord(character):04X}" for character in item.nfc),
                item.id,
                item.original_spans,
            )
        )
        index += 1
    return TextCoverageReport(tuple(supported), tuple(controls), tuple(missing))

