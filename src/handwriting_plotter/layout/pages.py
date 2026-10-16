"""Deterministic A4 layout over measured shaped-word envelopes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from handwriting_plotter.geometry.bounds import Bounds, curve_bounds
from handwriting_plotter.shaping.schedule import ShapedWord, WordShaper
from handwriting_plotter.shaping.variants import VariationSpec, hash_unit, symmetric
from handwriting_plotter.styles.models import StyleSnapshot
from handwriting_plotter.text.breaks import Token, find_breaks
from handwriting_plotter.text.normalize import Grapheme, NormalizedDocument

from .lines import PageLine, PlacedWord, place_group


@dataclass(frozen=True, slots=True)
class PageSpec:
    width_mm: float = 210.0
    height_mm: float = 297.0
    margin_left_mm: float = 15.0
    margin_right_mm: float = 15.0
    margin_top_mm: float = 15.0
    margin_bottom_mm: float = 15.0
    x_height_mm: float = 3.5
    line_pitch_mm: float = 9.0
    character_spacing_mm: float = 0.0
    paragraph_gap_mm: float = 4.0
    pen_width_mm: float = 0.35
    alignment: str = "left"
    long_token_policy: str = "grapheme_break"
    hyphenation: str = "off"

    def __post_init__(self) -> None:
        values = (
            self.width_mm, self.height_mm, self.margin_left_mm, self.margin_right_mm,
            self.margin_top_mm, self.margin_bottom_mm, self.x_height_mm,
            self.line_pitch_mm, self.character_spacing_mm, self.paragraph_gap_mm, self.pen_width_mm,
        )
        if any(value < 0 for value in values) or self.width_mm <= 0 or self.height_mm <= 0:
            raise ValueError("invalid page dimensions")
        if self.printable_width <= 0 or self.printable_height <= 0:
            raise ValueError("printable rectangle must have positive area")
        if self.x_height_mm <= 0 or self.line_pitch_mm <= 0 or self.pen_width_mm <= 0:
            raise ValueError("invalid text dimensions")
        if self.alignment != "left" or self.long_token_policy != "grapheme_break" or self.hyphenation != "off":
            raise ValueError("unsupported page policy")

    @property
    def printable_width(self) -> float:
        return self.width_mm - self.margin_left_mm - self.margin_right_mm

    @property
    def printable_height(self) -> float:
        return self.height_mm - self.margin_top_mm - self.margin_bottom_mm


@dataclass(frozen=True, slots=True)
class Page:
    index: int
    page_id: str
    spec: PageSpec
    lines: tuple[PageLine, ...]
    ink_bounds: Bounds | None

    @property
    def groups(self):
        return tuple(group for line in self.lines for word in line.words for group in word.groups)


@dataclass(frozen=True, slots=True)
class PageDocument:
    document_id: str
    pages: tuple[Page, ...]
    source_coverage: tuple[str, ...]
    complete: bool
    diagnostics: tuple[str, ...]


@dataclass(slots=True)
class _LineWord:
    shape: ShapedWord
    x: float


def _occupied(shape: ShapedWord, pen_width: float) -> tuple[float, float, float]:
    half = pen_width / 2
    left = min(0.0, shape.ink_bounds_mm.min_x - half)
    right = max(shape.advance_mm, shape.ink_bounds_mm.max_x + half)
    return left, right, right - left


def _line_relative_bounds(words: list[_LineWord], pen_width: float) -> Bounds:
    half = pen_width / 2
    first = words[0]
    bounds = Bounds(
        first.x + first.shape.ink_bounds_mm.min_x - half,
        first.shape.ink_bounds_mm.min_y - half,
        first.x + first.shape.ink_bounds_mm.max_x + half,
        first.shape.ink_bounds_mm.max_y + half,
    )
    for item in words[1:]:
        bounds = bounds.union(Bounds(
            item.x + item.shape.ink_bounds_mm.min_x - half,
            item.shape.ink_bounds_mm.min_y - half,
            item.x + item.shape.ink_bounds_mm.max_x + half,
            item.shape.ink_bounds_mm.max_y + half,
        ))
    return bounds


def _split_word(
    graphemes: tuple[Grapheme, ...],
    style: StyleSnapshot,
    shaper: WordShaper,
    seed: int,
    spec: PageSpec,
    variation: VariationSpec,
) -> tuple[ShapedWord, tuple[Grapheme, ...]]:
    if len(graphemes) > 4096:
        raise ValueError("RESOURCE_LIMIT:emergency-token")
    chosen: ShapedWord | None = None
    chosen_length = 0
    for length in range(1, len(graphemes) + 1):
        candidate = shaper.shape(
            graphemes[:length],
            style,
            seed=seed,
            x_height_mm=spec.x_height_mm,
            pen_width_mm=spec.pen_width_mm,
            character_spacing_mm=spec.character_spacing_mm,
            variation=variation,
        )
        if _occupied(candidate, spec.pen_width_mm)[2] <= spec.printable_width:
            chosen = candidate
            chosen_length = length
        else:
            break
    if chosen is None:
        raise ValueError("GLYPH_TOO_WIDE")
    return chosen, graphemes[chosen_length:]


def layout_document(
    document: NormalizedDocument,
    style: StyleSnapshot,
    *,
    seed: int,
    page_spec: PageSpec = PageSpec(),
    variation: VariationSpec = VariationSpec(),
    shaper: WordShaper | None = None,
) -> PageDocument:
    low, high = style.manifest.metrics.supported_x_height_mm
    if not low <= page_spec.x_height_mm <= high:
        raise ValueError("UNSUPPORTED_X_HEIGHT")
    shaper = shaper or WordShaper()
    grapheme_by_id = {item.id: item for item in document.graphemes}
    tokens = list(find_breaks(document))
    pages_lines: list[list[PageLine]] = [[]]
    current: list[_LineWord] = []
    current_x = 0.0
    pending_gap = 0.0
    pending_nonbreakable = False
    last_baseline: float | None = None
    previous_bottom: float | None = None
    diagnostics: list[str] = []
    coverage: list[str] = []
    paragraph_gap_pending = False
    shaping_operations = 0

    def finish_line(*, forced_empty: bool = False) -> None:
        nonlocal current, current_x, pending_gap, pending_nonbreakable, last_baseline, previous_bottom, paragraph_gap_pending
        if not current:
            if forced_empty:
                last_baseline = (last_baseline if last_baseline is not None else page_spec.margin_top_mm) + page_spec.line_pitch_mm
                paragraph_gap_pending = True
            pending_gap = 0
            return
        relative = _line_relative_bounds(current, page_spec.pen_width_mm)
        reserve = style.manifest.variation_policy.max_line_y_mm * variation.realism
        if last_baseline is None:
            baseline = page_spec.margin_top_mm + reserve - relative.min_y
        else:
            baseline = max(last_baseline + page_spec.line_pitch_mm, (previous_bottom or 0) + 0.5 - relative.min_y)
            if paragraph_gap_pending:
                baseline += page_spec.paragraph_gap_mm
        line_number = sum(len(page) for page in pages_lines)
        line_variation = symmetric(
            hash_unit(seed, style.revision_hash, f"line-{line_number:06d}", "line-y"),
            reserve,
        )
        baseline += line_variation
        final_bottom = baseline + relative.max_y
        if final_bottom > page_spec.height_mm - page_spec.margin_bottom_mm + 1e-9:
            pages_lines.append([])
            last_baseline = None
            previous_bottom = None
            paragraph_gap_pending = False
            baseline = page_spec.margin_top_mm + reserve - relative.min_y + line_variation
            final_bottom = baseline + relative.max_y
            if final_bottom > page_spec.height_mm - page_spec.margin_bottom_mm + 1e-9:
                raise ValueError("LINE_TOO_TALL")
        page_index = len(pages_lines) - 1
        line_id = f"page-{page_index:04d}/line-{len(pages_lines[-1]):04d}"
        placed_words: list[PlacedWord] = []
        line_bounds: Bounds | None = None
        for item in current:
            origin_x = page_spec.margin_left_mm + item.x
            groups = tuple(place_group(group, origin_x, baseline, line_id) for group in item.shape.execution_groups)
            placed_words.append(PlacedWord(item.shape, origin_x, groups))
            word_bounds = Bounds(
                origin_x + item.shape.ink_bounds_mm.min_x - page_spec.pen_width_mm / 2,
                baseline + item.shape.ink_bounds_mm.min_y - page_spec.pen_width_mm / 2,
                origin_x + item.shape.ink_bounds_mm.max_x + page_spec.pen_width_mm / 2,
                baseline + item.shape.ink_bounds_mm.max_y + page_spec.pen_width_mm / 2,
            )
            line_bounds = word_bounds if line_bounds is None else line_bounds.union(word_bounds)
        assert line_bounds is not None
        if line_bounds.min_x < page_spec.margin_left_mm - 1e-9 or line_bounds.max_x > page_spec.width_mm - page_spec.margin_right_mm + 1e-9:
            raise ValueError("LAYOUT_OUT_OF_BOUNDS")
        pages_lines[-1].append(PageLine(line_id, baseline, tuple(placed_words), line_bounds))
        last_baseline, previous_bottom = baseline, final_bottom
        current, current_x, pending_gap, pending_nonbreakable = [], 0.0, 0.0, False
        paragraph_gap_pending = False

    queue: list[tuple[str, tuple[Grapheme, ...], Token | None]] = []
    for token in tokens:
        graphemes = tuple(grapheme_by_id[item] for item in token.grapheme_ids)
        queue.append((token.kind, graphemes, token))
    index = 0
    while index < len(queue):
        kind, graphemes, token = queue[index]
        assert token is not None
        if kind == "space":
            coverage.extend(item.id for item in graphemes)
            nominal = style.manifest.metrics.space_advance_gu * page_spec.x_height_mm / 1000
            if token.text == "\u202f":
                nominal *= 0.5
            if token.text == "\t":
                tab = nominal * 4
                pending_gap = tab - (current_x % tab) if current_x % tab else tab
            else:
                pending_gap += nominal
            pending_nonbreakable = token.break_policy == "nonbreakable"
            index += 1
            continue
        if kind == "hard_break":
            coverage.extend(item.id for item in graphemes)
            finish_line(forced_empty=not current)
            index += 1
            continue
        if kind == "page_break":
            coverage.extend(item.id for item in graphemes)
            finish_line()
            if index != len(queue) - 1:
                pages_lines.append([])
                last_baseline = previous_bottom = None
                diagnostics.append("EXPLICIT_PAGE_BREAK")
            index += 1
            continue
        block_words: list[tuple[tuple[Grapheme, ...], Token]] = [(graphemes, token)]
        block_spaces: list[tuple[Grapheme, ...]] = []
        scan = index
        while scan + 2 < len(queue):
            next_kind, next_graphemes, next_token = queue[scan + 1]
            following_kind, following_graphemes, following_token = queue[scan + 2]
            if (
                next_kind != "space"
                or next_token is None
                or next_token.break_policy != "nonbreakable"
                or following_kind != "word"
                or following_token is None
            ):
                break
            block_spaces.append(next_graphemes)
            block_words.append((following_graphemes, following_token))
            scan += 2
        if len(block_words) > 1:
            nominal = style.manifest.metrics.space_advance_gu * page_spec.x_height_mm / 1000
            relative_words: list[_LineWord] = []
            block_x = 0.0
            for word_index, (word_graphemes, _) in enumerate(block_words):
                shaping_operations += 1
                if shaping_operations > 1_000_000:
                    raise ValueError("RESOURCE_LIMIT:shaping-operations")
                block_shape = shaper.shape(
                    word_graphemes,
                    style,
                    seed=seed,
                    x_height_mm=page_spec.x_height_mm,
                    pen_width_mm=page_spec.pen_width_mm,
                    character_spacing_mm=page_spec.character_spacing_mm,
                    variation=variation,
                )
                left, _, width = _occupied(block_shape, page_spec.pen_width_mm)
                relative_words.append(_LineWord(block_shape, block_x - left))
                block_x += width
                if word_index < len(block_words) - 1:
                    space_text = "".join(item.nfc for item in block_spaces[word_index])
                    block_x += nominal * (0.5 if space_text == "\u202f" else 1.0)
            if block_x > page_spec.printable_width + 1e-9:
                raise ValueError("NONBREAKABLE_OVERFLOW")
            if current and current_x + pending_gap + block_x > page_spec.printable_width + 1e-9:
                finish_line()
                continue
            base_x = current_x + pending_gap
            current.extend(_LineWord(item.shape, base_x + item.x) for item in relative_words)
            current_x += pending_gap + block_x
            pending_gap = 0
            pending_nonbreakable = False
            for word_graphemes, _ in block_words:
                coverage.extend(item.id for item in word_graphemes)
            for space_graphemes in block_spaces:
                coverage.extend(item.id for item in space_graphemes)
            index = scan + 1
            continue
        shaping_operations += 1
        if shaping_operations > 1_000_000:
            raise ValueError("RESOURCE_LIMIT:shaping-operations")
        shape = shaper.shape(
            graphemes,
            style,
            seed=seed,
            x_height_mm=page_spec.x_height_mm,
            pen_width_mm=page_spec.pen_width_mm,
            character_spacing_mm=page_spec.character_spacing_mm,
            variation=variation,
        )
        left, _, width = _occupied(shape, page_spec.pen_width_mm)
        required = pending_gap + width
        if current and current_x + required > page_spec.printable_width + 1e-9:
            if pending_nonbreakable:
                raise ValueError("NONBREAKABLE_OVERFLOW")
            finish_line()
            pending_gap = 0
            continue
        if not current and width > page_spec.printable_width + 1e-9:
            prefix, remainder = _split_word(graphemes, style, shaper, seed, page_spec, variation)
            queue[index] = (kind, graphemes[:len(prefix.grapheme_ids)], token)
            if remainder:
                queue.insert(index + 1, (kind, remainder, token))
            shape = prefix
            graphemes = graphemes[:len(prefix.grapheme_ids)]
            left, _, width = _occupied(shape, page_spec.pen_width_mm)
        origin = current_x + pending_gap - left
        current.append(_LineWord(shape, origin))
        current_x += pending_gap + width
        pending_gap = 0
        pending_nonbreakable = False
        coverage.extend(item.id for item in graphemes)
        index += 1
    finish_line()

    pages: list[Page] = []
    for page_index, lines in enumerate(pages_lines):
        if not lines and page_index == len(pages_lines) - 1:
            continue
        bounds: Bounds | None = None
        for line in lines:
            bounds = line.ink_bounds if bounds is None else bounds.union(line.ink_bounds)
        pages.append(Page(page_index, f"page-{page_index:04d}", page_spec, tuple(lines), bounds))
    document_id = "doc-" + hashlib.sha256(
        f"{document.original_hash}:{style.revision_hash}:{seed}:{page_spec}".encode()
    ).hexdigest()[:20]
    if sorted(coverage) != sorted(item.id for item in document.graphemes):
        raise ValueError("SOURCE_COVERAGE_MISMATCH")
    return PageDocument(document_id, tuple(pages), tuple(coverage), True, tuple(diagnostics))

