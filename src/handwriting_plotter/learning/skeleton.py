"""Raw topology-preserving thinning and undirected pixel graphs (TASK 13A)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import math
from pathlib import Path
from typing import Annotated, Callable, Literal
import uuid

from pydantic import Field, model_validator

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads
from .grapheme_alignment import binary_mask_digest
from .repository import PhotoRecord, PhotoRepository
from .transcription_review import TranscriptionReviewRecord
from .word_alignment import AlignmentStaleError, BinaryInkMask, InkComponent, LineMaskCropper, verified_line_mask

Pixel = tuple[Annotated[int, Field(ge=0)], Annotated[int, Field(ge=0)]]
_RING = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))
_ORTHOGONAL = ((0, -1), (1, 0), (0, 1), (-1, 0))
MAX_FOREGROUND = 50_000
MAX_RECORD_BYTES = 16 * 1024 * 1024


class SkeletonLimitError(ValueError):
    """A complete result cannot be produced within the admitted resource bounds."""


class SkeletonLimits(StrictModel):
    max_pixels: int = Field(default=1_000_000, ge=1, le=4_000_000)
    max_foreground: int = Field(default=MAX_FOREGROUND, ge=1, le=MAX_FOREGROUND)
    max_components: int = Field(default=256, ge=1, le=256)
    max_nodes: int = Field(default=8192, ge=1, le=8192)
    max_edges: int = Field(default=16384, ge=1, le=16384)
    max_graph_points: int = Field(default=100_000, ge=1, le=200_000)
    max_iterations: int = Field(default=256, ge=1, le=1024)
    max_work_units: int = Field(default=20_000_000, ge=1, le=50_000_000)
    max_working_bytes: int = Field(default=256 * 1024 * 1024, ge=1024, le=256 * 1024 * 1024)


class TopologyCounts(StrictModel):
    foreground_components: int = Field(ge=0, le=256)
    background_holes: int = Field(ge=0)


class SkeletonProvenance(StrictModel):
    input_mask_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    line_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    crop_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    encoded_mask_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    review_revision_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    frame_id: str | None = Field(default=None, min_length=1, max_length=128)
    crop_left_px: int | None = Field(default=None, ge=0)
    crop_top_px: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def complete_photo_reference(self) -> SkeletonProvenance:
        references = (self.source_manifest_sha256, self.line_id, self.crop_sha256, self.encoded_mask_sha256,
                      self.review_revision_sha256, self.frame_id, self.crop_left_px, self.crop_top_px)
        if any(value is not None for value in references) and any(value is None for value in references):
            raise ValueError("INCOMPLETE_SKELETON_PROVENANCE")
        return self


class SkeletonNode(StrictModel):
    node_id: str = Field(pattern=r"^n-[0-9]+$")
    component_id: str = Field(pattern=r"^c-[0-9]+$")
    kind: Literal["endpoint", "junction", "isolated", "cycle_anchor"]
    anchor: Pixel
    pixels: tuple[Pixel, ...] = Field(min_length=1, max_length=MAX_FOREGROUND)
    internal_holes: int = Field(default=0, ge=0)


class SkeletonEdge(StrictModel):
    edge_id: str = Field(pattern=r"^e-[0-9]+$")
    component_id: str = Field(pattern=r"^c-[0-9]+$")
    node_a: str = Field(pattern=r"^n-[0-9]+$")
    node_b: str = Field(pattern=r"^n-[0-9]+$")
    pixels: tuple[Pixel, ...] = Field(min_length=2, max_length=MAX_FOREGROUND + 1)
    closed: bool
    pixel_length: float = Field(gt=0.0, allow_inf_nan=False)


class SkeletonComponent(StrictModel):
    component_id: str = Field(pattern=r"^c-[0-9]+$")
    input_ink_component: InkComponent
    skeleton_pixel_count: int = Field(gt=0, le=MAX_FOREGROUND)
    node_ids: tuple[str, ...] = Field(min_length=1, max_length=8192)
    edge_ids: tuple[str, ...] = Field(default=(), max_length=16384)
    cycle_rank: int = Field(ge=0)


class SkeletonGraph(StrictModel):
    format: Literal["hp-skeleton-graph"] = "hp-skeleton-graph"
    schema_version: Literal["1.0"] = "1.0"
    thinning_algorithm: Literal["guarded-zhang-suen/1"] = "guarded-zhang-suen/1"
    graph_algorithm: Literal["pixel-chains-junctions/1"] = "pixel-chains-junctions/1"
    foreground_connectivity: Literal[8] = 8
    background_connectivity: Literal[4] = 4
    adjacency_policy: Literal["8-no-corner-shortcuts/1"] = "8-no-corner-shortcuts/1"
    coordinate_system: Literal["line-crop-px-top-left"] = "line-crop-px-top-left"
    graph_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    created_at_utc: str
    provenance: SkeletonProvenance
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    skeleton_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_pixels: tuple[Pixel, ...] = Field(default=(), max_length=MAX_FOREGROUND)
    input_topology: TopologyCounts
    skeleton_topology: TopologyCounts
    nodes: tuple[SkeletonNode, ...] = Field(default=(), max_length=8192)
    edges: tuple[SkeletonEdge, ...] = Field(default=(), max_length=16384)
    components: tuple[SkeletonComponent, ...] = Field(default=(), max_length=256)
    limits: SkeletonLimits
    thinning_iterations: int = Field(ge=0)
    work_units: int = Field(ge=0)
    removed_pixels: int = Field(ge=0)
    working_memory_estimate_bytes: int = Field(ge=0)
    diagnostics: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def graph_integrity(self) -> SkeletonGraph:
        if self.width_px * self.height_px > self.limits.max_pixels or len(self.raw_pixels) > self.limits.max_foreground:
            raise SkeletonLimitError("SKELETON_PIXEL_LIMIT")
        if (len(self.nodes) > self.limits.max_nodes or len(self.edges) > self.limits.max_edges
                or len(self.components) > self.limits.max_components):
            raise SkeletonLimitError("SKELETON_GRAPH_LIMIT")
        if self.work_units > self.limits.max_work_units or self.thinning_iterations > self.limits.max_iterations:
            raise SkeletonLimitError("SKELETON_WORK_LIMIT")
        if self.working_memory_estimate_bytes > self.limits.max_working_bytes:
            raise SkeletonLimitError("SKELETON_MEMORY_LIMIT")
        if len(self.raw_pixels) + self.removed_pixels > self.limits.max_foreground:
            raise SkeletonLimitError("SKELETON_FOREGROUND_LIMIT")
        estimate = _memory_estimate(self.width_px * self.height_px, len(self.raw_pixels) + self.removed_pixels)
        if self.working_memory_estimate_bytes != estimate or estimate > self.limits.max_working_bytes:
            raise SkeletonLimitError("SKELETON_MEMORY_LIMIT")
        if sum(len(node.pixels) for node in self.nodes) + sum(len(edge.pixels) for edge in self.edges) > self.limits.max_graph_points:
            raise SkeletonLimitError("SKELETON_EDGE_OR_POINT_LIMIT")
        if len(set(self.raw_pixels)) != len(self.raw_pixels) or tuple(sorted(self.raw_pixels, key=_order)) != self.raw_pixels:
            raise ValueError("SKELETON_PIXELS_NOT_CANONICAL")
        if any(x >= self.width_px or y >= self.height_px for x, y in self.raw_pixels):
            raise ValueError("SKELETON_PIXEL_OUTSIDE_CROP")
        if self.input_topology != self.skeleton_topology:
            raise ValueError("SKELETON_TOPOLOGY_MISMATCH")
        if binary_mask_digest(self.skeleton_mask()) != self.skeleton_sha256:
            raise ValueError("SKELETON_RASTER_HASH_MISMATCH")
        budget = _Budget(self.limits)
        raw = set(self.raw_pixels)
        groups = _connected(raw, _neighbors8, budget)
        if _topology(raw, budget, groups) != self.skeleton_topology:
            raise ValueError("SKELETON_TOPOLOGY_MISMATCH")
        if len(groups) != len(self.components):
            raise ValueError("SKELETON_COMPONENT_COUNT_MISMATCH")
        sources = tuple(component.input_ink_component for component in self.components)
        if len({item.component_id for item in sources}) != len(sources):
            raise ValueError("SKELETON_SOURCE_COMPONENT_MISMATCH")
        for group, source in zip(groups, sources, strict=True):
            if source.pixel_count < len(group) or any(
                not (source.left_px <= x < source.right_px and source.top_px <= y < source.bottom_px) for x, y in group
            ):
                raise ValueError("SKELETON_SOURCE_COMPONENT_MISMATCH")
        expected = _graph_parts(raw, groups, sources, self.limits, budget)
        if (self.nodes, self.edges, self.components) != expected:
            raise ValueError("SKELETON_GRAPH_GEOMETRY_MISMATCH")
        if sum(item.pixel_count for item in sources) != len(raw) + self.removed_pixels:
            raise ValueError("SKELETON_INPUT_PIXEL_COUNT_MISMATCH")
        return self

    def skeleton_mask(self) -> BinaryInkMask:
        data = bytearray(self.width_px * self.height_px)
        for x, y in self.raw_pixels:
            data[y * self.width_px + x] = 1
        return BinaryInkMask(self.width_px, self.height_px, bytes(data))

    def validate_input(self, mask: BinaryInkMask) -> None:
        if self.provenance.input_mask_sha256 != binary_mask_digest(mask):
            raise AlignmentStaleError("SKELETON_INPUT_MASK_STALE")
        if (self.width_px, self.height_px) != (mask.width_px, mask.height_px):
            raise AlignmentStaleError("SKELETON_COORDINATES_STALE")
        raw = set(self.raw_pixels)
        if any(not mask.foreground[y * mask.width_px + x] for x, y in raw):
            raise ValueError("SKELETON_CREATED_FOREGROUND")
        budget = _Budget(self.limits)
        points = _mask_points(mask, self.limits)
        original = _connected(points, _neighbors8, budget)
        if _topology(points, budget, original) != self.input_topology:
            raise ValueError("SKELETON_INPUT_TOPOLOGY_MISMATCH")
        _check_component_identity(original, _connected(raw, _neighbors8, budget))
        source_of = {pixel: index for index, group in enumerate(original) for pixel in group}
        ordered_sources = tuple(
            _ink_component(source_of[node.anchor], original[source_of[node.anchor]])
            for node in (next(node for node in self.nodes if node.component_id == component.component_id)
                         for component in self.components)
        )
        if ordered_sources != tuple(item.input_ink_component for item in self.components):
            raise ValueError("SKELETON_SOURCE_COMPONENT_MISMATCH")


@dataclass
class _Budget:
    limits: SkeletonLimits
    work: int = 0
    cancelled: Callable[[], bool] | None = None

    def take(self, amount: int = 1) -> None:
        if self.work + amount > self.limits.max_work_units:
            raise SkeletonLimitError("SKELETON_WORK_LIMIT")
        self.work += amount
        if self.cancelled is not None and self.cancelled():
            raise SkeletonLimitError("SKELETON_CANCELLED")


def _order(pixel: Pixel) -> tuple[int, int]:
    return pixel[1], pixel[0]


def _neighbors8(pixel: Pixel, points: set[Pixel]) -> tuple[Pixel, ...]:
    x, y = pixel
    return tuple((x + dx, y + dy) for dx, dy in _RING if (x + dx, y + dy) in points)


def _graph_neighbors(pixel: Pixel, points: set[Pixel]) -> tuple[Pixel, ...]:
    x, y = pixel
    return tuple(sorted((neighbor for neighbor in _neighbors8(pixel, points)
                         if neighbor[0] == x or neighbor[1] == y
                         or ((neighbor[0], y) not in points and (x, neighbor[1]) not in points)), key=_order))


def _connected(points: set[Pixel], neighbors: Callable, budget: _Budget) -> tuple[set[Pixel], ...]:
    seen: set[Pixel] = set()
    groups: list[set[Pixel]] = []
    for start in sorted(points, key=_order):
        if start in seen:
            continue
        group = {start}
        seen.add(start)
        stack = [start]
        while stack:
            pixel = stack.pop()
            budget.take(8)
            for neighbor in neighbors(pixel, points):
                if neighbor not in seen:
                    seen.add(neighbor)
                    group.add(neighbor)
                    stack.append(neighbor)
        groups.append(group)
    return tuple(groups)


def _topology(points: set[Pixel], budget: _Budget, groups: tuple[set[Pixel], ...] | None = None) -> TopologyCounts:
    groups = groups if groups is not None else _connected(points, _neighbors8, budget)
    # Digital Euler number for (foreground 8, background 4), on the infinite
    # zero-padded lattice: chi = (Q1 - Q3 - 2*Qdiagonal) / 4.
    blocks = {(x + dx, y + dy) for x, y in points for dx, dy in ((0, 0), (-1, 0), (0, -1), (-1, -1))}
    budget.take(4 * len(points))
    numerator = 0
    for x, y in blocks:
        a, b, c, d = ((x, y) in points, (x + 1, y) in points, (x, y + 1) in points, (x + 1, y + 1) in points)
        count = a + b + c + d
        numerator += int(count == 1) - int(count == 3) - 2 * int(count == 2 and ((a and d) or (b and c)))
    if numerator % 4:
        raise ValueError("INVALID_DIGITAL_EULER_NUMBER")
    return TopologyCounts(foreground_components=len(groups), background_holes=len(groups) - numerator // 4)


def topology_counts(mask: BinaryInkMask) -> TopologyCounts:
    limits = SkeletonLimits()
    return _topology(_mask_points(mask, limits), _Budget(limits))


def _mask_points(mask: BinaryInkMask, limits: SkeletonLimits) -> set[Pixel]:
    # Revalidate because Python dataclass annotations alone do not reject a
    # mutable bytearray, bool dimensions, or malformed constructed instances.
    if (not isinstance(mask, BinaryInkMask) or type(mask.width_px) is not int or type(mask.height_px) is not int
            or type(mask.foreground) is not bytes or mask.width_px <= 0 or mask.height_px <= 0):
        raise ValueError("INVALID_SKELETON_BINARY_MASK")
    if mask.width_px * mask.height_px > limits.max_pixels:
        raise SkeletonLimitError("SKELETON_PIXEL_LIMIT")
    if len(mask.foreground) != mask.width_px * mask.height_px or any(value not in (0, 1) for value in mask.foreground):
        raise ValueError("INVALID_SKELETON_BINARY_MASK")
    count = sum(mask.foreground)
    if count > limits.max_foreground:
        raise SkeletonLimitError("SKELETON_FOREGROUND_LIMIT")
    estimate = _memory_estimate(len(mask.foreground), count)
    if estimate > limits.max_working_bytes:
        raise SkeletonLimitError("SKELETON_MEMORY_LIMIT")
    return {(index % mask.width_px, index // mask.width_px) for index, value in enumerate(mask.foreground) if value}


def _memory_estimate(pixels: int, foreground: int) -> int:
    # Conservative admission estimate for bounded sets, topology blocks,
    # adjacency/link maps, typed records and their validation copies. This is
    # a workspace estimate, not an RSS or virtual-memory measurement.
    return pixels * 8 + foreground * 4096 + 4096


def _zhang_candidate(pixel: Pixel, points: set[Pixel], phase: int) -> bool:
    x, y = pixel
    ring = tuple(int((x + dx, y + dy) in points) for dx, dy in _RING)
    neighbors = sum(ring)
    transitions = sum(a == 0 and b == 1 for a, b in zip(ring, (*ring[1:], ring[0]), strict=True))
    if not 2 <= neighbors <= 6 or transitions != 1:
        return False
    if phase == 0:
        return not (ring[0] * ring[2] * ring[4] or ring[2] * ring[4] * ring[6])
    return not (ring[0] * ring[2] * ring[6] or ring[0] * ring[4] * ring[6])


def _simple_point(pixel: Pixel, points: set[Pixel], budget: _Budget) -> bool:
    x, y = pixel
    foreground = set(_neighbors8(pixel, points))
    if len(foreground) <= 1 or len(_connected(foreground, _neighbors8, budget)) != 1:
        return False
    ring = {(x + dx, y + dy) for dx, dy in _RING}
    background = ring - foreground
    adjacent = {(x + dx, y + dy) for dx, dy in _ORTHOGONAL}

    def neighbors4(point, region):
        px, py = point
        return tuple((px + dx, py + dy) for dx, dy in _ORTHOGONAL if (px + dx, py + dy) in region)

    return sum(bool(group & adjacent) for group in _connected(background, neighbors4, budget)) == 1


def _thin(points: set[Pixel], budget: _Budget) -> tuple[set[Pixel], int]:
    current = set(points)
    if not current:
        return current, 0
    for iteration in range(1, budget.limits.max_iterations + 1):
        removed = 0
        for phase in (0, 1):
            budget.take(8 * len(current))
            candidates = [pixel for pixel in sorted(current, key=_order) if _zhang_candidate(pixel, current, phase)]
            for pixel in candidates:
                budget.take(8)
                if _simple_point(pixel, current, budget):
                    current.remove(pixel)
                    removed += 1
        if not removed:
            return current, iteration
    raise SkeletonLimitError("SKELETON_ITERATION_LIMIT")


def _ink_component(index: int, pixels: set[Pixel]) -> InkComponent:
    return InkComponent(component_id=f"component-{index}", left_px=min(x for x, _ in pixels),
                        top_px=min(y for _, y in pixels), right_px=max(x for x, _ in pixels) + 1,
                        bottom_px=max(y for _, y in pixels) + 1, pixel_count=len(pixels))


def _check_component_identity(original: tuple[set[Pixel], ...], skeleton: tuple[set[Pixel], ...]) -> None:
    ownership = {pixel: index for index, group in enumerate(original) for pixel in group}
    identities = []
    for group in skeleton:
        owners = {ownership.get(pixel) for pixel in group}
        if len(owners) != 1 or None in owners:
            raise ValueError("SKELETON_COMPONENT_MERGE_OR_NEW_PIXEL")
        identities.append(next(iter(owners)))
    if sorted(identities) != list(range(len(original))):
        raise ValueError("SKELETON_COMPONENT_LOSS_OR_SPLIT")


def _graph_parts(
    pixels: set[Pixel], groups: tuple[set[Pixel], ...], sources: tuple[InkComponent, ...],
    limits: SkeletonLimits, budget: _Budget,
) -> tuple[tuple[SkeletonNode, ...], tuple[SkeletonEdge, ...], tuple[SkeletonComponent, ...]]:
    adjacency = {pixel: _graph_neighbors(pixel, pixels) for pixel in sorted(pixels, key=_order)}
    budget.take(8 * len(pixels))
    component_of = {pixel: index for index, group in enumerate(groups) for pixel in group}
    junctions = {pixel for pixel, neighbors in adjacency.items() if len(neighbors) >= 3}
    # A filled 2x2 cell has no background hole, but its four perimeter links
    # would form a false graph cycle. Preserve the cell as a compact region,
    # including its degree-two corners, instead of inventing a one-pixel cut.
    for x, y in pixels:
        square = {(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)}
        if square <= pixels:
            junctions.update(square)
    regions = list(_connected(junctions, lambda point, region: tuple(p for p in adjacency[point] if p in region), budget))
    node_specs = []
    for region in regions:
        # Use the *full raster's* adjacency here. Recomputing adjacency on an
        # isolated region can introduce diagonal links previously suppressed by
        # chain pixels just outside it, double-counting a loop. Filled 2x2
        # plaquettes are faces, not holes in the digital (8,4) topology.
        internal_links = sum(sum(neighbor in region for neighbor in adjacency[pixel]) for pixel in region) // 2
        faces = sum({(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)} <= region for x, y in region)
        internal_holes = internal_links - len(region) + 1 - faces
        if internal_holes < 0:
            raise ValueError("SKELETON_JUNCTION_TOPOLOGY_MISMATCH")
        node_specs.append(("junction", region, internal_holes))
    node_specs.extend(("isolated" if not neighbors else "endpoint", {pixel}, 0)
                      for pixel, neighbors in adjacency.items() if len(neighbors) <= 1)
    node_pixels = {pixel for _, region, _ in node_specs for pixel in region}
    for group in groups:
        if not (group & node_pixels):
            # A degree-two component has no endpoint; preserve its entire loop.
            node_specs.append(("cycle_anchor", {min(group, key=_order)}, 0))
    node_specs.sort(key=lambda item: _order(min(item[1], key=_order)))
    if len(node_specs) > limits.max_nodes:
        raise SkeletonLimitError("SKELETON_NODE_LIMIT")
    nodes = tuple(SkeletonNode(node_id=f"n-{index}", component_id=f"c-{component_of[min(region, key=_order)]}",
                               kind=kind, anchor=min(region, key=_order), pixels=tuple(sorted(region, key=_order)), internal_holes=holes)
                  for index, (kind, region, holes) in enumerate(node_specs))
    node_of = {pixel: node.node_id for node in nodes for pixel in node.pixels}
    links: set[tuple[Pixel, Pixel]] = set()

    def link(a: Pixel, b: Pixel) -> tuple[Pixel, Pixel]:
        return (a, b) if _order(a) < _order(b) else (b, a)

    edges = []
    entries = sum(len(node.pixels) for node in nodes)
    if entries > limits.max_graph_points:
        raise SkeletonLimitError("SKELETON_EDGE_OR_POINT_LIMIT")
    for node in nodes:
        for start in node.pixels:
            for neighbor in adjacency[start]:
                if node_of.get(neighbor) == node.node_id or link(start, neighbor) in links:
                    continue
                path = [start, neighbor]
                links.add(link(start, neighbor))
                previous, current = start, neighbor
                while current not in node_of:
                    budget.take(8)
                    if len(adjacency[current]) != 2:
                        raise ValueError("SKELETON_CHAIN_DEGREE_MISMATCH")
                    following = next(point for point in adjacency[current] if point != previous)
                    if link(current, following) in links:
                        raise ValueError("SKELETON_CHAIN_REVISITED")
                    links.add(link(current, following))
                    path.append(following)
                    previous, current = current, following
                endpoint = node_of[current]
                a, b = node.node_id, endpoint
                forward = tuple(path)
                reverse = tuple(reversed(path))
                if int(a[2:]) > int(b[2:]) or (a == b and tuple(map(_order, reverse)) < tuple(map(_order, forward))):
                    a, b, forward = b, a, reverse
                entries += len(path)
                if len(edges) >= limits.max_edges or entries > limits.max_graph_points:
                    raise SkeletonLimitError("SKELETON_EDGE_OR_POINT_LIMIT")
                edges.append((a, b, forward))
    edges.sort(key=lambda item: (int(item[0][2:]), int(item[1][2:]), tuple(map(_order, item[2]))))
    typed_edges = tuple(SkeletonEdge(edge_id=f"e-{index}", component_id=nodes[int(a[2:])].component_id,
                                    node_a=a, node_b=b, pixels=path, closed=a == b,
                                    pixel_length=sum(math.hypot(bx - ax, by - ay) for (ax, ay), (bx, by) in zip(path, path[1:])))
                        for index, (a, b, path) in enumerate(edges))
    # Every non-junction link must have an explicit chain, including loop links.
    expected = {link(pixel, neighbor) for pixel, neighbors in adjacency.items() for neighbor in neighbors
                if node_of.get(pixel) is None or node_of.get(pixel) != node_of.get(neighbor)}
    if expected != links:
        raise ValueError("SKELETON_GRAPH_LINK_LOSS")
    represented = {pixel for node in nodes for pixel in node.pixels} | {pixel for edge in typed_edges for pixel in edge.pixels}
    if represented != pixels:
        raise ValueError("SKELETON_GRAPH_PIXEL_LOSS")
    components = []
    for index, group in enumerate(groups):
        identity = f"c-{index}"
        member_nodes = tuple(node for node in nodes if node.component_id == identity)
        member_edges = tuple(edge for edge in typed_edges if edge.component_id == identity)
        cycle_rank = len(member_edges) - len(member_nodes) + 1 + sum(node.internal_holes for node in member_nodes)
        if cycle_rank != _topology(group, budget).background_holes:
            raise ValueError("SKELETON_GRAPH_CYCLE_MISMATCH")
        components.append(SkeletonComponent(
            component_id=identity, input_ink_component=sources[index], skeleton_pixel_count=len(group),
            node_ids=tuple(node.node_id for node in member_nodes), edge_ids=tuple(edge.edge_id for edge in member_edges), cycle_rank=cycle_rank,
        ))
    return nodes, typed_edges, tuple(components)


def extract_skeleton(
    mask: BinaryInkMask, *, limits: SkeletonLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> SkeletonGraph:
    limits = SkeletonLimits.model_validate((limits or SkeletonLimits()).model_dump())
    budget = _Budget(limits, cancelled=cancelled)
    original = _mask_points(mask, limits)
    source_groups = _connected(original, _neighbors8, budget)
    if len(source_groups) > limits.max_components:
        raise SkeletonLimitError("SKELETON_COMPONENT_LIMIT")
    before = _topology(original, budget, source_groups)
    skeleton, iterations = _thin(original, budget)
    # Canonical graph components follow the surviving pixels. The original
    # InkComponent ID independently retains pre-thinning source ownership.
    after_groups = _connected(skeleton, _neighbors8, budget)
    _check_component_identity(source_groups, after_groups)
    owner = {pixel: index for index, group in enumerate(source_groups) for pixel in group}
    after = _topology(skeleton, budget, after_groups)
    if before != after:
        raise ValueError("SKELETON_TOPOLOGY_MISMATCH")
    sources = tuple(_ink_component(owner[next(iter(group))], source_groups[owner[next(iter(group))]]) for group in after_groups)
    nodes, edges, components = _graph_parts(skeleton, after_groups, sources, limits, budget)
    raw = tuple(sorted(skeleton, key=_order))
    data = bytearray(mask.width_px * mask.height_px)
    for x, y in raw:
        data[y * mask.width_px + x] = 1
    graph = SkeletonGraph(
        graph_id=str(uuid.uuid4()), created_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        provenance=SkeletonProvenance(input_mask_sha256=binary_mask_digest(mask)),
        width_px=mask.width_px, height_px=mask.height_px, skeleton_sha256=binary_mask_digest(BinaryInkMask(mask.width_px, mask.height_px, bytes(data))),
        raw_pixels=raw, input_topology=before, skeleton_topology=after, nodes=nodes, edges=edges, components=components,
        limits=limits, thinning_iterations=iterations, work_units=budget.work, removed_pixels=len(original) - len(skeleton),
        working_memory_estimate_bytes=_memory_estimate(len(mask.foreground), len(original)),
        diagnostics=("UNDIRECTED_NO_STROKE_ORDER", "DIAGONAL_CONTACTS_AMBIGUOUS", "NO_SPUR_PRUNING")
        + (("COMPACT_JUNCTION_REGIONS_RETAINED",) if any(len(node.pixels) > 1 for node in nodes) else ()),
    )
    graph.validate_input(mask)
    return graph


def extract_photo_skeleton(
    *, photos: PhotoRepository, source: PhotoRecord, review: TranscriptionReviewRecord,
    cropper: LineMaskCropper, limits: SkeletonLimits | None = None,
) -> SkeletonGraph:
    context, mask = verified_line_mask(photos=photos, source=source, review=review, cropper=cropper)
    if review.revision.status != "accepted":
        raise ValueError("SKELETON_REQUIRES_ACCEPTED_REVIEW")
    graph = extract_skeleton(mask, limits=limits)
    provenance = SkeletonProvenance(
        input_mask_sha256=graph.provenance.input_mask_sha256, source_manifest_sha256=source.sha256,
        line_id=review.revision.line_id, crop_sha256=review.revision.crop_sha256,
        encoded_mask_sha256=context.mask_sha256, review_revision_sha256=review.sha256,
        frame_id=context.frame_id, crop_left_px=context.crop_left_px, crop_top_px=context.crop_top_px,
    )
    return SkeletonGraph.model_validate({**graph.model_dump(), "provenance": provenance})


@dataclass(frozen=True, slots=True)
class SkeletonGraphRecord:
    sha256: str
    path: Path
    graph: SkeletonGraph


class SkeletonRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, digest: str) -> Path:
        if len(digest) != 64 or any(value not in "0123456789abcdef" for value in digest):
            raise ValueError("INVALID_SKELETON_RECORD_HASH")
        root = self.root.resolve()
        target = (root / "skeleton-graphs" / digest[:2] / f"{digest}.hp-skeleton-graph.json").resolve()
        if root not in target.parents:
            raise ValueError("SKELETON_PATH_OUTSIDE_DATA_ROOT")
        return target

    def store(self, graph: SkeletonGraph) -> SkeletonGraphRecord:
        graph = SkeletonGraph.model_validate(graph.model_dump())
        content = canonical_json_bytes(graph.model_dump(mode="json"))
        if len(content) > MAX_RECORD_BYTES:
            raise SkeletonLimitError("SKELETON_RECORD_TOO_LARGE")
        digest = sha256(content).hexdigest()
        path = self.path_for(digest)
        PhotoRepository._store_immutable(path, content, "SKELETON_RECORD_HASH_MISMATCH")
        return SkeletonGraphRecord(digest, path, graph)

    def load(self, digest: str) -> SkeletonGraphRecord:
        path = self.path_for(digest)
        if path.stat().st_size > MAX_RECORD_BYTES:
            raise SkeletonLimitError("SKELETON_RECORD_TOO_LARGE")
        content = path.read_bytes()
        if len(content) > MAX_RECORD_BYTES or sha256(content).hexdigest() != digest:
            raise ValueError("SKELETON_RECORD_HASH_MISMATCH")
        if not isinstance(strict_json_loads(content), dict):
            raise ValueError("INVALID_SKELETON_RECORD")
        return SkeletonGraphRecord(digest, path, SkeletonGraph.model_validate_json(content, strict=True))

    def load_current(
        self, digest: str, *, photos: PhotoRepository, source: PhotoRecord,
        review: TranscriptionReviewRecord, cropper: LineMaskCropper,
    ) -> SkeletonGraphRecord:
        record = self.load(digest)
        context, mask = verified_line_mask(photos=photos, source=source, review=review, cropper=cropper)
        provenance = record.graph.provenance
        current = (source.sha256, review.revision.line_id, review.revision.crop_sha256, context.mask_sha256,
                   review.sha256, context.frame_id, context.crop_left_px, context.crop_top_px)
        stored = (provenance.source_manifest_sha256, provenance.line_id, provenance.crop_sha256, provenance.encoded_mask_sha256,
                  provenance.review_revision_sha256, provenance.frame_id, provenance.crop_left_px, provenance.crop_top_px)
        if current != stored or review.revision.status != "accepted":
            raise AlignmentStaleError("SKELETON_PROVENANCE_STALE")
        record.graph.validate_input(mask)
        return record
