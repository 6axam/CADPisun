"""Validated external StylePack models and immutable runtime snapshot."""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Literal, Mapping, Union

from pydantic import ConfigDict, Field, TypeAdapter, field_validator

from handwriting_plotter.domain.models import StrictModel
from handwriting_plotter.geometry.curves import Cubic, Line, Point2, Quadratic, Segment, Stroke, tangent as segment_tangent


class PointModel(StrictModel):
    x: float
    y: float


class LineModel(StrictModel):
    kind: Literal["line"]
    p0: PointModel
    p1: PointModel


class QuadraticModel(StrictModel):
    kind: Literal["quadratic"]
    p0: PointModel
    c1: PointModel
    p1: PointModel


class CubicModel(StrictModel):
    kind: Literal["cubic"]
    p0: PointModel
    c1: PointModel
    c2: PointModel
    p1: PointModel


SegmentModel = Annotated[Union[LineModel, QuadraticModel, CubicModel], Field(discriminator="kind")]
SEGMENT_ADAPTER = TypeAdapter(SegmentModel)


class StrokeModel(StrictModel):
    id: str
    segments: tuple[SegmentModel, ...]
    source_refs: tuple[str, ...] = ()
    role: Literal["body", "mark", "connector", "punctuation", "diagnostic"] = "body"
    direction_provenance: Literal["captured", "authored", "inferred", "unknown"]

    @field_validator("segments")
    @classmethod
    def nonempty(cls, value: tuple[SegmentModel, ...]) -> tuple[SegmentModel, ...]:
        if not value:
            raise ValueError("stroke must not be empty")
        return value


class EndpointAnchorModel(StrictModel):
    stroke_id: str
    endpoint: Literal["start", "end"]
    tangent: PointModel
    class_id: str
    allowed_partner_classes: tuple[str, ...]
    max_gap_gu: float = Field(gt=0)
    max_vertical_delta_gu: float = Field(ge=0)
    max_angle_deg: float = Field(gt=0, le=180)


class JoinSpecModel(StrictModel):
    mode: Literal["none", "single_body_deferred_marks"] = "none"
    body_stroke_id: str | None = None
    deferred_marks: tuple[str, ...] = ()
    entry: EndpointAnchorModel | None = None
    exit: EndpointAnchorModel | None = None
    no_join_before: bool = False
    no_join_after: bool = False


class ProvenanceModel(StrictModel):
    license_id: str
    source_method: Literal["manual_vector", "online_capture", "offline_reconstruction"]
    author_id: str | None = None
    source_asset_hash: str | None = None
    transforms: tuple[str, ...] = ()
    reviewed_by: str | None = None
    review_record_id: str | None = None


class GlyphVariantFile(StrictModel):
    format: Literal["hp-glyph"]
    schema_version: Literal["1.0"]
    variant_id: str
    key: str
    strokes: tuple[StrokeModel, ...]
    advance_gu: float = Field(gt=0)
    context_tags: frozenset[Literal["isolated", "initial", "medial", "final"]]
    join_spec: JoinSpecModel
    provenance: ProvenanceModel
    review_status: Literal["draft", "approved", "rejected"]
    critical_features: tuple[str, ...] = ()

    @field_validator("key")
    @classmethod
    def key_is_nonspace(cls, value: str) -> str:
        if not value or any(char.isspace() for char in value):
            raise ValueError("glyph key must be non-whitespace")
        return value


class StyleMetricsModel(StrictModel):
    x_height_gu: float = 1000.0
    ascender_gu: float
    descender_gu: float
    space_advance_gu: float = Field(default=900.0, gt=0)
    line_gap_gu: float = Field(default=500.0, ge=0)
    supported_x_height_mm: tuple[float, float]

    @field_validator("supported_x_height_mm")
    @classmethod
    def ordered_range(cls, value: tuple[float, float]) -> tuple[float, float]:
        if len(value) != 2 or value[0] <= 0 or value[0] > value[1]:
            raise ValueError("invalid x-height range")
        return value


class VariationPolicyModel(StrictModel):
    max_scale_fraction: float = Field(default=0.02, ge=0, le=0.02)
    max_shear_deg: float = Field(default=2.0, ge=0, le=2.0)
    max_baseline_offset_mm: float = Field(default=0.08, ge=0, le=0.08)
    max_word_space_fraction: float = Field(default=0.05, ge=0, le=0.05)
    max_line_y_mm: float = Field(default=0.10, ge=0, le=0.10)


class LicenseRecordModel(StrictModel):
    license_id: str
    name: str
    redistribution_allowed: bool


