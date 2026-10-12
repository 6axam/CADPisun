from __future__ import annotations

import json
import math

import pytest
from hypothesis import given, strategies as st

from handwriting_plotter.domain.models import canonical_json_bytes, strict_json_loads
from handwriting_plotter.geometry.bounds import curve_bounds
from handwriting_plotter.geometry.curves import Cubic, Line, Point2, Quadratic, Stroke, StrokeSet, evaluate
from handwriting_plotter.geometry.flatten import FlattenLimits, flatten_segment
from handwriting_plotter.geometry.collision import segment_distance, segments_intersect
from handwriting_plotter.geometry.transforms import Affine2, transform_strokes


def test_t_g01_rejects_invalid_numbers_and_discontinuous_stroke() -> None:
    with pytest.raises(ValueError):
        Point2(math.inf, 0)
    with pytest.raises(TypeError):
        Point2(True, 0)
    with pytest.raises(ValueError, match="discontinuous"):
        Stroke("s", (Line(Point2(0, 0), Point2(1, 0)), Line(Point2(2, 0), Point2(3, 0))))


def test_t_g02_curve_bounds_include_interior_extremum() -> None:
    curve = Quadratic(Point2(0, 0), Point2(5, 10), Point2(10, 0))
    bounds = curve_bounds(curve)
    assert bounds.max_y == pytest.approx(5.0)
    assert bounds.min_x == 0
    assert bounds.max_x == 10


def test_t_g03_degenerate_loop_flattens_without_becoming_zero() -> None:
    curve = Cubic(Point2(0, 0), Point2(3, 4), Point2(-3, 4), Point2(0, 0))
    lines, depth = flatten_segment(curve, 0.02, FlattenLimits(max_chord_length=1.0))
    assert depth > 0
    assert len(lines) > 4
    assert sum(line.p0.distance_to(line.p1) for line in lines) > 1


@given(
    st.floats(-100, 100, allow_nan=False, allow_infinity=False),
    st.floats(-100, 100, allow_nan=False, allow_infinity=False),
)
def test_t_g04_transform_inverse_roundtrip(x: float, y: float) -> None:
    transform = Affine2(1.2, 0.1, -0.2, 0.9, 5.0, -3.0, "a", "b")
    result = transform.inverse().apply(transform.apply(Point2(x, y)))
    assert result.x == pytest.approx(x, abs=1e-10)
    assert result.y == pytest.approx(y, abs=1e-10)


def test_t_g05_shared_endpoint_is_exact_after_transform() -> None:
    shared = Point2(1, 1)
    strokes = StrokeSet(
        "set", "glyph", "gu", (Stroke("s", (Line(Point2(0, 0), shared), Quadratic(shared, Point2(2, 3), Point2(4, 0)))),)
    )
    result = transform_strokes(strokes, Affine2(0.0035, 0, 0, -0.0035, 2, 3, "glyph", "word"))
    assert result.strokes[0].segments[0].p1 is result.strokes[0].segments[1].p0


def test_t_g06_flatten_error_and_budget() -> None:
    curve = Cubic(Point2(0, 0), Point2(0, 10), Point2(10, 10), Point2(10, 0))
    lines, _ = flatten_segment(curve, 0.01, FlattenLimits(max_chord_length=0.5))
    assert all(line.p0.distance_to(line.p1) <= 0.5 + 1e-12 for line in lines)
    with pytest.raises(ValueError, match="GEOMETRY_BUDGET_EXCEEDED"):
        flatten_segment(curve, 1e-12, FlattenLimits(max_depth=2, max_segments=2))


def test_strict_json_rejects_duplicates_and_nonfinite() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        strict_json_loads('{"x":1,"x":2}')
    with pytest.raises(ValueError, match="non-finite"):
        strict_json_loads('{"x":NaN}')
    assert json.loads(canonical_json_bytes({"я": 2, "a": 1})) == {"a": 1, "я": 2}


def test_cubic_evaluation_endpoints() -> None:
    curve = Cubic(Point2(1, 2), Point2(3, 4), Point2(5, 6), Point2(7, 8))
    assert evaluate(curve, 0) == curve.p0
    assert evaluate(curve, 1) == curve.p1


def test_t_g06_collinear_disjoint_segments_are_not_collisions() -> None:
    first = Line(Point2(0, 0), Point2(1, 0))
    disjoint = Line(Point2(2, 0), Point2(3, 0))
    crossing = Line(Point2(0.5, -1), Point2(0.5, 1))
    assert not segments_intersect(first, disjoint)
    assert segment_distance(first, disjoint) == pytest.approx(1.0)
    assert segments_intersect(first, crossing)

