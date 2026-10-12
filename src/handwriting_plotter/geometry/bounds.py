"""Analytical curve and ink bounds."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .curves import Cubic, Line, Point2, Quadratic, Segment, StrokeSet, evaluate


@dataclass(frozen=True, slots=True)
class Bounds:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def __post_init__(self) -> None:
        values = (self.min_x, self.min_y, self.max_x, self.max_y)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("bounds must be finite")
        if self.min_x > self.max_x or self.min_y > self.max_y:
            raise ValueError("invalid bounds ordering")

    def union(self, other: Bounds) -> Bounds:
        return Bounds(
            min(self.min_x, other.min_x),
            min(self.min_y, other.min_y),
            max(self.max_x, other.max_x),
            max(self.max_y, other.max_y),
        )

    def expanded(self, amount: float) -> Bounds:
        if amount < 0 or not math.isfinite(amount):
            raise ValueError("expansion must be finite and non-negative")
        return Bounds(self.min_x - amount, self.min_y - amount, self.max_x + amount, self.max_y + amount)


def _quadratic_root(p0: float, c1: float, p1: float) -> list[float]:
    denominator = p0 - 2 * c1 + p1
    if abs(denominator) < 1e-15:
        return []
    return [(p0 - c1) / denominator]


def _cubic_roots(p0: float, c1: float, c2: float, p1: float) -> list[float]:
    a = -p0 + 3 * c1 - 3 * c2 + p1
    b = 2 * (p0 - 2 * c1 + c2)
    c = c1 - p0
    if abs(a) < 1e-15:
        if abs(b) < 1e-15:
            return []
        return [-c / b]
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return []
    root = math.sqrt(max(0.0, discriminant))
    return [(-b - root) / (2 * a), (-b + root) / (2 * a)]


def curve_bounds(segment: Segment) -> Bounds:
    parameters = [0.0, 1.0]
    if isinstance(segment, Quadratic):
        parameters.extend(_quadratic_root(segment.p0.x, segment.c1.x, segment.p1.x))
        parameters.extend(_quadratic_root(segment.p0.y, segment.c1.y, segment.p1.y))
    elif isinstance(segment, Cubic):
        parameters.extend(_cubic_roots(segment.p0.x, segment.c1.x, segment.c2.x, segment.p1.x))
        parameters.extend(_cubic_roots(segment.p0.y, segment.c1.y, segment.c2.y, segment.p1.y))
    points = [evaluate(segment, t) for t in parameters if 0.0 < t < 1.0] + [segment.p0, segment.p1]
    return Bounds(
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


def ink_bounds(strokes: StrokeSet, pen_width: float, reserve: float = 0.0) -> Bounds:
    if not strokes.strokes:
        raise ValueError("cannot measure empty stroke set")
    if pen_width <= 0 or reserve < 0:
        raise ValueError("invalid pen width or reserve")
    parts = [curve_bounds(segment) for stroke in strokes.strokes for segment in stroke.segments]
    result = parts[0]
    for part in parts[1:]:
        result = result.union(part)
    return result.expanded(pen_width / 2 + reserve)

