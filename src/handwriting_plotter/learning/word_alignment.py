"""Deterministic, uncertainty-preserving word alignment for reviewed line crops.

This is deliberately a word/span stage.  It does not infer letters, ligatures,
or pen paths: a connected handwritten region can remain a shared, ambiguous
area for several text words until TASK 12B has enough evidence to refine it.
"""

from __future__ import annotations

import math
import os
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol

import regex
from pydantic import Field, field_validator, model_validator

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads

from .models import PhotoRegion
from .repository import PhotoRecord, PhotoRepository
from .transcription_review import TranscriptionReviewRecord, TranscriptionReviewRepository

WORD_ALIGNMENT_FORMAT = "hp-word-alignment"
WORD_ALIGNMENT_SCHEMA_VERSION = "1.0"
WORD_ALIGNMENT_ALGORITHM = "word-spans-components/1"
CoordinateSystem = Literal["line-crop-px-top-left"]
SpanKind = Literal["word", "whitespace", "punctuation"]
AlignmentState = Literal["matched", "ambiguous", "unresolved", "non_ink"]

_WORD_PART = r"[\p{L}\p{M}\p{N}]"
_APOSTROPHE = r"['’ʼ]"
_TOKEN_RE = regex.compile(
    rf"(?P<word>{_WORD_PART}+(?:{_APOSTROPHE}{_WORD_PART}+)*|{_APOSTROPHE}{_WORD_PART}+)|"
    r"(?P<whitespace>\s+)|(?P<punctuation>.)",
    flags=regex.VERSION1,
)


class AlignmentStaleError(RuntimeError):
    """An immutable alignment no longer matches its review or crop identity."""


@dataclass(frozen=True, slots=True)
class LineAlignmentContext:
    """Validated bridge to the existing photo/mask/line pipeline, not a copy."""

    line_region: PhotoRegion
    selected_mask_png: bytes
    mask_sha256: str


class LineMaskCropper(Protocol):
    def crop(self, mask_png: bytes, *, line_region: PhotoRegion) -> BinaryInkMask: ...


@dataclass(frozen=True, slots=True)
class BinaryInkMask:
    """A bounded binary crop.  Every foreground pixel, including dots, remains."""

    width_px: int
    height_px: int
    foreground: bytes

    def __post_init__(self) -> None:
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("INVALID_BINARY_MASK_DIMENSIONS")
        if len(self.foreground) != self.width_px * self.height_px:
            raise ValueError("INVALID_BINARY_MASK_LENGTH")
        if any(value not in (0, 1) for value in self.foreground):
            raise ValueError("INVALID_BINARY_MASK_VALUE")

    @classmethod
    def from_rows(cls, rows: tuple[tuple[int, ...], ...]) -> BinaryInkMask:
        if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
            raise ValueError("INVALID_BINARY_MASK_ROWS")
        return cls(len(rows[0]), len(rows), bytes(value for row in rows for value in row))

    def foreground_at(self, x: int, y: int) -> bool:
        return bool(self.foreground[y * self.width_px + x])


def prepare_line_alignment_context(
    *,
    photos: PhotoRepository,
    source: PhotoRecord,
    review: TranscriptionReviewRecord,
) -> LineAlignmentContext:
    """Resolve one selected immutable mask and its line geometry with no fallback.

    A different manifest, selected-mask frame, or absent line invalidates the
    request instead of carrying a review into new segmentation.
    """

    if review.revision.source_manifest_sha256 != source.sha256:
        raise AlignmentStaleError("ALIGNMENT_SOURCE_MANIFEST_STALE")
    mask = source.photo.ink_mask
    if mask is None:
        raise ValueError("ALIGNMENT_REQUIRES_INK_MASK")
    line = next(
        (region for region in source.photo.regions if region.region_id == review.revision.line_id and region.kind == "line"),
        None,
    )
    if line is None or line.frame_id != mask.frame_id:
        raise AlignmentStaleError("ALIGNMENT_LINE_SEGMENTATION_STALE")
    selected_sha256 = mask.raw_sha256 if mask.selected_variant == "raw" else mask.cleaned_sha256
    selected_relative = mask.raw_relative_path if mask.selected_variant == "raw" else mask.cleaned_relative_path
    content = (photos.root / selected_relative).read_bytes()
    if sha256(content).hexdigest() != selected_sha256:
        raise ValueError("ALIGNMENT_MASK_HASH_MISMATCH")
    return LineAlignmentContext(line_region=line, selected_mask_png=content, mask_sha256=selected_sha256)


