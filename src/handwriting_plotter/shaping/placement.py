"""Place complete glyphs and anchors into WordFrame millimetres."""

from __future__ import annotations

import math
from dataclasses import dataclass

from handwriting_plotter.geometry.curves import Cubic, Line, Point2, Quadratic, Segment, Stroke
from handwriting_plotter.styles.models import EndpointAnchor, GlyphVariant

from .resolve import GlyphMatch
from .variants import EffectiveVariation


@dataclass(frozen=True, slots=True)
class PlacedAnchor:
    point: Point2
    tangent: Point2
    class_id: str
    allowed_partner_classes: tuple[str, ...]
    max_gap_mm: float
    max_vertical_delta_mm: float
    max_angle_deg: float


@dataclass(frozen=True, slots=True)
class PlacedGlyph:
    match: GlyphMatch
    variant_id: str
    strokes: tuple[Stroke, ...]
    advance_mm: float
    entry: PlacedAnchor | None
    exit: PlacedAnchor | None
    body_stroke_id: str | None
    deferred_marks: tuple[str, ...]
    join_mode: str


def _convert(point: Point2, x_offset: float, factor: float, variation: EffectiveVariation) -> Point2:
    scaled = factor * variation.scale
    shear = math.tan(math.radians(variation.shear_deg))
    return Point2(
        x_offset + (point.x + shear * point.y) * scaled,
        -point.y * scaled + variation.baseline_offset_mm,
    )


def _segment(segment: Segment, x_offset: float, factor: float, variation: EffectiveVariation) -> Segment:
    if isinstance(segment, Line):
        return Line(_convert(segment.p0, x_offset, factor, variation), _convert(segment.p1, x_offset, factor, variation))
    if isinstance(segment, Quadratic):
        return Quadratic(
            _convert(segment.p0, x_offset, factor, variation),
            _convert(segment.c1, x_offset, factor, variation),
            _convert(segment.p1, x_offset, factor, variation),
        )
    return Cubic(
        _convert(segment.p0, x_offset, factor, variation),
        _convert(segment.c1, x_offset, factor, variation),
        _convert(segment.c2, x_offset, factor, variation),
        _convert(segment.p1, x_offset, factor, variation),
    )


def _anchor(
    value: EndpointAnchor | None,
    strokes: tuple[Stroke, ...],
    factor: float,
    variation: EffectiveVariation,
) -> PlacedAnchor | None:
    if value is None:
        return None
    stroke = next(item for item in strokes if item.id.endswith("/" + value.stroke_id))
    point = stroke.start if value.endpoint == "start" else stroke.end
    shear = math.tan(math.radians(variation.shear_deg))
    dx = value.tangent.x + shear * value.tangent.y
    dy = -value.tangent.y
    length = math.hypot(dx, dy)
    tangent = Point2(dx / length, dy / length)
    scale = factor * variation.scale
    return PlacedAnchor(
        point,
        tangent,
        value.class_id,
        value.allowed_partner_classes,
        value.max_gap_gu * scale,
        value.max_vertical_delta_gu * scale,
        value.max_angle_deg,
    )


def place_glyph(
    match: GlyphMatch,
    variant: GlyphVariant,
    x_offset_mm: float,
    x_height_mm: float,
    variation: EffectiveVariation,
) -> PlacedGlyph:
    factor = x_height_mm / 1000.0
    prefix = match.occurrence_id
    source_refs = tuple(item.id for item in match.graphemes)
    strokes = tuple(
        Stroke(
            f"{prefix}/{stroke.id}",
            tuple(_segment(segment, x_offset_mm, factor, variation) for segment in stroke.segments),
            source_refs,
            stroke.role,
            stroke.direction_provenance,
        )
        for stroke in variant.strokes
    )
    spec = variant.join_spec
    return PlacedGlyph(
        match,
        variant.variant_id,
        strokes,
        variant.advance_gu * factor * variation.scale,
        _anchor(spec.entry, strokes, factor, variation),
        _anchor(spec.exit, strokes, factor, variation),
        f"{prefix}/{spec.body_stroke_id}" if spec.body_stroke_id else None,
        tuple(f"{prefix}/{item}" for item in spec.deferred_marks),
        spec.mode,
    )

