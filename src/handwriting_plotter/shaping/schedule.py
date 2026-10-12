"""Word shaping orchestration and authored execution scheduling."""

from __future__ import annotations

from dataclasses import dataclass

from handwriting_plotter.geometry.bounds import Bounds, curve_bounds
from handwriting_plotter.geometry.curves import Stroke
from handwriting_plotter.styles.models import StyleSnapshot
from handwriting_plotter.text.normalize import Grapheme

from .joins import RejectedJoin, connect
from .placement import PlacedGlyph, place_glyph
from .resolve import resolve
from .variants import VariationSpec, effective_variation, select_variant


@dataclass(frozen=True, slots=True)
class ExecutionGroup:
    group_id: str
    strokes: tuple[Stroke, ...]
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ShapedWord:
    fragment_id: str
    grapheme_ids: tuple[str, ...]
    glyphs: tuple[PlacedGlyph, ...]
    execution_groups: tuple[ExecutionGroup, ...]
    advance_mm: float
    ink_bounds_mm: Bounds
    diagnostics: tuple[str, ...]


class WordShaper:
    def shape(
        self,
        graphemes: tuple[Grapheme, ...],
        style: StyleSnapshot,
        *,
        seed: int,
        x_height_mm: float,
        variation: VariationSpec = VariationSpec(),
    ) -> ShapedWord:
        if not graphemes:
            raise ValueError("EMPTY_FRAGMENT")
        matches = resolve(graphemes, style)
        placed: list[PlacedGlyph] = []
        diagnostics: list[str] = []
        x = 0.0
        previous_by_key: dict[str, str] = {}
        for match in matches:
            selected = select_variant(
                match,
                seed=seed,
                style_hash=style.revision_hash,
                previous_variant_id=previous_by_key.get(match.key),
            )
            previous_by_key[match.key] = selected.variant_id
            effective = effective_variation(match, style, variation, seed)
            glyph = place_glyph(match, selected, x, x_height_mm, effective)
            placed.append(glyph)
            x += glyph.advance_mm

        groups: list[ExecutionGroup] = []
        index = 0
        while index < len(placed):
            glyph = placed[index]
            if glyph.join_mode != "single_body_deferred_marks" or glyph.body_stroke_id is None:
                for stroke in glyph.strokes:
                    groups.append(ExecutionGroup(f"group-{len(groups):06d}", (stroke,), stroke.source_refs))
                index += 1
                continue
            chain: list[Stroke] = [next(stroke for stroke in glyph.strokes if stroke.id == glyph.body_stroke_id)]
            marks: list[Stroke] = [next(stroke for stroke in glyph.strokes if stroke.id == mark) for mark in glyph.deferred_marks]
            run_end = index
            while run_end + 1 < len(placed):
                connector = connect(placed[run_end], placed[run_end + 1])
                if isinstance(connector, RejectedJoin):
                    diagnostics.append(
                        f"JOIN_REJECTED:{placed[run_end].match.key}:{placed[run_end + 1].match.key}:{connector.reason}"
                    )
                    break
                chain.append(connector)
                following = placed[run_end + 1]
                if following.body_stroke_id is None:
                    break
                chain.append(next(stroke for stroke in following.strokes if stroke.id == following.body_stroke_id))
                marks.extend(next(stroke for stroke in following.strokes if stroke.id == mark) for mark in following.deferred_marks)
                run_end += 1
            refs = tuple(dict.fromkeys(ref for stroke in chain for ref in stroke.source_refs))
            groups.append(ExecutionGroup(f"group-{len(groups):06d}", tuple(chain), refs))
            for mark in marks:
                groups.append(ExecutionGroup(f"group-{len(groups):06d}", (mark,), mark.source_refs))
            index = run_end + 1

        segments = [segment for glyph in placed for stroke in glyph.strokes for segment in stroke.segments]
        segments.extend(segment for group in groups for stroke in group.strokes if stroke.role == "connector" for segment in stroke.segments)
        if not segments:
            raise ValueError("EMPTY_SHAPE")
        bounds = curve_bounds(segments[0])
        for segment in segments[1:]:
            bounds = bounds.union(curve_bounds(segment))
        fragment_id = "fragment:" + "+".join(item.id for item in graphemes)
        return ShapedWord(
            fragment_id,
            tuple(item.id for item in graphemes),
            tuple(placed),
            tuple(groups),
            x,
            bounds,
            tuple(diagnostics),
        )

