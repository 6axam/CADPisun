"""Tailored LTR token and break policy for UA/RU/EN text."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal

from .normalize import Grapheme, NormalizedDocument


@dataclass(frozen=True, slots=True)
class Token:
    token_id: str
    kind: Literal["word", "space", "hard_break", "page_break"]
    grapheme_ids: tuple[str, ...]
    break_policy: Literal["breakable", "nonbreakable", "forced", "none"]
    text: str


def find_breaks(document: NormalizedDocument) -> tuple[Token, ...]:
    tokens: list[Token] = []
    buffer: list[Grapheme] = []

    def flush_word() -> None:
        if buffer:
            tokens.append(Token(f"t-{len(tokens):06d}", "word", tuple(g.id for g in buffer), "none", "".join(g.nfc for g in buffer)))
            buffer.clear()

    for grapheme in document.graphemes:
        value = grapheme.nfc
        if value in {"\n", "\f"}:
            flush_word()
            kind = "hard_break" if value == "\n" else "page_break"
            tokens.append(Token(f"t-{len(tokens):06d}", kind, (grapheme.id,), "forced", value))
        elif value in {" ", "\t"}:
            flush_word()
            tokens.append(Token(f"t-{len(tokens):06d}", "space", (grapheme.id,), "breakable", value))
        elif value in {"\u00a0", "\u202f"}:
            flush_word()
            tokens.append(Token(f"t-{len(tokens):06d}", "space", (grapheme.id,), "nonbreakable", value))
        else:
            buffer.append(grapheme)
    flush_word()
    return tuple(tokens)


def script_of(value: str) -> str:
    if not value:
        return "Unknown"
    name = unicodedata.name(value[0], "")
    if "CYRILLIC" in name:
        return "Cyrillic"
    if "LATIN" in name:
        return "Latin"
    if value[0].isdigit():
        return "Digit"
    return "Common"

