"""Dependency-free canonical stroke geometry."""

from .curves import Cubic, Line, Point2, Quadratic, Segment, Stroke, StrokeSet
from .bounds import Bounds, curve_bounds, ink_bounds
from .transforms import Affine2

__all__ = [
    "Affine2",
    "Bounds",
    "Cubic",
    "Line",
    "Point2",
    "Quadratic",
    "Segment",
    "Stroke",
    "StrokeSet",
    "curve_bounds",
    "ink_bounds",
]

