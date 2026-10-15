"""Manual, auditable glyph annotation and existing-engine join preview."""

from __future__ import annotations

import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads
from handwriting_plotter.geometry.curves import Point2, Stroke, tangent
from handwriting_plotter.shaping.joins import RejectedJoin, connect
from handwriting_plotter.shaping.placement import place_glyph
from handwriting_plotter.shaping.resolve import GlyphMatch
from handwriting_plotter.shaping.variants import EffectiveVariation
from handwriting_plotter.styles.models import (
    EndpointAnchorModel,
    GlyphVariantFile,
    JoinSpecModel,
    PointModel,
    ProvenanceModel,
    StrokeModel,
    to_variant,
)
from handwriting_plotter.text.normalize import normalize

from .metrics import NormalizedGlyph, NormalizedRepository, segment_to_model

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StrokeRoleAssignment(StrictModel):
    stroke_id: str = Field(min_length=1, max_length=128)
    role: Literal["body", "mark", "punctuation"]


class AnchorAnnotation(StrictModel):
    stroke_id: str = Field(min_length=1, max_length=128)
    endpoint: Literal["start", "end"]
    tangent: PointModel
    class_id: str = Field(min_length=1, max_length=64)
    allowed_partner_classes: tuple[str, ...]
    max_gap_gu: float = Field(gt=0)
    max_vertical_delta_gu: float = Field(ge=0)
    max_angle_deg: float = Field(gt=0, le=180)

    @model_validator(mode="after")
    def unit_tangent_and_classes(self) -> AnchorAnnotation:
        length = math.hypot(self.tangent.x, self.tangent.y)
        if not 0.999 <= length <= 1.001:
            raise ValueError("annotation tangent must be a unit vector")
        if not self.allowed_partner_classes or len(self.allowed_partner_classes) != len(set(self.allowed_partner_classes)):
            raise ValueError("allowed partner classes must be nonempty and unique")
        return self


class GlyphAnnotation(StrictModel):
    format: Literal["hp-glyph-annotation"] = "hp-glyph-annotation"
    schema_version: Literal["1.0"] = "1.0"
    source_normalized_sha256: str
    source_processed_sha256: str
    variant_id: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=256)
    revision: int = Field(default=1, ge=1)
    context_tags: frozenset[Literal["isolated", "initial", "medial", "final"]] = frozenset({"isolated"})
    stroke_order: tuple[str, ...]
    stroke_roles: tuple[StrokeRoleAssignment, ...]
    join_mode: Literal["none", "single_body_deferred_marks"] = "none"
    body_stroke_id: str | None = None
    deferred_marks: tuple[str, ...] = ()
    entry: AnchorAnnotation | None = None
    exit: AnchorAnnotation | None = None
    no_join_before: bool = False
    no_join_after: bool = False
    critical_features: tuple[str, ...] = ()
    review_status: Literal["draft", "reviewed"] = "draft"

    @field_validator("source_normalized_sha256", "source_processed_sha256")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("INVALID_ANNOTATION_HASH")
        return value

    @model_validator(mode="after")
    def internal_consistency(self) -> GlyphAnnotation:
        if not self.context_tags:
            raise ValueError("at least one context tag is required")
        if not self.stroke_order or len(self.stroke_order) != len(set(self.stroke_order)):
            raise ValueError("stroke order must be nonempty and unique")
        role_ids = tuple(item.stroke_id for item in self.stroke_roles)
        if role_ids != self.stroke_order:
            raise ValueError("stroke roles must follow complete original order")
        if len(self.critical_features) != len(set(self.critical_features)):
            raise ValueError("duplicate critical feature")
        return self


@dataclass(frozen=True, slots=True)
class AnnotationValidationReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.errors


class PairJoinPreview(StrictModel):
    left_variant_id: str
    right_variant_id: str
    decision: Literal["connected", "pen_lift", "rejected"]
    reason: str
    units: Literal["mm"] = "mm"
    connector: StrokeModel | None = None


def _actual_tangent(stroke: Stroke, endpoint: Literal["start", "end"]) -> Point2:
    segment = stroke.segments[0] if endpoint == "start" else stroke.segments[-1]
    return tangent(segment, 0.0 if endpoint == "start" else 1.0)


def create_anchor_annotation(
    glyph: NormalizedGlyph,
    stroke_id: str,
    endpoint: Literal["start", "end"],
    *,
    class_id: str = "cursive",
    allowed_partner_classes: tuple[str, ...] = ("cursive",),
    max_gap_gu: float = 500.0,
    max_vertical_delta_gu: float = 200.0,
    max_angle_deg: float = 60.0,
) -> AnchorAnnotation:
    try:
        stroke = next(item for item in glyph.to_strokes() if item.id == stroke_id)
    except StopIteration as exc:
        raise KeyError(stroke_id) from exc
    value = _actual_tangent(stroke, endpoint)
    return AnchorAnnotation(
        stroke_id=stroke_id,
        endpoint=endpoint,
        tangent=PointModel(x=value.x, y=value.y),
        class_id=class_id,
        allowed_partner_classes=allowed_partner_classes,
        max_gap_gu=max_gap_gu,
        max_vertical_delta_gu=max_vertical_delta_gu,
        max_angle_deg=max_angle_deg,
    )


