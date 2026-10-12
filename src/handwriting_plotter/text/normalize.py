"""CR/LF normalization, per-cluster NFC and scalar-index source mapping."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass

from .segment import grapheme_spans


MAX_TEXT_BYTES = 1024 * 1024
MAX_GRAPHEMES = 100_000
_ALLOWED_C0 = {"\t", "\n", "\f"}


@dataclass(frozen=True, slots=True)
class Grapheme:
    id: str
    nfc: str
    normalized_span: tuple[int, int]
    original_spans: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    original_hash: str
    normalized_text: str
    graphemes: tuple[Grapheme, ...]
    diagnostics: tuple[str, ...] = ()


def _line_endings(text: str) -> tuple[str, list[tuple[int, int]]]:
    output: list[str] = []
    mapping: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        if text[index] == "\r":
            end = index + 2 if index + 1 < len(text) and text[index + 1] == "\n" else index + 1
            output.append("\n")
            mapping.append((index, end))
            index = end
        else:
            output.append(text[index])
            mapping.append((index, index + 1))
            index += 1
    return "".join(output), mapping


def _validate_controls(text: str) -> None:
    for index, character in enumerate(text):
        category = unicodedata.category(character)
        if category == "Cc" and character not in _ALLOWED_C0:
            raise ValueError(f"UNSUPPORTED_CONTROL:{index}:U+{ord(character):04X}")
        if category == "Cf":
            raise ValueError(f"UNSUPPORTED_SCRIPT_DIRECTION:{index}:U+{ord(character):04X}")


def normalize(text: str) -> NormalizedDocument:
    if not isinstance(text, str):
        raise TypeError("text must be decoded Unicode")
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_TEXT_BYTES:
        raise ValueError("RESOURCE_LIMIT:text-bytes")
    intermediate, scalar_map = _line_endings(text)
    _validate_controls(intermediate)
    output: list[str] = []
    graphemes: list[Grapheme] = []
    normalized_offset = 0
    for cluster_index, (start, end) in enumerate(grapheme_spans(intermediate)):
        source = intermediate[start:end]
        nfc = unicodedata.normalize("NFC", source)
        if not nfc:
            raise ValueError("INVALID_UNICODE_CLUSTER")
        original_spans = tuple(scalar_map[start:end])
        normalized_span = (normalized_offset, normalized_offset + len(nfc))
        graphemes.append(Grapheme(f"g-{cluster_index:06d}", nfc, normalized_span, original_spans))
        output.append(nfc)
        normalized_offset += len(nfc)
    if len(graphemes) > MAX_GRAPHEMES:
        raise ValueError("RESOURCE_LIMIT:graphemes")
    if not graphemes or all(grapheme.nfc.isspace() for grapheme in graphemes):
        raise ValueError("EMPTY_DOCUMENT")
    return NormalizedDocument(hashlib.sha256(encoded).hexdigest(), "".join(output), tuple(graphemes))

