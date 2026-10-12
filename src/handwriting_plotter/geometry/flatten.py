"""Conservative De Casteljau flattening with explicit budgets."""

from __future__ import annotations

from dataclasses import dataclass

from .curves import Cubic, Line, Point2, Quadratic, Segment, Stroke, StrokeSet, split


@dataclass(frozen=True, slots=True)
class FlattenLimits:
    max_depth: int = 24
    max_segments: int = 2_000_000
    max_chord_length: float = 1.0


@dataclass(frozen=True, slots=True)
class ApproximationReport:
    tolerance: float
    input_segments: int
    output_segments: int
    max_depth_used: int


def _distance_to_segment(point: Point2, start: Point2, end: Point2) -> float:
    dx, dy = end.x - start.x, end.y - start.y
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return point.distance_to(start)
    t = max(0.0, min(1.0, ((point.x - start.x) * dx + (point.y - start.y) * dy) / length_sq))
    projection = Point2(start.x + t * dx, start.y + t * dy)
    return point.distance_to(projection)


def _flat_enough(segment: Segment, tolerance: float, max_chord_length: float) -> bool:
    chord_length = segment.p0.distance_to(segment.p1)
    if chord_length > max_chord_length:
        return False
    if isinstance(segment, Line):
        return True
    controls = (segment.c1,) if isinstance(segment, Quadratic) else (segment.c1, segment.c2)
    return all(_distance_to_segment(point, segment.p0, segment.p1) <= tolerance for point in controls)


def flatten_segment(
    segment: Segment,
    tolerance: float,
    limits: FlattenLimits,
) -> tuple[list[Line], int]:
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    if isinstance(segment, Line) and _flat_enough(segment, tolerance, limits.max_chord_length):
        return [segment], 0
    output: list[Line] = []
    stack: list[tuple[Segment, int]] = [(segment, 0)]
    max_depth = 0
    while stack:
        current, depth = stack.pop()
        max_depth = max(max_depth, depth)
        if _flat_enough(current, tolerance, limits.max_chord_length):
            if current.p0 != current.p1:
                output.append(Line(current.p0, current.p1))
            if len(output) > limits.max_segments:
                raise ValueError("GEOMETRY_BUDGET_EXCEEDED")
            continue
        if depth >= limits.max_depth:
            raise ValueError("GEOMETRY_BUDGET_EXCEEDED")
        left, right = split(current)
        stack.append((right, depth + 1))
        stack.append((left, depth + 1))
    if not output:
        raise ValueError("RESOLUTION_INSUFFICIENT")
    return output, max_depth


def flatten_strokes(
    strokes: StrokeSet,
    tolerance: float,
    limits: FlattenLimits = FlattenLimits(),
) -> tuple[StrokeSet, ApproximationReport]:
    result: list[Stroke] = []
    output_count = 0
    input_count = 0
    max_depth = 0
    for stroke in strokes.strokes:
        lines: list[Line] = []
        for segment in stroke.segments:
            input_count += 1
            flat, used = flatten_segment(segment, tolerance, limits)
            lines.extend(flat)
            output_count += len(flat)
            max_depth = max(max_depth, used)
            if output_count > limits.max_segments:
                raise ValueError("GEOMETRY_BUDGET_EXCEEDED")
        result.append(Stroke(stroke.id, tuple(lines), stroke.source_refs, stroke.role, stroke.direction_provenance))
    return (
        StrokeSet(strokes.id, strokes.frame_id, strokes.units, tuple(result), strokes.source_refs),
        ApproximationReport(tolerance, input_count, output_count, max_depth),
    )

