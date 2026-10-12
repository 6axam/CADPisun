"""Immutable directed segment primitives."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, TypeAlias


@dataclass(frozen=True, slots=True)
class Point2:
    x: float
    y: float

    def __post_init__(self) -> None:
        if isinstance(self.x, bool) or isinstance(self.y, bool):
            raise TypeError("point coordinates must be numbers")
        if not math.isfinite(self.x) or not math.isfinite(self.y):
            raise ValueError("point coordinates must be finite")

    def lerp(self, other: Point2, t: float) -> Point2:
        return Point2(self.x + (other.x - self.x) * t, self.y + (other.y - self.y) * t)

    def distance_to(self, other: Point2) -> float:
        return math.hypot(other.x - self.x, other.y - self.y)


@dataclass(frozen=True, slots=True)
class Line:
    p0: Point2
    p1: Point2
    kind: Literal["line"] = "line"

    def __post_init__(self) -> None:
        if self.p0 == self.p1:
            raise ValueError("line must have non-zero length")


@dataclass(frozen=True, slots=True)
class Quadratic:
    p0: Point2
    c1: Point2
    p1: Point2
    kind: Literal["quadratic"] = "quadratic"


@dataclass(frozen=True, slots=True)
class Cubic:
    p0: Point2
    c1: Point2
    c2: Point2
    p1: Point2
    kind: Literal["cubic"] = "cubic"


Segment: TypeAlias = Line | Quadratic | Cubic


@dataclass(frozen=True, slots=True)
class Stroke:
    id: str
    segments: tuple[Segment, ...]
    source_refs: tuple[str, ...] = ()
    role: Literal["body", "mark", "connector", "punctuation", "diagnostic"] = "body"
    direction_provenance: Literal["captured", "authored", "inferred", "unknown"] = "unknown"

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("stroke id is required")
        if not self.segments:
            raise ValueError("stroke must contain at least one segment")
        for previous, current in zip(self.segments, self.segments[1:], strict=False):
            if previous.p1 != current.p0:
                raise ValueError(f"discontinuous stroke {self.id}")

    @property
    def start(self) -> Point2:
        return self.segments[0].p0

    @property
    def end(self) -> Point2:
        return self.segments[-1].p1


@dataclass(frozen=True, slots=True)
class StrokeSet:
    id: str
    frame_id: str
    units: Literal["gu", "mm"]
    strokes: tuple[Stroke, ...]
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.frame_id:
            raise ValueError("stroke set id and frame are required")
        ids = [stroke.id for stroke in self.strokes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate stroke id")


def evaluate(segment: Segment, t: float) -> Point2:
    if not 0.0 <= t <= 1.0:
        raise ValueError("t must be within [0,1]")
    if isinstance(segment, Line):
        return segment.p0.lerp(segment.p1, t)
    if isinstance(segment, Quadratic):
        a = segment.p0.lerp(segment.c1, t)
        b = segment.c1.lerp(segment.p1, t)
        return a.lerp(b, t)
    a = segment.p0.lerp(segment.c1, t)
    b = segment.c1.lerp(segment.c2, t)
    c = segment.c2.lerp(segment.p1, t)
    return a.lerp(b, t).lerp(b.lerp(c, t), t)


def split(segment: Segment, t: float = 0.5) -> tuple[Segment, Segment]:
    if not 0.0 < t < 1.0:
        raise ValueError("split t must be within (0,1)")
    if isinstance(segment, Line):
        midpoint = segment.p0.lerp(segment.p1, t)
        return Line(segment.p0, midpoint), Line(midpoint, segment.p1)
    if isinstance(segment, Quadratic):
        a = segment.p0.lerp(segment.c1, t)
        b = segment.c1.lerp(segment.p1, t)
        midpoint = a.lerp(b, t)
        return Quadratic(segment.p0, a, midpoint), Quadratic(midpoint, b, segment.p1)
    a = segment.p0.lerp(segment.c1, t)
    b = segment.c1.lerp(segment.c2, t)
    c = segment.c2.lerp(segment.p1, t)
    d = a.lerp(b, t)
    e = b.lerp(c, t)
    midpoint = d.lerp(e, t)
    return Cubic(segment.p0, a, d, midpoint), Cubic(midpoint, e, c, segment.p1)


def tangent(segment: Segment, t: float) -> Point2:
    if isinstance(segment, Line):
        dx, dy = segment.p1.x - segment.p0.x, segment.p1.y - segment.p0.y
    elif isinstance(segment, Quadratic):
        dx = 2 * ((1 - t) * (segment.c1.x - segment.p0.x) + t * (segment.p1.x - segment.c1.x))
        dy = 2 * ((1 - t) * (segment.c1.y - segment.p0.y) + t * (segment.p1.y - segment.c1.y))
    else:
        dx = 3 * (
            (1 - t) ** 2 * (segment.c1.x - segment.p0.x)
            + 2 * (1 - t) * t * (segment.c2.x - segment.c1.x)
            + t**2 * (segment.p1.x - segment.c2.x)
        )
        dy = 3 * (
            (1 - t) ** 2 * (segment.c1.y - segment.p0.y)
            + 2 * (1 - t) * t * (segment.c2.y - segment.c1.y)
            + t**2 * (segment.p1.y - segment.c2.y)
        )
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("tangent is undefined at stationary point")
    return Point2(dx / length, dy / length)