def validate_annotation(annotation: GlyphAnnotation, glyph: NormalizedGlyph) -> AnnotationValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    if annotation.source_processed_sha256 != glyph.source_processed_sha256:
        errors.append("ANNOTATION_PROCESSED_SOURCE_MISMATCH")
    if annotation.variant_id != glyph.variant_id or annotation.label != glyph.label:
        errors.append("ANNOTATION_GLYPH_IDENTITY_MISMATCH")
    ids = tuple(stroke.id for stroke in glyph.to_strokes())
    if annotation.stroke_order != ids:
        errors.append("ANNOTATION_STROKE_ORDER_CHANGED")
    role_map = {item.stroke_id: item.role for item in annotation.stroke_roles}
    if set(role_map) != set(ids):
        errors.append("ANNOTATION_STROKE_ROLES_INCOMPLETE")
    if any(item not in ids for item in annotation.critical_features):
        errors.append("ANNOTATION_CRITICAL_FEATURE_MISSING")

    if annotation.join_mode == "none":
        if annotation.body_stroke_id is not None or annotation.deferred_marks or annotation.entry or annotation.exit:
            errors.append("ANNOTATION_JOIN_NONE_HAS_JOIN_DATA")
        if not annotation.no_join_before or not annotation.no_join_after:
            warnings.append("ANNOTATION_JOIN_MODE_NONE_IMPLIES_PEN_LIFT")
    else:
        bodies = [stroke_id for stroke_id, role in role_map.items() if role == "body"]
        if len(bodies) != 1 or annotation.body_stroke_id != (bodies[0] if bodies else None):
            errors.append("ANNOTATION_REQUIRES_ONE_BODY_STROKE")
        expected_marks = tuple(stroke_id for stroke_id in ids if stroke_id != annotation.body_stroke_id)
        if annotation.deferred_marks != expected_marks:
            errors.append("ANNOTATION_DEFERRED_MARK_ORDER_MISMATCH")
        if any(role_map.get(item) != "mark" for item in annotation.deferred_marks):
            errors.append("ANNOTATION_DEFERRED_STROKE_NOT_MARK")
        for name, anchor, expected_endpoint in (
            ("ENTRY", annotation.entry, "start"),
            ("EXIT", annotation.exit, "end"),
        ):
            if anchor is None:
                warnings.append(f"ANNOTATION_{name}_MISSING")
                continue
            if anchor.stroke_id != annotation.body_stroke_id or anchor.endpoint != expected_endpoint:
                errors.append(f"ANNOTATION_{name}_NOT_BODY_ENDPOINT")
                continue
            stroke = next((item for item in glyph.to_strokes() if item.id == anchor.stroke_id), None)
            if stroke is None:
                errors.append(f"ANNOTATION_{name}_STROKE_MISSING")
                continue
            actual = _actual_tangent(stroke, anchor.endpoint)
            dot = max(-1.0, min(1.0, actual.x * anchor.tangent.x + actual.y * anchor.tangent.y))
            if math.degrees(math.acos(dot)) > 1.0:
                errors.append(f"ANNOTATION_{name}_TANGENT_MISMATCH")
    return AnnotationValidationReport(tuple(errors), tuple(warnings))


def annotation_to_glyph_variant(annotation: GlyphAnnotation, glyph: NormalizedGlyph) -> GlyphVariantFile:
    report = validate_annotation(annotation, glyph)
    if not report.passed:
        raise ValueError(";".join(report.errors))
    roles = {item.stroke_id: item.role for item in annotation.stroke_roles}
    strokes = tuple(StrokeModel(
        id=item.id,
        segments=item.segments,
        source_refs=item.source_refs,
        role=roles[item.id],
        direction_provenance=item.direction_provenance,
    ) for item in glyph.strokes)

    def anchor(value: AnchorAnnotation | None) -> EndpointAnchorModel | None:
        if value is None:
            return None
        return EndpointAnchorModel(
            stroke_id=value.stroke_id,
            endpoint=value.endpoint,
            tangent=value.tangent,
            class_id=value.class_id,
            allowed_partner_classes=value.allowed_partner_classes,
            max_gap_gu=value.max_gap_gu,
            max_vertical_delta_gu=value.max_vertical_delta_gu,
            max_angle_deg=value.max_angle_deg,
        )

    return GlyphVariantFile(
        format="hp-glyph",
        schema_version="1.0",
        variant_id=annotation.variant_id,
        key=annotation.label,
        strokes=strokes,
        advance_gu=glyph.advance_gu,
        context_tags=annotation.context_tags,
        join_spec=JoinSpecModel(
            mode=annotation.join_mode,
            body_stroke_id=annotation.body_stroke_id,
            deferred_marks=annotation.deferred_marks,
            entry=anchor(annotation.entry),
            exit=anchor(annotation.exit),
            no_join_before=annotation.no_join_before,
            no_join_after=annotation.no_join_after,
        ),
        provenance=ProvenanceModel(
            license_id="personal-test-only",
            source_method="online_capture",
            source_asset_hash=glyph.source_capture_sha256,
            transforms=(glyph.metric_profile_sha256, glyph.source_processed_sha256),
        ),
        review_status="draft",
        critical_features=annotation.critical_features,
    )


