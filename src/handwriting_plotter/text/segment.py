"""Extended grapheme segmentation backed by the pinned regex library."""

from __future__ import annotations

import regex


_GRAPHEME = regex.compile(r"\X")


def grapheme_spans(text: str) -> tuple[tuple[int, int], ...]:
    return tuple((match.start(), match.end()) for match in _GRAPHEME.finditer(text))

