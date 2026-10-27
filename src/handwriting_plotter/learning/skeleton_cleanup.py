"""Non-destructive, explicit terminal-branch filtering of TASK 13A graphs.

Short terminal branches are ambiguous candidates, never classified as noise.
All decisions refer to the immutable raw graph; there is no cascading pruning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable, Literal

from pydantic import Field

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes
from .repository import PhotoRecord, PhotoRepository
from .transcription_review import TranscriptionReviewRecord
from .skeleton import (
    MAX_FOREGROUND, MAX_RECORD_BYTES, Pixel, SkeletonComponent, SkeletonEdge,
    SkeletonGraphRecord, SkeletonLimitError, SkeletonLimits, SkeletonNode,
    SkeletonProvenance, SkeletonRepository, TopologyCounts, _Budget,
    _check_component_identity, _connected, _graph_parts, _neighbors8, _order, _topology,
)
from .word_alignment import AlignmentStaleError, BinaryInkMask, LineMaskCropper


class SkeletonCleanupPolicy(StrictModel):
    max_spur_length_px: float = Field(default=3.0, ge=0, le=32, allow_inf_nan=False)
    selection: Literal["explicit-raw-edge-ids"] = "explicit-raw-edge-ids"
    cascading: Literal[False] = False


class SkeletonCleanupLimits(StrictModel):
    max_candidates: int = Field(default=8192, ge=1, le=8192)
    max_removals: int = Field(default=256, ge=0, le=256)
    max_work_units: int = Field(default=20_000_000, ge=1, le=50_000_000)
    max_working_bytes: int = Field(default=256 * 1024 * 1024, ge=1024, le=256 * 1024 * 1024)


class SpurCandidate(StrictModel):
    edge_id: str = Field(pattern=r"^e-[0-9]+$")
    endpoint_node_id: str = Field(pattern=r"^n-[0-9]+$")
    junction_node_id: str = Field(pattern=r"^n-[0-9]+$")
    pixel_length: float = Field(gt=0, allow_inf_nan=False)
    removable_pixels: tuple[Pixel, ...] = Field(min_length=1, max_length=MAX_FOREGROUND)
    ambiguous: Literal[True] = True
    evidence: Literal["short-endpoint-to-junction; semantic-role-unknown"] = "short-endpoint-to-junction; semantic-role-unknown"


class SkeletonCleanup(StrictModel):
    format: Literal["hp-skeleton-cleanup"] = "hp-skeleton-cleanup"
    schema_version: Literal["1.0"] = "1.0"
    algorithm: Literal["explicit-terminal-filter/1"] = "explicit-terminal-filter/1"
    raw_graph_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at_utc: str = Field(min_length=1, max_length=64)
    provenance: SkeletonProvenance
    coordinate_system: Literal["line-crop-px-top-left"] = "line-crop-px-top-left"
    width_px: int = Field(gt=0, le=4_000_000)
    height_px: int = Field(gt=0, le=4_000_000)
    policy: SkeletonCleanupPolicy
    limits: SkeletonCleanupLimits
    candidates: tuple[SpurCandidate, ...] = Field(default=(), max_length=8192)
    removed_edge_ids: tuple[str, ...] = Field(default=(), max_length=256)
    removed_pixels: tuple[Pixel, ...] = Field(default=(), max_length=MAX_FOREGROUND)
    retained_pixels: tuple[Pixel, ...] = Field(default=(), max_length=MAX_FOREGROUND)
    nodes: tuple[SkeletonNode, ...] = Field(default=(), max_length=8192)
    edges: tuple[SkeletonEdge, ...] = Field(default=(), max_length=16384)
    components: tuple[SkeletonComponent, ...] = Field(default=(), max_length=256)
    topology: TopologyCounts
    work_units: int = Field(ge=0)
    working_memory_estimate_bytes: int = Field(ge=0)
    diagnostics: tuple[str, ...] = Field(max_length=16)

    def validate_raw(self, raw: SkeletonGraphRecord) -> None:
        if self.raw_graph_sha256 != raw.sha256:
            raise AlignmentStaleError("CLEANUP_RAW_REFERENCE_STALE")
        expected = cleanup_skeleton(raw, remove_edge_ids=self.removed_edge_ids, policy=self.policy, limits=self.limits)
        if self.model_dump(exclude={"created_at_utc"}) != expected.model_dump(exclude={"created_at_utc"}):
            raise ValueError("CLEANUP_CONTENT_MISMATCH")

    def skeleton_mask(self) -> BinaryInkMask:
        # Also bound standalone model use; persisted records are validated
        # against their raw graph before being returned by the repository.
        if self.width_px * self.height_px > 4_000_000:
            raise SkeletonLimitError("CLEANUP_PIXEL_LIMIT")
        data = bytearray(self.width_px * self.height_px)
        for x, y in self.retained_pixels:
            if x >= self.width_px or y >= self.height_px:
                raise ValueError("CLEANUP_PIXEL_OUTSIDE_CROP")
            data[y * self.width_px + x] = 1
        return BinaryInkMask(self.width_px, self.height_px, bytes(data))


def _verify_raw(raw: SkeletonGraphRecord) -> None:
    # Reuse strict raw graph geometry/provenance validation, even if a caller
    # constructs a record without going through SkeletonRepository.
    from .skeleton import SkeletonGraph

    if not isinstance(raw, SkeletonGraphRecord):
        raise TypeError("CLEANUP_REQUIRES_RAW_GRAPH_RECORD")
    content = canonical_json_bytes(raw.graph.model_dump(mode="json"))
    if len(content) > MAX_RECORD_BYTES or sha256(content).hexdigest() != raw.sha256:
        raise ValueError("CLEANUP_RAW_RECORD_HASH_MISMATCH")
    SkeletonGraph.model_validate(raw.graph.model_dump())


def cleanup_skeleton(
    raw: SkeletonGraphRecord, *, remove_edge_ids: tuple[str, ...] = (),
    policy: SkeletonCleanupPolicy | None = None, limits: SkeletonCleanupLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> SkeletonCleanup:
    """Return a canonical derived view; only explicitly selected raw spurs go.

    Default is a lossless proposal. Explicit selection acknowledges semantic
    ambiguity, but cannot remove isolated marks, loops, junction pixels or
    enough branches to leave an original junction with fewer than two links.
    """
    policy = SkeletonCleanupPolicy.model_validate((policy or SkeletonCleanupPolicy()).model_dump())
    limits = SkeletonCleanupLimits.model_validate((limits or SkeletonCleanupLimits()).model_dump())
    if not isinstance(raw, SkeletonGraphRecord):
        raise TypeError("CLEANUP_REQUIRES_RAW_GRAPH_RECORD")
    graph = raw.graph
    estimate = graph.width_px * graph.height_px * 8 + len(graph.raw_pixels) * 4096 + 8192
    if estimate > limits.max_working_bytes:
        raise SkeletonLimitError("CLEANUP_MEMORY_LIMIT")
    # Charge raw validation's bounded traversal before starting it. The raw
    # validator has its own hard limits; parsing is separately byte bounded.
    geometry_limits = SkeletonLimits.model_validate({**graph.limits.model_dump(), "max_work_units": limits.max_work_units})
    budget = _Budget(geometry_limits, cancelled=cancelled)
    budget.take(64 * len(graph.raw_pixels) + len(graph.nodes) + len(graph.edges) + 1)
    _verify_raw(raw)
    if len(remove_edge_ids) > limits.max_removals:
        raise SkeletonLimitError("CLEANUP_REMOVAL_LIMIT")
    if len(set(remove_edge_ids)) != len(remove_edge_ids):
        raise ValueError("INVALID_SPUR_SELECTION")
    nodes = {node.node_id: node for node in graph.nodes}
    junction_regions = {node.node_id: set(node.pixels) for node in graph.nodes if node.kind == "junction"}
    candidates = []
    for edge in graph.edges:
        budget.take(len(edge.pixels) + 1)
        a, b = nodes[edge.node_a], nodes[edge.node_b]
        if a.kind == "junction" and b.kind == "endpoint":
            a, b = b, a
        if a.kind != "endpoint" or b.kind != "junction" or edge.closed or edge.pixel_length > policy.max_spur_length_px:
            continue
        junction_pixels = junction_regions[b.node_id]
        removable = tuple(sorted(set(edge.pixels) - junction_pixels, key=_order))
        if not removable:
            continue
        if len(candidates) >= limits.max_candidates:
            raise SkeletonLimitError("CLEANUP_CANDIDATE_LIMIT")
        candidates.append(SpurCandidate(edge_id=edge.edge_id, endpoint_node_id=a.node_id,
                                        junction_node_id=b.node_id, pixel_length=edge.pixel_length,
                                        removable_pixels=removable))
    by_id = {item.edge_id: item for item in candidates}
    if any(identity not in by_id for identity in remove_edge_ids):
        raise ValueError("INVALID_SPUR_SELECTION")
    selection_set = set(remove_edge_ids)
    selected = tuple(item.edge_id for item in candidates if item.edge_id in selection_set)
    incidence = {node.node_id: 0 for node in graph.nodes}
    for edge in graph.edges:
        if edge.edge_id not in selection_set:
            incidence[edge.node_a] += 1
            incidence[edge.node_b] += 1
    if any(incidence[by_id[identity].junction_node_id] < 2 for identity in selected):
        raise ValueError("CLEANUP_JUNCTION_SUPPORT_REQUIRED")
    removed = {pixel for identity in selected for pixel in by_id[identity].removable_pixels}
    protected = {pixel for node in graph.nodes if node.kind == "junction" for pixel in node.pixels}
    if removed & protected:
        raise ValueError("CLEANUP_JUNCTION_PIXEL_REMOVAL")
    original = set(graph.raw_pixels)
    retained = original - removed
    groups_before = _connected(original, _neighbors8, budget)
    groups_after = _connected(retained, _neighbors8, budget)
    _check_component_identity(groups_before, groups_after)
    topology = _topology(retained, budget, groups_after)
    if topology != graph.skeleton_topology:
        raise ValueError("CLEANUP_TOPOLOGY_CHANGED")
    owner = {pixel: index for index, group in enumerate(groups_before) for pixel in group}
    sources = tuple(graph.components[owner[next(iter(group))]].input_ink_component for group in groups_after)
    parts = _graph_parts(retained, groups_after, sources, geometry_limits, budget)
    old_cycles = {c.input_ink_component.component_id: c.cycle_rank for c in graph.components}
    if any(old_cycles[c.input_ink_component.component_id] != c.cycle_rank for c in parts[2]):
        raise ValueError("CLEANUP_COMPONENT_CYCLE_CHANGED")
    return SkeletonCleanup(
        raw_graph_sha256=raw.sha256, created_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        provenance=graph.provenance, width_px=graph.width_px, height_px=graph.height_px,
        policy=policy, limits=limits, candidates=tuple(candidates), removed_edge_ids=selected,
        removed_pixels=tuple(sorted(removed, key=_order)), retained_pixels=tuple(sorted(retained, key=_order)),
        nodes=parts[0], edges=parts[1], components=parts[2], topology=topology,
        work_units=budget.work, working_memory_estimate_bytes=estimate,
        diagnostics=("DIAGNOSTIC_UNDIRECTED_NO_PEN_ORDER", "SHORT_BRANCH_SEMANTICS_UNKNOWN",
                     "RAW_GRAPH_RETAINED", "NO_CASCADING_NO_SMOOTHING")
        + (("EXPLICIT_BRANCH_REMOVALS",) if selected else ("LOSSLESS_PROPOSAL",)),
    )


@dataclass(frozen=True, slots=True)
class SkeletonCleanupRecord:
    sha256: str
    path: Path
    cleanup: SkeletonCleanup


class SkeletonCleanupRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.raw = SkeletonRepository(root)

    def path_for(self, digest: str) -> Path:
        if len(digest) != 64 or any(value not in "0123456789abcdef" for value in digest):
            raise ValueError("INVALID_CLEANUP_RECORD_HASH")
        root = self.root.resolve()
        path = (root / "skeleton-cleanups" / digest[:2] / f"{digest}.hp-skeleton-cleanup.json").resolve()
        if root not in path.parents:
            raise ValueError("CLEANUP_PATH_OUTSIDE_DATA_ROOT")
        return path

    def store(self, cleanup: SkeletonCleanup) -> SkeletonCleanupRecord:
        cleanup = SkeletonCleanup.model_validate(cleanup.model_dump())
        cleanup.validate_raw(self.raw.load(cleanup.raw_graph_sha256))
        content = canonical_json_bytes(cleanup.model_dump(mode="json"))
        if len(content) > MAX_RECORD_BYTES:
            raise SkeletonLimitError("CLEANUP_RECORD_TOO_LARGE")
        digest = sha256(content).hexdigest()
        path = self.path_for(digest)
        PhotoRepository._store_immutable(path, content, "CLEANUP_RECORD_HASH_MISMATCH")
        return SkeletonCleanupRecord(digest, path, cleanup)

    def _load(self, digest: str) -> SkeletonCleanupRecord:
        path = self.path_for(digest)
        if path.stat().st_size > MAX_RECORD_BYTES:
            raise SkeletonLimitError("CLEANUP_RECORD_TOO_LARGE")
        with path.open("rb") as stream:
            content = stream.read(MAX_RECORD_BYTES + 1)
        if len(content) > MAX_RECORD_BYTES:
            raise SkeletonLimitError("CLEANUP_RECORD_TOO_LARGE")
        if sha256(content).hexdigest() != digest:
            raise ValueError("CLEANUP_RECORD_HASH_MISMATCH")
        # Strict JSON rejects duplicate keys/nonfinite numbers before schema.
        from handwriting_plotter.domain.models import strict_json_loads
        strict_json_loads(content)
        return SkeletonCleanupRecord(digest, path, SkeletonCleanup.model_validate_json(content, strict=True))

    def load(self, digest: str) -> SkeletonCleanupRecord:
        record = self._load(digest)
        record.cleanup.validate_raw(self.raw.load(record.cleanup.raw_graph_sha256))
        return record

    def load_current(
        self, digest: str, *, photos: PhotoRepository, source: PhotoRecord,
        review: TranscriptionReviewRecord, cropper: LineMaskCropper,
    ) -> SkeletonCleanupRecord:
        """Use the identical active source/review/crop/mask checks as TASK 13A."""
        record = self._load(digest)
        raw = self.raw.load_current(record.cleanup.raw_graph_sha256, photos=photos, source=source,
                                    review=review, cropper=cropper)
        record.cleanup.validate_raw(raw)
        return record