class TextSpan(StrictModel):
    span_id: str = Field(pattern=r"^span-[0-9]{1,4}$")
    kind: SpanKind
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=16_384)

    @model_validator(mode="after")
    def valid_range(self) -> TextSpan:
        if self.end <= self.start or self.end - self.start != len(self.text):
            raise ValueError("INVALID_TEXT_SPAN_RANGE")
        return self


class InkComponent(StrictModel):
    component_id: str = Field(pattern=r"^component-[0-9]{1,4}$")
    left_px: int = Field(ge=0)
    top_px: int = Field(ge=0)
    right_px: int = Field(gt=0)
    bottom_px: int = Field(gt=0)
    pixel_count: int = Field(gt=0)

    @model_validator(mode="after")
    def positive_box(self) -> InkComponent:
        if self.right_px <= self.left_px or self.bottom_px <= self.top_px:
            raise ValueError("INVALID_INK_COMPONENT_BOX")
        return self


class WordGeometryCandidate(StrictModel):
    candidate_id: str = Field(pattern=r"^geometry-[0-9]{1,4}-[0-9]{1,4}$")
    grouping_variant: int = Field(ge=0, le=31)
    component_ids: tuple[str, ...] = Field(min_length=1, max_length=256)
    left_px: int = Field(ge=0)
    top_px: int = Field(ge=0)
    right_px: int = Field(gt=0)
    bottom_px: int = Field(gt=0)

    @field_validator("component_ids")
    @classmethod
    def unique_components(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("DUPLICATE_GEOMETRY_COMPONENT")
        return value

    @model_validator(mode="after")
    def positive_box(self) -> WordGeometryCandidate:
        if self.right_px <= self.left_px or self.bottom_px <= self.top_px:
            raise ValueError("INVALID_WORD_GEOMETRY_BOX")
        return self


class SpanGeometryAssignment(StrictModel):
    span_id: str = Field(pattern=r"^span-[0-9]{1,4}$")
    state: AlignmentState
    geometry_candidate_ids: tuple[str, ...] = Field(default=(), max_length=32)
    diagnostics: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def state_matches_geometry(self) -> SpanGeometryAssignment:
        if self.state in {"matched", "ambiguous"} and not self.geometry_candidate_ids:
            raise ValueError("GEOMETRY_ASSIGNMENT_REQUIRED")
        if self.state in {"unresolved", "non_ink"} and self.geometry_candidate_ids:
            raise ValueError("UNRESOLVED_SPAN_CANNOT_HAVE_GEOMETRY")
        return self


class WordAlignmentAlternative(StrictModel):
    alternative_id: str = Field(pattern=r"^alternative-[0-9]{1,3}$")
    rank: int = Field(ge=1, le=16)
    grouping_variant: int = Field(ge=0, le=31)
    optimization_cost: float = Field(ge=0.0)
    assignments: tuple[SpanGeometryAssignment, ...] = Field(min_length=1, max_length=4_096)
    diagnostics: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("assignments")
    @classmethod
    def distinct_spans(cls, value: tuple[SpanGeometryAssignment, ...]) -> tuple[SpanGeometryAssignment, ...]:
        if len({assignment.span_id for assignment in value}) != len(value):
            raise ValueError("DUPLICATE_SPAN_ASSIGNMENT")
        return value


class WordAlignment(StrictModel):
    format: Literal["hp-word-alignment"] = WORD_ALIGNMENT_FORMAT
    schema_version: Literal["1.0"] = WORD_ALIGNMENT_SCHEMA_VERSION
    alignment_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    created_at_utc: str
    algorithm_version: Literal["word-spans-components/1"] = WORD_ALIGNMENT_ALGORITHM
    coordinate_system: CoordinateSystem = "line-crop-px-top-left"
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    line_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    crop_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mask_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mask_width_px: int = Field(gt=0)
    mask_height_px: int = Field(gt=0)
    spans: tuple[TextSpan, ...] = Field(min_length=1, max_length=4_096)
    components: tuple[InkComponent, ...] = Field(default=(), max_length=4_096)
    geometry_candidates: tuple[WordGeometryCandidate, ...] = Field(default=(), max_length=4_096)
    alternatives: tuple[WordAlignmentAlternative, ...] = Field(min_length=1, max_length=16)
    diagnostics: tuple[str, ...] = Field(default=(), max_length=64)

    @field_validator("spans")
    @classmethod
    def contiguous_spans(cls, value: tuple[TextSpan, ...]) -> tuple[TextSpan, ...]:
        expected = 0
        for index, span in enumerate(value):
            if span.span_id != f"span-{index}" or span.start != expected:
                raise ValueError("NONCONTIGUOUS_TEXT_SPANS")
            expected = span.end
        return value

    @field_validator("components")
    @classmethod
    def unique_components(cls, value: tuple[InkComponent, ...]) -> tuple[InkComponent, ...]:
        if len({component.component_id for component in value}) != len(value):
            raise ValueError("DUPLICATE_INK_COMPONENT")
        return value

    @model_validator(mode="after")
    def references_are_valid(self) -> WordAlignment:
        span_ids = {span.span_id for span in self.spans}
        candidate_ids = {candidate.candidate_id for candidate in self.geometry_candidates}
        component_ids = {component.component_id for component in self.components}
        for candidate in self.geometry_candidates:
            if not set(candidate.component_ids) <= component_ids:
                raise ValueError("UNKNOWN_CANDIDATE_COMPONENT")
        for alternative in self.alternatives:
            if {assignment.span_id for assignment in alternative.assignments} != span_ids:
                raise ValueError("INCOMPLETE_ALTERNATIVE_ASSIGNMENTS")
            if not all(set(assignment.geometry_candidate_ids) <= candidate_ids for assignment in alternative.assignments):
                raise ValueError("UNKNOWN_ASSIGNMENT_CANDIDATE")
        return self


@dataclass(frozen=True, slots=True)
class WordAlignmentRecord:
    sha256: str
    path: Path
    alignment: WordAlignment


def split_text_spans(text: str) -> tuple[TextSpan, ...]:
    """Partition exact NFC text without dropping whitespace or punctuation."""

    normalized = unicodedata.normalize("NFC", text)
    if not normalized:
        raise ValueError("ALIGNMENT_TEXT_EMPTY")
    spans: list[TextSpan] = []
    for match in _TOKEN_RE.finditer(normalized):
        kind = "word" if match.group("word") is not None else (
            "whitespace" if match.group("whitespace") is not None else "punctuation"
        )
        spans.append(TextSpan(
            span_id=f"span-{len(spans)}", kind=kind, start=match.start(), end=match.end(), text=match.group(),
        ))
    if "".join(span.text for span in spans) != normalized:
        raise ValueError("TEXT_SPAN_PARTITION_FAILED")
    return tuple(spans)


def extract_ink_components(mask: BinaryInkMask) -> tuple[InkComponent, ...]:
    """8-connected components, retaining even one-pixel marks and punctuation."""

    visited = bytearray(mask.width_px * mask.height_px)
    components: list[InkComponent] = []
    for y in range(mask.height_px):
        for x in range(mask.width_px):
            index = y * mask.width_px + x
            if visited[index] or not mask.foreground[index]:
                continue
            visited[index] = 1
            stack = [(x, y)]
            left = right = x
            top = bottom = y
            pixels = 0
            while stack:
                current_x, current_y = stack.pop()
                pixels += 1
                left, right = min(left, current_x), max(right, current_x)
                top, bottom = min(top, current_y), max(bottom, current_y)
                for next_y in range(max(0, current_y - 1), min(mask.height_px, current_y + 2)):
                    for next_x in range(max(0, current_x - 1), min(mask.width_px, current_x + 2)):
                        next_index = next_y * mask.width_px + next_x
                        if not visited[next_index] and mask.foreground[next_index]:
                            visited[next_index] = 1
                            stack.append((next_x, next_y))
            components.append(InkComponent(
                component_id=f"component-{len(components)}", left_px=left, top_px=top,
                right_px=right + 1, bottom_px=bottom + 1, pixel_count=pixels,
            ))
    return tuple(components)


def _group_components(
    components: tuple[InkComponent, ...], *, variant: int, gap_limit: float
) -> tuple[WordGeometryCandidate, ...]:
    if not components:
        return ()
    ordered = tuple(sorted(components, key=lambda component: (component.left_px, component.top_px, component.component_id)))
    groups: list[list[InkComponent]] = [[ordered[0]]]
    previous_right = ordered[0].right_px
    for component in ordered[1:]:
        gap = component.left_px - previous_right
        if gap > gap_limit:
            groups.append([component])
        else:
            groups[-1].append(component)
        previous_right = max(previous_right, component.right_px)
    return tuple(WordGeometryCandidate(
        candidate_id=f"geometry-{variant}-{index}", grouping_variant=variant,
        component_ids=tuple(component.component_id for component in group),
        left_px=min(component.left_px for component in group),
        top_px=min(component.top_px for component in group),
        right_px=max(component.right_px for component in group),
        bottom_px=max(component.bottom_px for component in group),
    ) for index, group in enumerate(groups))


def geometry_grouping_candidates(
    components: tuple[InkComponent, ...], *, max_variants: int = 4
) -> tuple[tuple[WordGeometryCandidate, ...], ...]:
    """Bounded component partitions from horizontal gaps, not a word classifier."""

    if not components:
        return ((),)
    ordered = tuple(sorted(components, key=lambda component: (component.left_px, component.top_px, component.component_id)))
    gaps = [max(0, right.left_px - left.right_px) for left, right in zip(ordered, ordered[1:])]
    positive = sorted(gap for gap in gaps if gap > 0)
    median = positive[len(positive) // 2] if positive else 0.0
    limits = (max(1.0, median * 0.5), max(2.0, median * 1.25), max(4.0, median * 2.5), float("inf"))
    variants: list[tuple[WordGeometryCandidate, ...]] = []
    seen: set[tuple[tuple[str, ...], ...]] = set()
    for limit in limits:
        grouped = _group_components(ordered, variant=len(variants), gap_limit=limit)
        key = tuple(candidate.component_ids for candidate in grouped)
        if key not in seen:
            seen.add(key)
            variants.append(grouped)
        if len(variants) >= max_variants:
            break
    return tuple(variants)


def _bounded_partitions(item_count: int, bucket_count: int, *, limit: int = 16) -> tuple[tuple[tuple[int, ...], ...], ...]:
    """All contiguous non-empty partitions, deliberately capped and ordered."""

    if not 1 <= bucket_count <= item_count:
        return ()
    output: list[tuple[tuple[int, ...], ...]] = []

    def visit(start: int, buckets_left: int, built: list[tuple[int, ...]]) -> None:
        if len(output) >= limit:
            return
        if buckets_left == 1:
            output.append(tuple((*built, tuple(range(start, item_count)))))
            return
        last_start = item_count - buckets_left
        for end in range(start + 1, last_start + 2):
            visit(end, buckets_left - 1, [*built, tuple(range(start, end))])

    visit(0, bucket_count, [])
    return tuple(output)


def _assignment_cost(word_text: str, candidates: tuple[WordGeometryCandidate, ...]) -> float:
    width = sum(candidate.right_px - candidate.left_px for candidate in candidates)
    character_count = max(1, len(word_text.replace("ʼ", "'")))
    # This is a deterministic layout cost, explicitly not a probability or confidence.
    return abs(math.log((width + 1.0) / character_count))


def _word_assignments(
    words: tuple[TextSpan, ...], candidates: tuple[WordGeometryCandidate, ...]
) -> tuple[tuple[dict[str, tuple[str, ...]], float, tuple[str, ...]], ...]:
    """Map contiguous text/candidate groups while retaining under/over-segmentation."""

    if not words:
        return (({}, 0.0, ()),)
    if not candidates:
        return (({word.span_id: () for word in words}, float(len(words)), ("NO_INK_GEOMETRY",)),)
    results: list[tuple[dict[str, tuple[str, ...]], float, tuple[str, ...]]] = []
    if len(candidates) <= len(words):
        for partition in _bounded_partitions(len(words), len(candidates)):
            mapping: dict[str, tuple[str, ...]] = {}
            cost = 0.0
            for candidate, word_indices in zip(candidates, partition, strict=True):
                for word_index in word_indices:
                    word = words[word_index]
                    mapping[word.span_id] = (candidate.candidate_id,)
                    cost += _assignment_cost(word.text, (candidate,))
                cost += max(0, len(word_indices) - 1) * 2.0
            results.append((mapping, cost, ("CONNECTED_WORD_GROUP",) if len(candidates) < len(words) else ()))
    else:
        for partition in _bounded_partitions(len(candidates), len(words)):
            mapping = {}
            cost = 0.0
            for word, candidate_indices in zip(words, partition, strict=True):
                assigned = tuple(candidates[index] for index in candidate_indices)
                mapping[word.span_id] = tuple(candidate.candidate_id for candidate in assigned)
                cost += _assignment_cost(word.text, assigned) + max(0, len(assigned) - 1) * 1.5
            results.append((mapping, cost, ("POSSIBLE_FALSE_COMPONENT_BREAK",)))
    return tuple(results)


def align_reviewed_line(
    *,
    review: TranscriptionReviewRecord,
    mask: BinaryInkMask,
    mask_sha256: str,
    max_alternatives: int = 8,
) -> WordAlignment:
    """Build a bounded alignment record for an accepted/edited review revision."""

    if review.revision.status not in {"edited", "accepted"}:
        raise ValueError("ALIGNMENT_REQUIRES_REVIEWED_TEXT")
    spans = split_text_spans(review.revision.reviewed_text)
    components = extract_ink_components(mask)
    grouped_variants = geometry_grouping_candidates(components)
    word_spans = tuple(span for span in spans if span.kind == "word")
    candidates = tuple(candidate for variant in grouped_variants for candidate in variant)
    alternatives: list[tuple[float, int, dict[str, tuple[str, ...]], tuple[str, ...]]] = []
    for variant_index, grouped in enumerate(grouped_variants):
        for mapping, cost, diagnostics in _word_assignments(word_spans, grouped):
            alternatives.append((cost, variant_index, mapping, diagnostics))
    alternatives.sort(key=lambda item: (item[0], item[1], tuple(sorted(item[2].items()))))
    selected = alternatives[:max(1, min(max_alternatives, 16))]
    rendered: list[WordAlignmentAlternative] = []
    for rank, (cost, variant_index, mapping, diagnostics) in enumerate(selected, start=1):
        assignments: list[SpanGeometryAssignment] = []
        for span in spans:
            candidate_ids = mapping.get(span.span_id, ())
            if span.kind == "whitespace":
                assignments.append(SpanGeometryAssignment(span_id=span.span_id, state="non_ink", diagnostics=("WHITESPACE",)))
            elif span.kind == "punctuation":
                assignments.append(SpanGeometryAssignment(span_id=span.span_id, state="unresolved", diagnostics=("PUNCTUATION_NOT_FORCED",)))
            elif not candidate_ids:
                assignments.append(SpanGeometryAssignment(span_id=span.span_id, state="unresolved", diagnostics=("NO_GEOMETRY",)))
            else:
                state: AlignmentState = "matched" if len(candidate_ids) == 1 and not diagnostics else "ambiguous"
                assignments.append(SpanGeometryAssignment(
                    span_id=span.span_id, state=state, geometry_candidate_ids=candidate_ids, diagnostics=diagnostics,
                ))
        rendered.append(WordAlignmentAlternative(
            alternative_id=f"alternative-{rank - 1}", rank=rank, grouping_variant=variant_index,
            optimization_cost=cost, assignments=tuple(assignments), diagnostics=diagnostics,
        ))
    return WordAlignment(
        alignment_id=str(uuid.uuid4()), created_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        source_manifest_sha256=review.revision.source_manifest_sha256,
        line_id=review.revision.line_id, crop_sha256=review.revision.crop_sha256,
        mask_sha256=mask_sha256, review_revision_sha256=review.sha256,
        reviewed_text_sha256=sha256(review.revision.reviewed_text.encode("utf-8")).hexdigest(),
        mask_width_px=mask.width_px, mask_height_px=mask.height_px, spans=spans,
        components=components, geometry_candidates=candidates, alternatives=tuple(rendered),
        diagnostics=("NO_LETTER_BOUNDARIES_IN_TASK_12A", "OPTIMIZATION_COST_IS_NOT_CONFIDENCE"),
    )


def align_photo_line(
    *,
    photos: PhotoRepository,
    source: PhotoRecord,
    review: TranscriptionReviewRecord,
    cropper: LineMaskCropper,
    max_alternatives: int = 8,
) -> WordAlignment:
    """Use the existing selected-mask and persisted line region exactly once."""

    context = prepare_line_alignment_context(photos=photos, source=source, review=review)
    return align_reviewed_line(
        review=review,
        mask=cropper.crop(context.selected_mask_png, line_region=context.line_region),
        mask_sha256=context.mask_sha256,
        max_alternatives=max_alternatives,
    )


class WordAlignmentRepository:
    """Content-addressed alignment hypotheses outside project files and Git."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _digest(value: str, code: str) -> None:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError(code)

    def path_for(self, digest: str) -> Path:
        self._digest(digest, "INVALID_WORD_ALIGNMENT_HASH")
        return self.root / "word-alignments" / digest[:2] / f"{digest}.hp-word-alignment.json"

    def store(self, alignment: WordAlignment) -> WordAlignmentRecord:
        content = canonical_json_bytes(alignment.model_dump(mode="json"))
        digest = sha256(content).hexdigest()
        target = self.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != content:
                raise ValueError("WORD_ALIGNMENT_HASH_MISMATCH")
        else:
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_bytes(content)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return WordAlignmentRecord(digest, target, alignment)

    def load(self, digest: str) -> WordAlignmentRecord:
        path = self.path_for(digest)
        content = path.read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("WORD_ALIGNMENT_HASH_MISMATCH")
        if not isinstance(strict_json_loads(content), dict):
            raise ValueError("INVALID_WORD_ALIGNMENT")
        return WordAlignmentRecord(digest, path, WordAlignment.model_validate_json(content, strict=True))

    def ensure_current(
        self,
        record: WordAlignmentRecord,
        *,
        reviews: TranscriptionReviewRepository,
        source_manifest_sha256: str,
        line_id: str,
        crop_sha256: str,
    ) -> None:
        alignment = record.alignment
        if (alignment.source_manifest_sha256, alignment.line_id, alignment.crop_sha256) != (
            source_manifest_sha256, line_id, crop_sha256,
        ):
            raise AlignmentStaleError("ALIGNMENT_CROP_OR_MANIFEST_STALE")
        latest = reviews.latest_for_line(source_manifest_sha256, line_id, crop_sha256)
        if latest is None or latest.sha256 != alignment.review_revision_sha256:
            raise AlignmentStaleError("ALIGNMENT_REVIEW_REVISION_STALE")