def preview_join(
    left_file: GlyphVariantFile,
    right_file: GlyphVariantFile,
    *,
    x_height_mm: float = 3.5,
    pen_width_mm: float = 0.35,
) -> PairJoinPreview:
    left, right = to_variant(left_file), to_variant(right_file)
    left_graphemes = normalize(left.key).graphemes
    right_graphemes = normalize(right.key).graphemes
    left_match = GlyphMatch(left.key, left_graphemes, (left,), "initial", "preview:left")
    right_match = GlyphMatch(right.key, right_graphemes, (right,), "final", "preview:right")
    variation = EffectiveVariation(1.0, 0.0, 0.0)
    placed_left = place_glyph(left_match, left, 0.0, x_height_mm, variation)
    placed_right = place_glyph(
        right_match, right, left.advance_gu * x_height_mm / 1000.0, x_height_mm, variation
    )
    outcome = connect(placed_left, placed_right, pen_width_mm=pen_width_mm)
    if isinstance(outcome, RejectedJoin):
        intentional = {
            "JOIN_MODE_NONE", "JOIN_FORBIDDEN", "MISSING_ANCHOR",
            "SCRIPT_BOUNDARY", "PUNCTUATION_BOUNDARY",
        }
        return PairJoinPreview(
            left_variant_id=left.variant_id,
            right_variant_id=right.variant_id,
            decision="pen_lift" if outcome.reason in intentional else "rejected",
            reason=outcome.reason,
        )
    segment = outcome.segments[0]
    return PairJoinPreview(
        left_variant_id=left.variant_id,
        right_variant_id=right.variant_id,
        decision="connected",
        reason="JOIN_ACCEPTED",
        connector=StrokeModel(
            id=outcome.id,
            segments=(segment_to_model(segment),),
            source_refs=outcome.source_refs,
            role="connector",
            direction_provenance="authored",
        ),
    )


class AnnotationStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, normalized_hash: str) -> Path:
        if not _SHA256.fullmatch(normalized_hash):
            raise ValueError("INVALID_NORMALIZED_HASH")
        return self.root / "drafts" / "annotations" / f"{normalized_hash}.json"

    def save(self, annotation: GlyphAnnotation) -> Path:
        glyph = NormalizedRepository(self.root).load(
            annotation.source_processed_sha256, annotation.source_normalized_sha256
        )
        report = validate_annotation(annotation, glyph)
        if not report.passed:
            raise ValueError(";".join(report.errors))
        path = self.path_for(annotation.source_normalized_sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            current = self.load(annotation.source_normalized_sha256)
            if current == annotation:
                return path
            if annotation.revision != current.revision + 1:
                raise ValueError("ANNOTATION_REVISION_CONFLICT")
        _atomic_replace(path, canonical_json_bytes(annotation.model_dump(mode="json")))
        return path

    def load(self, normalized_hash: str) -> GlyphAnnotation:
        decoded = strict_json_loads(self.path_for(normalized_hash).read_bytes())
        if not isinstance(decoded, dict) or decoded.get("format") != "hp-glyph-annotation":
            raise ValueError("UNSUPPORTED_ANNOTATION_FORMAT")
        if decoded.get("schema_version") != "1.0":
            raise ValueError("UNSUPPORTED_ANNOTATION_SCHEMA")
        annotation = GlyphAnnotation.model_validate_json(canonical_json_bytes(decoded), strict=True)
        glyph = NormalizedRepository(self.root).load(
            annotation.source_processed_sha256, annotation.source_normalized_sha256
        )
        report = validate_annotation(annotation, glyph)
        if not report.passed:
            raise ValueError(";".join(report.errors))
        return annotation

    def list_all(self) -> tuple[GlyphAnnotation, ...]:
        folder = self.root / "drafts" / "annotations"
        if not folder.is_dir():
            return ()
        return tuple(
            self.load(path.stem)
            for path in sorted(folder.glob("*.json"))
        )


def _atomic_replace(path: Path, content: bytes) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".annotation-", suffix=".tmp", dir=path.parent)
    staging = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        staging.unlink(missing_ok=True)
