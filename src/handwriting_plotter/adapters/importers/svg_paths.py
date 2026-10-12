"""Restricted centerline SVG path importer."""

from __future__ import annotations

import re
import math
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
_PLAIN_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def _point(value: complex) -> Point2:
    return Point2(float(value.real), float(value.imag))


def _compose(outer: Affine2, inner: Affine2) -> Affine2:
    return Affine2(
        outer.a * inner.a + outer.c * inner.b,
        outer.b * inner.a + outer.d * inner.b,
        outer.a * inner.c + outer.c * inner.d,
        outer.b * inner.c + outer.d * inner.d,
        outer.a * inner.tx + outer.c * inner.ty + outer.tx,
        outer.b * inner.tx + outer.d * inner.ty + outer.ty,
        "svg",
        "svg-normalized",
    )


def _identity() -> Affine2:
    return Affine2(1, 0, 0, 1, 0, 0, "svg", "svg-normalized")


def _transform(value: str | None) -> Affine2:
    result = _identity()
    if not value:
        return result
    remainder = _TRANSFORM.sub("", value)
    if remainder.replace(",", " ").strip():
        raise ValueError("UNSUPPORTED_SVG_FEATURE:transform")
    matrices: list[Affine2] = []
    for name, arguments in _TRANSFORM.findall(value):
        numbers = [float(item) for item in re.split(r"[\s,]+", arguments.strip()) if item]
        if name == "translate" and len(numbers) in (1, 2):
            matrices.append(Affine2(1, 0, 0, 1, numbers[0], numbers[1] if len(numbers) == 2 else 0, "x", "y"))
        elif name == "scale" and len(numbers) in (1, 2):
            matrices.append(Affine2(numbers[0], 0, 0, numbers[-1], 0, 0, "x", "y"))
        elif name == "matrix" and len(numbers) == 6:
            matrices.append(Affine2(*numbers, "x", "y"))
        elif name == "rotate" and len(numbers) in (1, 3):
            angle = math.radians(numbers[0])
            rotation = Affine2(math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 0, 0, "x", "y")
            if len(numbers) == 3:
                cx, cy = numbers[1:]
                rotation = _compose(
                    Affine2(1, 0, 0, 1, cx, cy, "x", "y"),
                    _compose(rotation, Affine2(1, 0, 0, 1, -cx, -cy, "x", "y")),
                )
            matrices.append(rotation)
        else:
            raise ValueError("UNSUPPORTED_SVG_FEATURE:transform")
    for matrix in matrices:
        result = _compose(matrix, result)
    return result


def import_centerline_svg(data: bytes, policy: ImportPolicy = ImportPolicy()) -> tuple[Stroke, ...]:
    if len(data) > policy.max_bytes:
        raise ValueError("RESOURCE_LIMIT")
    root = ElementTree.fromstring(data)
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise ValueError("UNSUPPORTED_SVG_FEATURE:root")
    for attribute in ("width", "height"):
        if not _PLAIN_NUMBER.fullmatch(root.attrib.get(attribute, "")):
            raise ValueError(f"UNSUPPORTED_SVG_FEATURE:{attribute}")
    try:
        view_box = [float(item) for item in re.split(r"[\s,]+", root.attrib.get("viewBox", "").strip()) if item]
    except ValueError as error:
        raise ValueError("UNSUPPORTED_SVG_FEATURE:viewBox") from error
    if len(view_box) != 4 or view_box[2] <= 0 or view_box[3] <= 0 or not all(math.isfinite(item) for item in view_box):
        raise ValueError("UNSUPPORTED_SVG_FEATURE:viewBox")
    allowed = {"svg", "g", "path"}
    strokes: list[Stroke] = []
    coordinate_count = 0
    path_count = 0
    def walk(element, inherited_transform: Affine2, inherited_fill: str, depth: int) -> None:
        nonlocal coordinate_count, path_count
        if depth > 64:
            raise ValueError("RESOURCE_LIMIT")
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in allowed:
            raise ValueError(f"UNSUPPORTED_SVG_FEATURE:{tag}")
        forbidden = {"href", "style", "class", "filter", "mask", "clip-path"}
        if any(key.rsplit("}", 1)[-1] in forbidden for key in element.attrib):
            raise ValueError("UNSUPPORTED_SVG_FEATURE:attribute")
        local_transform = _transform(element.attrib.get("transform"))
        effective_transform = _compose(inherited_transform, local_transform)
        effective_fill = element.attrib.get("fill", inherited_fill).strip().lower()
        if tag != "path":
            for child in element:
                walk(child, effective_transform, effective_fill, depth + 1)
            return
        path_count += 1
        if path_count > policy.max_paths:
            raise ValueError("RESOURCE_LIMIT")
        if effective_fill != "none":
            raise ValueError("UNSUPPORTED_SVG_FEATURE:filled-path")
        parsed = parse_path(element.attrib.get("d", ""))
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
                    current.append(transform_segment(Line(_point(item.start), _point(item.end)), effective_transform))
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
            converted = transform_segment(segment, effective_transform)
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
    walk(root, _identity(), "black", 0)
    if not strokes:
        raise ValueError("EMPTY_STROKE")
    return tuple(strokes)

