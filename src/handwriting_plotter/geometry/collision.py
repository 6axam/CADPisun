"""Polyline segment distance and intersection checks."""

from __future__ import annotations

from .curves import Line, Point2


def _orientation(a: Point2, b: Point2, c: Point2) -> float:
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def _on_segment(a: Point2, b: Point2, point: Point2, epsilon: float) -> bool:
    return (
        min(a.x, b.x) - epsilon <= point.x <= max(a.x, b.x) + epsilon
        and min(a.y, b.y) - epsilon <= point.y <= max(a.y, b.y) + epsilon
    )


def segments_intersect(first: Line, second: Line, epsilon: float = 1e-12) -> bool:
    a, b, c, d = first.p0, first.p1, second.p0, second.p1
    o1, o2, o3, o4 = _orientation(a, b, c), _orientation(a, b, d), _orientation(c, d, a), _orientation(c, d, b)
    if ((o1 > epsilon and o2 < -epsilon) or (o1 < -epsilon and o2 > epsilon)) and (
        (o3 > epsilon and o4 < -epsilon) or (o3 < -epsilon and o4 > epsilon)
    ):
        return True
    return (
        (abs(o1) <= epsilon and _on_segment(a, b, c, epsilon))
        or (abs(o2) <= epsilon and _on_segment(a, b, d, epsilon))
        or (abs(o3) <= epsilon and _on_segment(c, d, a, epsilon))
        or (abs(o4) <= epsilon and _on_segment(c, d, b, epsilon))
    )


def point_segment_distance(point: Point2, line: Line) -> float:
    dx, dy = line.p1.x - line.p0.x, line.p1.y - line.p0.y
    denominator = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((point.x - line.p0.x) * dx + (point.y - line.p0.y) * dy) / denominator))
    projected = Point2(line.p0.x + t * dx, line.p0.y + t * dy)
    return point.distance_to(projected)


def segment_distance(first: Line, second: Line) -> float:
    if segments_intersect(first, second):
        return 0.0
    return min(
        point_segment_distance(first.p0, second),
        point_segment_distance(first.p1, second),
        point_segment_distance(second.p0, first),
        point_segment_distance(second.p1, first),
    )

