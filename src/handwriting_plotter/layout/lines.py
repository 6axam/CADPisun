"""Immutable page-line and placed execution-group records."""

from __future__ import annotations

from dataclasses import dataclass

from handwriting_plotter.geometry.bounds import Bounds
from handwriting_plotter.geometry.curves import Cubic, Line, Point2, Quadratic, Segment, Stroke
from handwriting_plotter.shaping.schedule import ExecutionGroup, ShapedWord


@dataclass(frozen=True, slots=True)
class PlacedExecutionGroup:
    group_id: str
    strokes: tuple[Stroke, ...]
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlacedWord:
    shape: ShapedWord
    origin_x_mm: float
    groups: tuple[PlacedExecutionGroup, ...]


@dataclass(frozen=True, slots=True)
class PageLine:
    line_id: str
    baseline_y_mm: float
    words: tuple[PlacedWord, ...]
    ink_bounds: Bounds


def _translate_segment(segment: Segment, x: float, y: float) -> Segment:
    def point(value: Point2) -> Point2:
        return Point2(value.x + x, value.y + y)

    if isinstance(segment, Line):
        return Line(point(segment.p0), point(segment.p1))
    if isinstance(segment, Quadratic):
        return Quadratic(point(segment.p0), point(segment.c1), point(segment.p1))
    return Cubic(point(segment.p0), point(segment.c1), point(segment.c2), point(segment.p1))


def place_group(group: ExecutionGroup, x: float, y: float, line_id: str) -> PlacedExecutionGroup:
    strokes = tuple(
        Stroke(
            f"{line_id}/{stroke.id}",
            tuple(_translate_segment(segment, x, y) for segment in stroke.segments),
            stroke.source_refs,
            stroke.role,
            stroke.direction_provenance,
        )
        for stroke in group.strokes
    )
    return PlacedExecutionGroup(f"{line_id}/{group.group_id}", strokes, group.source_refs)

