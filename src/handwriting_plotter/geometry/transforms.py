"""Explicit affine transforms between named coordinate frames."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .curves import Cubic, Line, Point2, Quadratic, Segment, Stroke, StrokeSet


@dataclass(frozen=True, slots=True)
class Affine2:
    a: float
    b: float
    c: float
    d: float
    tx: float
    ty: float
    from_frame: str
    to_frame: str

    def __post_init__(self) -> None:
        if not self.from_frame or not self.to_frame:
            raise ValueError("transform frames are required")
        if not all(math.isfinite(v) for v in (self.a, self.b, self.c, self.d, self.tx, self.ty)):
            raise ValueError("transform values must be finite")
        if abs(self.determinant) < 1e-15:
            raise ValueError("transform must be invertible")

    @property
    def determinant(self) -> float:
        return self.a * self.d - self.b * self.c

    def apply(self, point: Point2) -> Point2:
        return Point2(
            self.a * point.x + self.c * point.y + self.tx,
            self.b * point.x + self.d * point.y + self.ty,
        )

    def inverse(self) -> Affine2:
        determinant = self.determinant
        a, b, c, d = self.d / determinant, -self.b / determinant, -self.c / determinant, self.a / determinant
        return Affine2(
            a,
            b,
            c,
            d,
            -(a * self.tx + c * self.ty),
            -(b * self.tx + d * self.ty),
            self.to_frame,
            self.from_frame,
        )


def transform_segment(segment: Segment, transform: Affine2) -> Segment:
    if isinstance(segment, Line):
        return Line(transform.apply(segment.p0), transform.apply(segment.p1))
    if isinstance(segment, Quadratic):
        return Quadratic(transform.apply(segment.p0), transform.apply(segment.c1), transform.apply(segment.p1))
    return Cubic(
        transform.apply(segment.p0),
        transform.apply(segment.c1),
        transform.apply(segment.c2),
        transform.apply(segment.p1),
    )


def transform_strokes(strokes: StrokeSet, transform: Affine2) -> StrokeSet:
    if strokes.frame_id != transform.from_frame:
        raise ValueError("FRAME_MISMATCH")
    transformed: list[Stroke] = []
    for stroke in strokes.strokes:
        segments: list[Segment] = []
        shared: Point2 | None = None
        for segment in stroke.segments:
            converted = transform_segment(segment, transform)
            if shared is not None:
                if isinstance(converted, Line):
                    converted = Line(shared, converted.p1)
                elif isinstance(converted, Quadratic):
                    converted = Quadratic(shared, converted.c1, converted.p1)
                else:
                    converted = Cubic(shared, converted.c1, converted.c2, converted.p1)
            segments.append(converted)
            shared = converted.p1
        transformed.append(
            Stroke(stroke.id, tuple(segments), stroke.source_refs, stroke.role, stroke.direction_provenance)
        )
    return StrokeSet(strokes.id, transform.to_frame, strokes.units, tuple(transformed), strokes.source_refs)

