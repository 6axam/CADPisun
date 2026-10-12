"""Restricted centerline SVG path importer."""

from __future__ import annotations

import re
from dataclasses import dataclass

from defusedxml import ElementTree
from svg.path import Arc, Close, CubicBezier, Line as SvgLine, Move, QuadraticBezier, parse_path

from handwriting_plotter.geometry.curves import Cubic, Line, Point2, Quadratic, Stroke
from handwriting_plotter.geometry.transforms import Affine2, transform_segment


@dataclass(frozen=True, slots=True)
class ImportPolicy:
    max_bytes: int = 20 * 1024 * 1024
    max_paths: int = 100_000
    max_coordinates: int = 2_000_000
    snap_tolerance_gu: float = 0.001
    author_review_required: bool = True


_TRANSFORM = re.compile(r"([a-zA-Z]+)\s*\(([^)]*)\)")


def _point(value: complex) -> Point2:
    return Point2(float(value.real), float(value.imag))


def _transform(value: str | None) -> Affine2:
    result = Affine2(1, 0, 0, 1, 0, 0, "svg", "svg-normalized")
    if not value:
        return result
    matrices: list[Affine2] = []
    for name, arguments in _TRANSFORM.findall(value):
        numbers = [float(item) for item in re.split(r"[\s,]+", arguments.strip()) if item]
        if name == "translate" and len(numbers) in (1, 2):
            matrices.append(Affine2(1, 0, 0, 1, numbers[0], numbers[1] if len(numbers) == 2 else 0, "x", "y"))
        elif name == "scale" and len(numbers) in (1, 2):
            matrices.append(Affine2(numbers[0], 0, 0, numbers[-1], 0, 0, "x", "y"))
        elif name == "matrix" and len(numbers) == 6:
            matrices.append(Affine2(*numbers, "x", "y"))
        else:
            raise ValueError("UNSUPPORTED_SVG_FEATURE:transform")
    a, b, c, d, tx, ty = result.a, result.b, result.c, result.d, result.tx, result.ty
    for matrix in matrices:
        a, b, c, d, tx, ty = (
            matrix.a * a + matrix.c * b,
            matrix.b * a + matrix.d * b,
            matrix.a * c + matrix.c * d,
            matrix.b * c + matrix.d * d,
            matrix.a * tx + matrix.c * ty + matrix.tx,
            matrix.b * tx + matrix.d * ty + matrix.ty,
        )
    return Affine2(a, b, c, d, tx, ty, "svg", "svg-normalized")


def import_centerline_svg(data: bytes, policy: ImportPolicy = ImportPolicy()) -> tuple[Stroke, ...]:
    if len(data) > policy.max_bytes:
        raise ValueError("RESOURCE_LIMIT")
    root = ElementTree.fromstring(data)
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("UNSUPPORTED_SVG_FEATURE:root")
    allowed = {"svg", "g", "path"}
    strokes: list[Stroke] = []
    coordinate_count = 0
    path_count = 0
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in allowed:
            raise ValueError(f"UNSUPPORTED_SVG_FEATURE:{tag}")
        if tag != "path":
            continue
        path_count += 1
        if path_count > policy.max_paths:
            raise ValueError("RESOURCE_LIMIT")
        if element.attrib.get("fill", "none").strip().lower() != "none":
            raise ValueError("UNSUPPORTED_SVG_FEATURE:filled-path")
        if any(key.rsplit("}", 1)[-1] in {"href", "style", "class", "filter", "mask", "clip-path"} for key in element.attrib):
            raise ValueError("UNSUPPORTED_SVG_FEATURE:attribute")
        parsed = parse_path(element.attrib.get("d", ""))
        transform = _transform(element.attrib.get("transform"))
        current: list = []
        subpath_index = 0
        for item in parsed:
            if isinstance(item, Move):
                if current:
                    strokes.append(Stroke(f"svg-{path_count}-{subpath_index}", tuple(current), role="body", direction_provenance="authored"))
                    current = []
                    subpath_index += 1
                continue
            if isinstance(item, Arc):
                raise ValueError("UNSUPPORTED_PATH_COMMAND:A")
            if isinstance(item, Close):
                if item.start != item.end:
                    current.append(transform_segment(Line(_point(item.start), _point(item.end)), transform))
                continue
            if isinstance(item, SvgLine):
                segment = Line(_point(item.start), _point(item.end))
                coordinate_count += 4
            elif isinstance(item, QuadraticBezier):
                segment = Quadratic(_point(item.start), _point(item.control), _point(item.end))
                coordinate_count += 6
            elif isinstance(item, CubicBezier):
                segment = Cubic(_point(item.start), _point(item.control1), _point(item.control2), _point(item.end))
                coordinate_count += 8
            else:
                raise ValueError("UNSUPPORTED_PATH_COMMAND")
            if coordinate_count > policy.max_coordinates:
                raise ValueError("RESOURCE_LIMIT")
            converted = transform_segment(segment, transform)
            if current and current[-1].p1 != converted.p0:
                if current[-1].p1.distance_to(converted.p0) <= policy.snap_tolerance_gu:
                    if isinstance(converted, Line):
                        converted = Line(current[-1].p1, converted.p1)
                    elif isinstance(converted, Quadratic):
                        converted = Quadratic(current[-1].p1, converted.c1, converted.p1)
                    else:
                        converted = Cubic(current[-1].p1, converted.c1, converted.c2, converted.p1)
                else:
                    raise ValueError("DISCONTINUOUS_STROKE")
            current.append(converted)
        if current:
            strokes.append(Stroke(f"svg-{path_count}-{subpath_index}", tuple(current), role="body", direction_provenance="authored"))
    if not strokes:
        raise ValueError("EMPTY_STROKE")
    return tuple(strokes)

