"""Bounded hypotheses over TASK 12A ink components; no stroke cuts or HTR."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal
import uuid

import regex
from pydantic import Field, model_validator

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads
from .repository import PhotoRecord, PhotoRepository
from .transcription_review import TranscriptionReviewRecord, TranscriptionReviewRepository
from .word_alignment import (
    AlignmentStaleError, BinaryInkMask, InkComponent, LineMaskCropper, WordAlignment,
    WordAlignmentAlternative, WordAlignmentRecord, WordAlignmentRepository,
    extract_ink_components, verified_line_mask,
)

GRAPHEME_ALGORITHM = "grapheme-component-graph/1"
MAX_GRAPHEMES = 512
MAX_RECORD_BYTES = 8 * 1024 * 1024


class GraphemeSearchLimits(StrictModel):
    max_nodes: int = Field(default=4096, ge=1, le=4096)
    max_transitions: int = Field(default=20000, ge=1, le=50000)
    max_candidates: int = Field(default=2048, ge=1, le=8192)
    max_alternatives: int = Field(default=16, ge=1, le=16)
    paths_per_node: int = Field(default=3, ge=1, le=4)
    max_group_size: int = Field(default=8, ge=1, le=16)


class GraphemeToken(StrictModel):
    grapheme_id: str = Field(pattern=r"^g-[0-9]{1,4}$")
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=16384)
    span_ids: tuple[str, ...] = Field(min_length=1, max_length=4096)
    kind: Literal["word", "whitespace", "punctuation", "mixed"]


class InkBounds(StrictModel):
    left_px: int = Field(ge=0)
    top_px: int = Field(ge=0)
    right_px: int = Field(gt=0)
    bottom_px: int = Field(gt=0)

    @model_validator(mode="after")
    def positive(self) -> InkBounds:
        if self.right_px <= self.left_px or self.bottom_px <= self.top_px:
            raise ValueError("INVALID_GRAPHEME_BOUNDS")
        return self


class UnresolvedJoin(StrictModel):
    left_grapheme_id: str
    right_grapheme_id: str
    state: Literal["unresolved"] = "unresolved"
    reason: Literal["SHARED_INK_NO_OBSERVABLE_CUT"] = "SHARED_INK_NO_OBSERVABLE_CUT"


class GraphemeInkGroup(StrictModel):
    group_id: str = Field(pattern=r"^group-[0-9]{1,4}$")
    grapheme_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_GRAPHEMES)
    component_ids: tuple[str, ...] = Field(default=(), max_length=256)
    state: Literal["ambiguous", "unresolved", "non_ink"]
    relation: Literal["single_grapheme", "join_or_ligature", "shared_words", "unresolved", "whitespace"]
    bounds: InkBounds | None = None
    unresolved_joins: tuple[UnresolvedJoin, ...] = Field(default=(), max_length=MAX_GRAPHEMES)


class GraphemeHypothesis(StrictModel):
    hypothesis_id: str = Field(pattern=r"^hypothesis-[0-9]{1,3}$")
    word_alternative_id: str
    rank: int = Field(ge=1, le=16)
    ranking_cost: float = Field(ge=0.0, allow_inf_nan=False)
    coarse: bool
    groups: tuple[GraphemeInkGroup, ...] = Field(min_length=1, max_length=MAX_GRAPHEMES)
    unassigned_component_ids: tuple[str, ...] = Field(default=(), max_length=256)
    diagnostics: tuple[str, ...] = Field(default=(), max_length=16)


class GraphemeAlignment(StrictModel):
    format: Literal["hp-grapheme-alignment"] = "hp-grapheme-alignment"
    schema_version: Literal["1.0"] = "1.0"
    algorithm_version: Literal["grapheme-component-graph/1"] = GRAPHEME_ALGORITHM
    alignment_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    created_at_utc: str
    word_alignment_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    line_id: str = Field(min_length=1, max_length=128)
    crop_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mask_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    binary_mask_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_revision_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewed_text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    coordinate_system: Literal["line-crop-px-top-left"] = "line-crop-px-top-left"
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    frame_id: str | None = None
    crop_left_px: int | None = Field(default=None, ge=0)
    crop_top_px: int | None = Field(default=None, ge=0)
    tokens: tuple[GraphemeToken, ...] = Field(min_length=1, max_length=MAX_GRAPHEMES)
    components: tuple[InkComponent, ...] = Field(default=(), max_length=256)
    hypotheses: tuple[GraphemeHypothesis, ...] = Field(min_length=1, max_length=16)
    limits: GraphemeSearchLimits
    nodes_visited: int = Field(ge=0)
    transitions_evaluated: int = Field(ge=0)
    candidates_evaluated: int = Field(ge=0)
    budget_exhausted: bool

    @model_validator(mode="after")
    def integrity(self) -> GraphemeAlignment:
        text = "".join(token.text for token in self.tokens)
        if sha256(text.encode("utf-8")).hexdigest() != self.reviewed_text_sha256:
            raise ValueError("GRAPHEME_TEXT_HASH_MISMATCH")
        expected = tuple((match.start(), match.end(), match.group()) for match in regex.finditer(r"\X", text))
        actual = tuple((token.start, token.end, token.text) for token in self.tokens)
        if expected != actual or any(token.grapheme_id != f"g-{index}" for index, token in enumerate(self.tokens)):
            raise ValueError("INVALID_EXTENDED_GRAPHEME_PARTITION")
        if (self.frame_id is None) != (self.crop_left_px is None) or (self.crop_left_px is None) != (self.crop_top_px is None):
            raise ValueError("INCOMPLETE_GRAPHEME_FRAME")
        if (self.nodes_visited > self.limits.max_nodes or self.transitions_evaluated > self.limits.max_transitions
                or self.candidates_evaluated > self.limits.max_candidates or len(self.hypotheses) > self.limits.max_alternatives):
            raise ValueError("GRAPHEME_RESOURCE_LIMIT_EXCEEDED")
        components = {item.component_id: item for item in self.components}
        if len(components) != len(self.components):
            raise ValueError("DUPLICATE_GRAPHEME_COMPONENT")
        if any(item.right_px > self.width_px or item.bottom_px > self.height_px for item in self.components):
            raise ValueError("GRAPHEME_COMPONENT_OUTSIDE_CROP")
        tokens = {token.grapheme_id: token for token in self.tokens}
        if len({item.hypothesis_id for item in self.hypotheses}) != len(self.hypotheses):
            raise ValueError("DUPLICATE_GRAPHEME_HYPOTHESIS")
        for hypothesis in self.hypotheses:
            seen_tokens: list[str] = []
            seen_components: list[str] = []
            previous_right = 0
            previous_token_end = -1
            for index, group in enumerate(hypothesis.groups):
                if group.group_id != f"group-{index}" or not set(group.grapheme_ids) <= tokens.keys():
                    raise ValueError("INVALID_GRAPHEME_GROUP_REFERENCE")
                if tuple(sorted(group.grapheme_ids, key=lambda item: tokens[item].start)) != group.grapheme_ids:
                    raise ValueError("NONMONOTONE_GRAPHEME_GROUP")
                seen_tokens.extend(group.grapheme_ids)
                seen_components.extend(group.component_ids)
                if not set(group.component_ids) <= components.keys():
                    raise ValueError("UNKNOWN_GRAPHEME_COMPONENT")
                members = tuple(components[identity] for identity in group.component_ids)
                if members:
                    if group.state != "ambiguous" or group.bounds != ink_bounds(members):
                        raise ValueError("GRAPHEME_GROUP_BOUNDS_MISMATCH")
                    if group.bounds.left_px < previous_right or tokens[group.grapheme_ids[0]].start < previous_token_end:
                        raise ValueError("NONMONOTONE_GRAPHEME_GEOMETRY")
                    previous_right = group.bounds.right_px
                    previous_token_end = tokens[group.grapheme_ids[-1]].end
                    if group.relation != "shared_words":
                        expected_relation = "single_grapheme" if len(group.grapheme_ids) == 1 else "join_or_ligature"
                        if group.relation != expected_relation:
                            raise ValueError("GRAPHEME_RELATION_MISMATCH")
                elif group.bounds is not None or group.state == "ambiguous":
                    raise ValueError("UNRESOLVED_GRAPHEME_HAS_BOUNDS")
                expected_joins = tuple(UnresolvedJoin(left_grapheme_id=left, right_grapheme_id=right)
                                       for left, right in zip(group.grapheme_ids, group.grapheme_ids[1:])) if members else ()
                if group.unresolved_joins != expected_joins:
                    raise ValueError("INVALID_UNRESOLVED_JOINS")
                if group.state == "non_ink" and any(tokens[identity].kind != "whitespace" for identity in group.grapheme_ids):
                    raise ValueError("ONLY_WHITESPACE_IS_NON_INK")
            if set(seen_tokens) != tokens.keys() or len(seen_tokens) != len(tokens):
                raise ValueError("INCOMPLETE_GRAPHEME_COVERAGE")
            all_ink = (*seen_components, *hypothesis.unassigned_component_ids)
            if set(all_ink) != components.keys() or len(all_ink) != len(components):
                raise ValueError("INCOMPLETE_OR_DUPLICATE_INK_COVERAGE")
        return self

    def validate_parent(self, words: WordAlignmentRecord) -> None:
        parent = words.alignment
        for field in ("source_manifest_sha256", "line_id", "crop_sha256", "mask_sha256", "review_revision_sha256",
                      "reviewed_text_sha256", "frame_id", "crop_left_px", "crop_top_px"):
            if getattr(self, field) != getattr(parent, field):
                raise AlignmentStaleError("GRAPHEME_PARENT_PROVENANCE_STALE")
        if self.word_alignment_sha256 != words.sha256 or self.components != parent.components:
            raise AlignmentStaleError("GRAPHEME_WORD_ALIGNMENT_STALE")
        if (self.width_px, self.height_px) != (parent.mask_width_px, parent.mask_height_px):
            raise AlignmentStaleError("GRAPHEME_COORDINATES_STALE")
        if self.tokens != split_graphemes(parent):
            raise ValueError("GRAPHEME_SPAN_REFERENCES_MISMATCH")
        alternatives = {item.alternative_id: item for item in parent.alternatives}
        if {item.word_alternative_id for item in self.hypotheses} != alternatives.keys():
            raise ValueError("GRAPHEME_WORD_ALTERNATIVE_COVERAGE")
        if {item.word_alternative_id for item in self.hypotheses if item.coarse} != alternatives.keys():
            raise ValueError("GRAPHEME_COARSE_FALLBACK_REQUIRED")
        component_by_id = {item.component_id: item for item in self.components}
        token_by_id = {item.grapheme_id: item for item in self.tokens}
        for hypothesis in self.hypotheses:
            units = word_units(parent, alternatives[hypothesis.word_alternative_id], self.tokens)
            if hypothesis.coarse:
                expected_groups = _complete_groups(
                    [_group(ids, ink, component_by_id, token_by_id) for ids, ink in units], self.tokens,
                )
                if hypothesis.groups != expected_groups:
                    raise ValueError("GRAPHEME_COARSE_GEOMETRY_MISMATCH")
            for group in hypothesis.groups:
                if not group.component_ids:
                    continue
                allowed = next((unit for unit in units if set(group.grapheme_ids) <= set(unit[0])), None)
                if allowed is None or not set(group.component_ids) <= set(allowed[1]):
                    raise ValueError("GRAPHEME_ESCAPES_WORD_CANDIDATE")
                # Component groups with overlapping X envelopes are indivisible
                # here: this includes detached dots above a body stroke.
                for atom in ink_atoms(tuple(component_by_id[identity] for identity in allowed[1])):
                    overlap = set(atom) & set(group.component_ids)
                    if overlap and overlap != set(atom):
                        raise ValueError("GRAPHEME_SPLITS_OVERLAPPING_INK")


@dataclass(frozen=True, slots=True)
class GraphemeAlignmentRecord:
    sha256: str
    path: Path
    alignment: GraphemeAlignment


def split_graphemes(words: WordAlignment) -> tuple[GraphemeToken, ...]:
    text = "".join(span.text for span in words.spans)
    tokens = []
    for index, match in enumerate(regex.finditer(r"\X", text)):
        if index >= MAX_GRAPHEMES:
            raise ValueError("GRAPHEME_TEXT_LIMIT")
        spans = [span for span in words.spans if span.start < match.end() and span.end > match.start()]
        tokens.append(GraphemeToken(
            grapheme_id=f"g-{index}", start=match.start(), end=match.end(), text=match.group(),
            span_ids=tuple(span.span_id for span in spans),
            kind=spans[0].kind if len(spans) == 1 else "mixed",
        ))
    return tuple(tokens)


def ink_bounds(components: tuple[InkComponent, ...]) -> InkBounds:
    return InkBounds(left_px=min(item.left_px for item in components), top_px=min(item.top_px for item in components),
                     right_px=max(item.right_px for item in components), bottom_px=max(item.bottom_px for item in components))


def ink_atoms(components: tuple[InkComponent, ...]) -> tuple[tuple[str, ...], ...]:
    """Projection-connected envelopes: no split through a component or dot/body."""
    groups: list[list[str]] = []
    right = -1
    for item in sorted(components, key=lambda item: (item.left_px, item.top_px, item.component_id)):
        if item.left_px >= right:
            groups.append([])
        groups[-1].append(item.component_id)
        right = max(right, item.right_px)
    return tuple(tuple(group) for group in groups)


def word_units(
    words: WordAlignment, alternative: WordAlignmentAlternative, tokens: tuple[GraphemeToken, ...],
) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    candidates = {item.candidate_id: item for item in words.geometry_candidates}
    units: list[tuple[set[str], set[str]]] = []
    for assignment in alternative.assignments:
        graphemes = {token.grapheme_id for token in tokens if token.kind == "word" and token.span_ids == (assignment.span_id,)}
        components = {identity for candidate in assignment.geometry_candidate_ids for identity in candidates[candidate].component_ids}
        if graphemes and components:
            units.append((graphemes, components))
    # Shared ink in 12A, or overlapping geometry across proposed words, cannot
    # be turned into fictitious per-word or per-letter cuts in 12B.
    by_id = {item.component_id: item for item in words.components}
    merged = True
    while merged:
        merged = False
        for left in range(len(units)):
            for right in range(left + 1, len(units)):
                a, b = ink_bounds(tuple(by_id[item] for item in units[left][1])), ink_bounds(tuple(by_id[item] for item in units[right][1]))
                if units[left][1] & units[right][1] or (a.left_px < b.right_px and b.left_px < a.right_px):
                    units[left][0].update(units[right][0])
                    units[left][1].update(units[right][1])
                    units.pop(right)
                    merged = True
                    break
            if merged:
                break
    order = {token.grapheme_id: index for index, token in enumerate(tokens)}
    return tuple((tuple(sorted(graphemes, key=order.get)), tuple(sorted(components)))
                 for graphemes, components in sorted(units, key=lambda unit: min(order[item] for item in unit[0])))


@dataclass
class _Budget:
    limits: GraphemeSearchLimits
    nodes: int = 0
    transitions: int = 0
    candidates: int = 0
    exhausted: bool = False

    def take(self, kind: str) -> bool:
        maximum = {"nodes": self.limits.max_nodes, "transitions": self.limits.max_transitions,
                   "candidates": self.limits.max_candidates}[kind]
        if getattr(self, kind) >= maximum:
            self.exhausted = True
            return False
        setattr(self, kind, getattr(self, kind) + 1)
        return True


# A path edge consumes whole adjacent graphemes and whole projection atoms.
_Edge = tuple[int, int, int, int]
_Path = tuple[float, tuple[_Edge, ...]]


def _paths(
    grapheme_count: int, atoms: tuple[tuple[str, ...], ...], components: dict[str, InkComponent], budget: _Budget,
) -> tuple[_Path, ...]:
    if budget.exhausted or not budget.take("nodes"):
        return ()
    states: dict[tuple[int, int], list[_Path]] = {(0, 0): [(0.0, ())]}
    bounds = [ink_bounds(tuple(components[identity] for identity in atom)) for atom in atoms]
    width = max(1, bounds[-1].right_px - bounds[0].left_px)
    for diagonal in range(grapheme_count + len(atoms)):
        for (i, j), prefixes in sorted(tuple(states.items())):
            if i + j != diagonal:
                continue
            edges = {(1, count) for count in range(1, min(budget.limits.max_group_size, len(atoms) - j) + 1)}
            edges |= {(count, 1) for count in range(1, min(budget.limits.max_group_size, grapheme_count - i) + 1)}
            for dg, dc in sorted(edges):
                if i + dg > grapheme_count or j + dc > len(atoms):
                    continue
                if not budget.take("candidates"):
                    return ()
                key = (i + dg, j + dc)
                if key not in states:
                    if not budget.take("nodes"):
                        return ()
                    states[key] = []
                edge_cost = (dg / grapheme_count - (bounds[j + dc - 1].right_px - bounds[j].left_px) / width) ** 2
                edge_cost += 0.05 * (dg - 1) + 0.02 * (dc - 1)
                for cost, path in prefixes:
                    if not budget.take("transitions"):
                        return ()
                    states[key].append((cost + edge_cost, (*path, (i, i + dg, j, j + dc))))
                states[key].sort(key=lambda item: (item[0], item[1]))
                del states[key][budget.limits.paths_per_node:]
    return tuple(states.get((grapheme_count, len(atoms)), ()))


def _group(token_ids: tuple[str, ...], component_ids: tuple[str, ...], components: dict[str, InkComponent], tokens: dict[str, GraphemeToken]) -> GraphemeInkGroup:
    shared = len({span for identity in token_ids for span in tokens[identity].span_ids}) > 1
    return GraphemeInkGroup(
        group_id="group-0", grapheme_ids=token_ids, component_ids=tuple(sorted(component_ids)), state="ambiguous",
        relation="shared_words" if shared else ("single_grapheme" if len(token_ids) == 1 else "join_or_ligature"),
        bounds=ink_bounds(tuple(components[identity] for identity in component_ids)),
        unresolved_joins=tuple(UnresolvedJoin(left_grapheme_id=left, right_grapheme_id=right)
                               for left, right in zip(token_ids, token_ids[1:])),
    )


def _complete_groups(
    groups: list[GraphemeInkGroup] | tuple[GraphemeInkGroup, ...], tokens: tuple[GraphemeToken, ...],
) -> tuple[GraphemeInkGroup, ...]:
    used = {identity for group in groups for identity in group.grapheme_ids}
    complete = [*groups, *(GraphemeInkGroup(
        group_id="group-0", grapheme_ids=(token.grapheme_id,),
        state="non_ink" if token.kind == "whitespace" else "unresolved",
        relation="whitespace" if token.kind == "whitespace" else "unresolved",
    ) for token in tokens if token.grapheme_id not in used)]
    positions = {token.grapheme_id: token.start for token in tokens}
    complete.sort(key=lambda group: min(positions[identity] for identity in group.grapheme_ids))
    return tuple(group.model_copy(update={"group_id": f"group-{index}"}) for index, group in enumerate(complete))


def _groups_key(groups: tuple[GraphemeInkGroup, ...]) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    return tuple((group.grapheme_ids, group.component_ids) for group in groups)


def binary_mask_digest(mask: BinaryInkMask) -> str:
    return sha256(mask.width_px.to_bytes(4, "big") + mask.height_px.to_bytes(4, "big") + mask.foreground).hexdigest()


def align_graphemes(
    *, words: WordAlignmentRecord, review: TranscriptionReviewRecord, mask: BinaryInkMask,
    limits: GraphemeSearchLimits | None = None,
) -> GraphemeAlignment:
    """Pure stage over verified inputs; photo-backed callers use the entry below."""
    limits = limits or GraphemeSearchLimits()
    parent = WordAlignment.model_validate(words.alignment.model_dump())
    # A legacy parser knows which optional fields were absent from old JSON.
    word_hashes = {
        sha256(canonical_json_bytes(words.alignment.model_dump(mode="json", exclude_unset=exclude))).hexdigest()
        for exclude in (False, True)
    }
    if words.sha256 not in word_hashes:
        raise AlignmentStaleError("GRAPHEME_WORD_ALIGNMENT_HASH_MISMATCH")
    if sha256(canonical_json_bytes(review.revision.model_dump(mode="json"))).hexdigest() != review.sha256:
        raise AlignmentStaleError("GRAPHEME_REVIEW_HASH_MISMATCH")
    if review.revision.status != "accepted":
        raise ValueError("GRAPHEME_REQUIRES_ACCEPTED_REVIEW")
    if parent.review_revision_sha256 != review.sha256 or "".join(span.text for span in parent.spans) != review.revision.reviewed_text:
        raise AlignmentStaleError("GRAPHEME_REVIEW_STALE")
    if (mask.width_px, mask.height_px) != (parent.mask_width_px, parent.mask_height_px) or extract_ink_components(mask) != parent.components:
        raise AlignmentStaleError("GRAPHEME_BINARY_MASK_STALE")
    if limits.max_alternatives < len(parent.alternatives):
        raise ValueError("GRAPHEME_LIMIT_MUST_COVER_WORD_ALTERNATIVES")
    tokens = split_graphemes(parent)
    token_by_id = {token.grapheme_id: token for token in tokens}
    components = {item.component_id: item for item in parent.components}
    budget = _Budget(limits)
    coarse_hypotheses = []
    refined_hypotheses = []
    for alternative in parent.alternatives:
        units = word_units(parent, alternative, tokens)
        coarse_groups = [_group(ids, ink, components, token_by_id) for ids, ink in units]
        coarse_costs = [0.05 * (len(ids) - 1) + 0.02 * (len(ink_atoms(tuple(components[identity] for identity in ink))) - 1)
                        for ids, ink in units]
        used = {identity for group in coarse_groups for identity in group.component_ids}
        residual = tuple(sorted(set(components) - used))
        coarse = GraphemeHypothesis(
            hypothesis_id="hypothesis-0", word_alternative_id=alternative.alternative_id, rank=1,
            ranking_cost=alternative.optimization_cost + sum(coarse_costs), coarse=True,
            groups=_complete_groups(coarse_groups, tokens), unassigned_component_ids=residual,
            diagnostics=("COARSE_SAFE_HYPOTHESIS", "COST_IS_NOT_CONFIDENCE"),
        )
        coarse_hypotheses.append(coarse)
        paths = [(0.0, ())]
        for (token_ids, component_ids), coarse_group, coarse_cost in zip(units, coarse_groups, coarse_costs, strict=True):
            atoms = ink_atoms(tuple(components[identity] for identity in component_ids))
            candidates = _paths(len(token_ids), atoms, components, budget)
            options = [(coarse_cost, (coarse_group,))]
            for cost, edges in candidates:
                options.append((cost, tuple(_group(
                    token_ids[start:end], tuple(identity for atom in atoms[left:right] for identity in atom), components, token_by_id,
                ) for start, end, left, right in edges)))
            combined = [(cost + extra_cost, (*groups, *extra)) for cost, groups in paths for extra_cost, extra in options]
            combined.sort(key=lambda item: (item[0], _groups_key(item[1])))
            paths = combined[:limits.paths_per_node]
        seen = {coarse.groups}
        for cost, groups in paths:
            complete = _complete_groups(groups, tokens)
            if complete in seen:
                continue
            seen.add(complete)
            refined_hypotheses.append(GraphemeHypothesis(
                hypothesis_id="hypothesis-0", word_alternative_id=alternative.alternative_id, rank=1,
                ranking_cost=alternative.optimization_cost + cost, coarse=False, groups=complete,
                unassigned_component_ids=residual, diagnostics=("GEOMETRY_HYPOTHESIS_ONLY", "COST_IS_NOT_CONFIDENCE"),
            ))
    # Preserve a fallback for *every* source alternative before adding refinements.
    refined_hypotheses.sort(key=lambda item: (item.ranking_cost, item.word_alternative_id, _groups_key(item.groups)))
    chosen = [*coarse_hypotheses, *refined_hypotheses[:limits.max_alternatives - len(coarse_hypotheses)]]
    chosen.sort(key=lambda item: (item.ranking_cost, item.word_alternative_id, not item.coarse, _groups_key(item.groups)))
    hypotheses = tuple(item.model_copy(update={"hypothesis_id": f"hypothesis-{index}", "rank": index + 1}) for index, item in enumerate(chosen))
    result = GraphemeAlignment(
        alignment_id=str(uuid.uuid4()), created_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        word_alignment_sha256=words.sha256, source_manifest_sha256=parent.source_manifest_sha256,
        line_id=parent.line_id, crop_sha256=parent.crop_sha256, mask_sha256=parent.mask_sha256,
        binary_mask_sha256=binary_mask_digest(mask), review_revision_sha256=review.sha256,
        reviewed_text_sha256=parent.reviewed_text_sha256, width_px=mask.width_px, height_px=mask.height_px,
        frame_id=parent.frame_id, crop_left_px=parent.crop_left_px, crop_top_px=parent.crop_top_px,
        tokens=tokens, components=parent.components, hypotheses=hypotheses, limits=limits,
        nodes_visited=budget.nodes, transitions_evaluated=budget.transitions, candidates_evaluated=budget.candidates,
        budget_exhausted=budget.exhausted,
    )
    result.validate_parent(words)
    return result


def align_photo_graphemes(
    *, photos: PhotoRepository, source: PhotoRecord, review: TranscriptionReviewRecord,
    words: WordAlignmentRecord, cropper: LineMaskCropper, limits: GraphemeSearchLimits | None = None,
) -> GraphemeAlignment:
    context, mask = verified_line_mask(photos=photos, source=source, review=review, cropper=cropper)
    stored_words = WordAlignmentRepository(photos.root).load(words.sha256)
    if stored_words != words:
        raise AlignmentStaleError("GRAPHEME_WORD_ALIGNMENT_STALE")
    WordAlignmentRepository(photos.root).ensure_current(
        words, reviews=TranscriptionReviewRepository(photos.root), source_manifest_sha256=source.sha256,
        line_id=review.revision.line_id, crop_sha256=review.revision.crop_sha256, mask_sha256=context.mask_sha256,
    )
    if (words.alignment.frame_id, words.alignment.crop_left_px, words.alignment.crop_top_px) != (
        context.frame_id, context.crop_left_px, context.crop_top_px,
    ):
        raise AlignmentStaleError("GRAPHEME_COORDINATES_STALE")
    return align_graphemes(words=words, review=review, mask=mask, limits=limits)


class GraphemeAlignmentRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, digest: str) -> Path:
        WordAlignmentRepository._digest(digest, "INVALID_GRAPHEME_ALIGNMENT_HASH")
        root = self.root.resolve()
        target = (root / "grapheme-alignments" / digest[:2] / f"{digest}.hp-grapheme-alignment.json").resolve()
        if root not in target.parents:
            raise ValueError("GRAPHEME_PATH_OUTSIDE_DATA_ROOT")
        return target

    def store(self, alignment: GraphemeAlignment) -> GraphemeAlignmentRecord:
        alignment = GraphemeAlignment.model_validate(alignment.model_dump())
        alignment.validate_parent(WordAlignmentRepository(self.root).load(alignment.word_alignment_sha256))
        content = canonical_json_bytes(alignment.model_dump(mode="json"))
        if len(content) > MAX_RECORD_BYTES:
            raise ValueError("GRAPHEME_RECORD_TOO_LARGE")
        digest = sha256(content).hexdigest()
        target = self.path_for(digest)
        PhotoRepository._store_immutable(target, content, "GRAPHEME_ALIGNMENT_HASH_MISMATCH")
        return GraphemeAlignmentRecord(digest, target, alignment)

    def load(self, digest: str) -> GraphemeAlignmentRecord:
        path = self.path_for(digest)
        if path.stat().st_size > MAX_RECORD_BYTES:
            raise ValueError("GRAPHEME_RECORD_TOO_LARGE")
        content = path.read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("GRAPHEME_ALIGNMENT_HASH_MISMATCH")
        if not isinstance(strict_json_loads(content), dict):
            raise ValueError("INVALID_GRAPHEME_RECORD")
        alignment = GraphemeAlignment.model_validate_json(content, strict=True)
        alignment.validate_parent(WordAlignmentRepository(self.root).load(alignment.word_alignment_sha256))
        return GraphemeAlignmentRecord(digest, path, alignment)

    def load_current(
        self, digest: str, *, photos: PhotoRepository, source: PhotoRecord,
        review: TranscriptionReviewRecord, words: WordAlignmentRecord, cropper: LineMaskCropper,
    ) -> GraphemeAlignmentRecord:
        record = self.load(digest)
        if WordAlignmentRepository(photos.root).load(words.sha256) != words:
            raise AlignmentStaleError("GRAPHEME_WORD_ALIGNMENT_STALE")
        record.alignment.validate_parent(words)
        context, mask = verified_line_mask(photos=photos, source=source, review=review, cropper=cropper)
        WordAlignmentRepository(photos.root).ensure_current(
            words, reviews=TranscriptionReviewRepository(photos.root), source_manifest_sha256=source.sha256,
            line_id=review.revision.line_id, crop_sha256=review.revision.crop_sha256, mask_sha256=context.mask_sha256,
        )
        if record.alignment.binary_mask_sha256 != binary_mask_digest(mask):
            raise AlignmentStaleError("GRAPHEME_BINARY_MASK_STALE")
        if (record.alignment.frame_id, record.alignment.crop_left_px, record.alignment.crop_top_px) != (
            context.frame_id, context.crop_left_px, context.crop_top_px,
        ):
            raise AlignmentStaleError("GRAPHEME_COORDINATES_STALE")
        if review.revision.status != "accepted":
            raise AlignmentStaleError("GRAPHEME_REVIEW_STALE")
        return record