class StyleManifest(StrictModel):
    format: Literal["hp-style"]
    schema_version: str
    style_id: str
    revision: str
    display_name: str
    scripts: tuple[str, ...]
    license_record: LicenseRecordModel
    glyph_frame: Literal["GlyphFrame"]
    metrics: StyleMetricsModel
    coverage: tuple[str, ...]
    glyph_files: tuple[str, ...]
    join_rules: dict[str, object] = Field(default_factory=dict)
    variation_policy: VariationPolicyModel = Field(default_factory=VariationPolicyModel)
    file_hashes: dict[str, str]
    approved: bool = False
    production_eligible: bool = False
    test_only: bool = False


@dataclass(frozen=True, slots=True)
class EndpointAnchor:
    stroke_id: str
    endpoint: str
    tangent: Point2
    class_id: str
    allowed_partner_classes: tuple[str, ...]
    max_gap_gu: float
    max_vertical_delta_gu: float
    max_angle_deg: float


@dataclass(frozen=True, slots=True)
class JoinSpec:
    mode: str
    body_stroke_id: str | None
    deferred_marks: tuple[str, ...]
    entry: EndpointAnchor | None
    exit: EndpointAnchor | None
    no_join_before: bool
    no_join_after: bool


@dataclass(frozen=True, slots=True)
class GlyphVariant:
    variant_id: str
    key: str
    strokes: tuple[Stroke, ...]
    advance_gu: float
    context_tags: frozenset[str]
    join_spec: JoinSpec
    critical_features: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StyleSnapshot:
    manifest: StyleManifest
    variants_by_key: Mapping[str, tuple[GlyphVariant, ...]]
    revision_hash: str

    @classmethod
    def frozen(
        cls,
        manifest: StyleManifest,
        variants_by_key: dict[str, list[GlyphVariant]],
        revision_hash: str,
    ) -> StyleSnapshot:
        mapping = MappingProxyType({key: tuple(value) for key, value in sorted(variants_by_key.items())})
        return cls(manifest, mapping, revision_hash)


def _point(value: PointModel) -> Point2:
    return Point2(value.x, value.y)


def to_segment(value: SegmentModel) -> Segment:
    if isinstance(value, LineModel):
        return Line(_point(value.p0), _point(value.p1))
    if isinstance(value, QuadraticModel):
        return Quadratic(_point(value.p0), _point(value.c1), _point(value.p1))
    return Cubic(_point(value.p0), _point(value.c1), _point(value.c2), _point(value.p1))


def to_variant(value: GlyphVariantFile) -> GlyphVariant:
    strokes = tuple(
        Stroke(
            stroke.id,
            tuple(to_segment(segment) for segment in stroke.segments),
            stroke.source_refs,
            stroke.role,
            stroke.direction_provenance,
        )
        for stroke in value.strokes
    )
    ids = {stroke.id for stroke in strokes}
    if len(ids) != len(strokes):
        raise ValueError("duplicate stroke id")
    spec = value.join_spec
    if spec.mode == "single_body_deferred_marks":
        if spec.body_stroke_id not in ids or any(mark not in ids for mark in spec.deferred_marks):
            raise ValueError("join spec references missing stroke")
        if len([stroke for stroke in strokes if stroke.role == "body"]) != 1:
            raise ValueError("joinable glyph must have exactly one body stroke")
    elif spec.entry is not None or spec.exit is not None:
        raise ValueError("anchors require joinable mode")
    if any(feature not in ids for feature in value.critical_features):
        raise ValueError("critical feature references missing stroke")

    def anchor(item: EndpointAnchorModel | None) -> EndpointAnchor | None:
        if item is None:
            return None
        if item.stroke_id not in ids:
            raise ValueError("anchor references missing stroke")
        length = (item.tangent.x**2 + item.tangent.y**2) ** 0.5
        if not 0.999 <= length <= 1.001:
            raise ValueError("anchor tangent must be unit length")
        stroke = next(stroke for stroke in strokes if stroke.id == item.stroke_id)
        segment = stroke.segments[0] if item.endpoint == "start" else stroke.segments[-1]
        actual = segment_tangent(segment, 0.0 if item.endpoint == "start" else 1.0)
        dot = max(-1.0, min(1.0, actual.x * item.tangent.x + actual.y * item.tangent.y))
        if math.degrees(math.acos(dot)) > 1.0:
            raise ValueError("anchor tangent disagrees with stroke geometry")
        return EndpointAnchor(
            item.stroke_id,
            item.endpoint,
            _point(item.tangent),
            item.class_id,
            item.allowed_partner_classes,
            item.max_gap_gu,
            item.max_vertical_delta_gu,
            item.max_angle_deg,
        )

    return GlyphVariant(
        value.variant_id,
        value.key,
        strokes,
        value.advance_gu,
        value.context_tags,
        JoinSpec(
            spec.mode,
            spec.body_stroke_id,
            spec.deferred_marks,
            anchor(spec.entry),
            anchor(spec.exit),
            spec.no_join_before,
            spec.no_join_after,
        ),
        value.critical_features,
    )

