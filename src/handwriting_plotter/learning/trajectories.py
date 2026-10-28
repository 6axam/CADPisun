"""Bounded offline-inferred trail covers of immutable skeleton graphs.

These are reviewable geometric hypotheses, never observed online trajectories
or plotter paths. Compact junction interiors are deliberately not interpolated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import math
from pathlib import Path
from typing import Annotated, Callable, Literal

from pydantic import Field

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads
from .repository import PhotoRecord, PhotoRepository
from .skeleton import MAX_RECORD_BYTES, Pixel, SkeletonGraphRecord, SkeletonProvenance, SkeletonRepository
from .skeleton_cleanup import SkeletonCleanupRecord, SkeletonCleanupRepository, _verify_raw
from .transcription_review import TranscriptionReviewRecord
from .word_alignment import AlignmentStaleError, LineMaskCropper

PortId = Annotated[str, Field(pattern=r"^e-[0-9]+:[ab]$")]
EdgeId = Annotated[str, Field(pattern=r"^e-[0-9]+$")]
Direction = Literal["forward", "reverse", "unresolved"]


class TrajectoryLimitError(ValueError):
    """Admission/cancellation refusal, distinct from a bounded search fallback."""


class PortPair(StrictModel):
    port_a: PortId
    port_b: PortId


class EdgeDirectionConstraint(StrictModel):
    edge_id: EdgeId
    direction: Literal["forward", "reverse"]


class TrajectoryConstraints(StrictModel):
    origin: Literal["user_supplied"] = "user_supplied"
    required_joins: tuple[PortPair, ...] = Field(default=(), max_length=128)
    forbidden_joins: tuple[PortPair, ...] = Field(default=(), max_length=128)
    edge_directions: tuple[EdgeDirectionConstraint, ...] = Field(default=(), max_length=128)


class TrajectoryLimits(StrictModel):
    max_search_edges: int = Field(default=128, ge=1, le=512)
    max_search_nodes: int = Field(default=256, ge=1, le=1024)
    max_ports_per_node: int = Field(default=8, ge=2, le=8)
    max_local_options: int = Field(default=8, ge=1, le=32)
    beam_width: int = Field(default=16, ge=1, le=32)
    max_hypotheses: int = Field(default=8, ge=1, le=16)
    max_search_expansions: int = Field(default=20_000, ge=1, le=100_000)
    max_working_bytes: int = Field(default=256 * 1024 * 1024, ge=1024, le=256 * 1024 * 1024)


class DirectedSkeletonEdge(StrictModel):
    edge_id: EdgeId
    direction: Direction


class InferredStroke(StrictModel):
    stroke_id: str = Field(pattern=r"^s-[0-9]+$")
    component_id: str = Field(pattern=r"^c-[0-9]+$")
    kind: Literal["edge_trail", "isolated_mark", "unresolved_region"]
    traversals: tuple[DirectedSkeletonEdge, ...] = Field(default=(), max_length=16384)
    node_id: str | None = Field(default=None, pattern=r"^n-[0-9]+$")
    start_pixel: Pixel
    end_pixel: Pixel
    closed: bool = False


class JunctionPassage(PortPair):
    node_id: str = Field(pattern=r"^n-[0-9]+$")
    geometry: Literal["single_pixel", "unresolved_region"]
    turn_cost: float = Field(ge=0, le=1, allow_inf_nan=False)


class InferredPenLift(StrictModel):
    after_stroke_id: str = Field(pattern=r"^s-[0-9]+$")
    before_stroke_id: str = Field(pattern=r"^s-[0-9]+$")
    from_pixel: Pixel
    to_pixel: Pixel
    reason: Literal["between_components", "separate_trails"]
    observed: Literal[False] = False


class TrajectoryHypothesis(StrictModel):
    hypothesis_id: str = Field(pattern=r"^h-[0-9]+$")
    status: Literal["proposed", "unresolved"]
    ranking_cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    order_state: Literal["hypothesized", "unresolved"]
    strokes: tuple[InferredStroke, ...] = Field(default=(), max_length=24576)
    joins: tuple[JunctionPassage, ...] = Field(default=(), max_length=16384)
    pen_lifts: tuple[InferredPenLift, ...] = Field(default=(), max_length=24575)
    unresolved_node_ids: tuple[str, ...] = Field(default=(), max_length=8192)
    constraints_satisfied: bool
    direction_order_observed: Literal[False] = False


class TrajectoryRun(StrictModel):
    format: Literal["hp-trajectory-hypotheses"] = "hp-trajectory-hypotheses"
    schema_version: Literal["1.0"] = "1.0"
    algorithm: Literal["bounded-port-pairing/1"] = "bounded-port-pairing/1"
    evidence_origin: Literal["offline_inferred"] = "offline_inferred"
    created_at_utc: str = Field(min_length=1, max_length=64)
    raw_graph_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cleanup_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    provenance: SkeletonProvenance
    coordinate_system: Literal["line-crop-px-top-left"] = "line-crop-px-top-left"
    width_px: int = Field(gt=0, le=4_000_000)
    height_px: int = Field(gt=0, le=4_000_000)
    node_region_ids: tuple[str, ...] = Field(default=(), max_length=8192)
    limits: TrajectoryLimits
    constraints: TrajectoryConstraints
    hypotheses: tuple[TrajectoryHypothesis, ...] = Field(min_length=1, max_length=16)
    search_expansions: int = Field(ge=0, le=100_000)
    budget_exhausted: bool
    fallback_reason: Literal["search_limit", "graph_complexity", "constraint_coverage"] | None
    alternatives_truncated: bool
    working_memory_estimate_bytes: int = Field(ge=0)
    diagnostics: tuple[str, ...] = Field(max_length=24)

    def validate_parent(self, raw: SkeletonGraphRecord, cleanup: SkeletonCleanupRecord | None = None) -> None:
        if (self.raw_graph_sha256, self.cleanup_sha256) != (raw.sha256, None if cleanup is None else cleanup.sha256):
            raise AlignmentStaleError("TRAJECTORY_PARENT_STALE")
        expected = infer_trajectories(raw, cleanup=cleanup, constraints=self.constraints, limits=self.limits)
        if self.model_dump(exclude={"created_at_utc"}) != expected.model_dump(exclude={"created_at_utc"}):
            raise ValueError("TRAJECTORY_CONTENT_MISMATCH")


class _SearchExhausted(Exception):
    pass


@dataclass
class _Search:
    limits: TrajectoryLimits
    cancelled: Callable[[], bool] | None
    count: int = 0
    truncated: bool = False

    def tick(self) -> None:
        if self.cancelled is not None and self.cancelled():
            raise TrajectoryLimitError("TRAJECTORY_CANCELLED")
        if self.count >= self.limits.max_search_expansions:
            raise _SearchExhausted("search_limit")
        self.count += 1

    def best(self, values, key, cap):
        ordered = sorted(values, key=key)
        if len(ordered) > cap:
            self.truncated = True
        return ordered[:cap]


def _port_key(port: str) -> tuple[int, int]:
    edge, side = port.split(":")
    return int(edge[2:]), int(side == "b")


def _pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b), key=_port_key))


def _parents(raw, cleanup):
    _verify_raw(raw)
    if cleanup is None:
        return raw.graph
    if not isinstance(cleanup, SkeletonCleanupRecord):
        raise TypeError("TRAJECTORY_REQUIRES_CLEANUP_RECORD")
    content = canonical_json_bytes(cleanup.cleanup.model_dump(mode="json"))
    if len(content) > MAX_RECORD_BYTES or sha256(content).hexdigest() != cleanup.sha256:
        raise ValueError("TRAJECTORY_CLEANUP_HASH_MISMATCH")
    cleanup.cleanup.validate_raw(raw)
    return cleanup.cleanup


def _ports(graph):
    edges = {edge.edge_id: edge for edge in graph.edges}
    at_node = {node.node_id: [] for node in graph.nodes}
    node_of, point_of, tangent = {}, {}, {}
    for edge in graph.edges:
        for side, node_id, points in (("a", edge.node_a, edge.pixels), ("b", edge.node_b, tuple(reversed(edge.pixels)))):
            identity = f"{edge.edge_id}:{side}"
            at_node[node_id].append(identity)
            node_of[identity], point_of[identity] = node_id, points[0]
            # A short secant along the actual chain approximates local curvature
            # continuity. No artificial route through a junction is sampled.
            sample = points[min(3, len(points) - 1)]
            dx, dy = sample[0] - points[0][0], sample[1] - points[0][1]
            norm = math.hypot(dx, dy)
            if norm == 0:  # tiny closed chain may return to its start
                dx, dy = points[1][0] - points[0][0], points[1][1] - points[0][1]
                norm = math.hypot(dx, dy)
            tangent[identity] = dx / norm, dy / norm
    return edges, at_node, node_of, point_of, tangent


def _constraint_sets(constraints, edges, node_of):
    required, forbidden = set(), set()
    used = set()
    for collection, target in ((constraints.required_joins, required), (constraints.forbidden_joins, forbidden)):
        for item in collection:
            a, b = item.port_a, item.port_b
            if a == b or a not in node_of or b not in node_of or node_of[a] != node_of[b]:
                raise ValueError("INVALID_TRAJECTORY_PORT_CONSTRAINT")
            pair = _pair(a, b)
            if pair in target:
                raise ValueError("DUPLICATE_TRAJECTORY_CONSTRAINT")
            target.add(pair)
            if target is required:
                if a in used or b in used:
                    raise ValueError("CONFLICTING_TRAJECTORY_JOINS")
                used.update((a, b))
    if required & forbidden:
        raise ValueError("CONFLICTING_TRAJECTORY_JOINS")
    directions = {}
    for item in constraints.edge_directions:
        if item.edge_id not in edges or item.edge_id in directions:
            raise ValueError("INVALID_TRAJECTORY_DIRECTION_CONSTRAINT")
        directions[item.edge_id] = item.direction
    return required, forbidden, directions


def _local_options(ports, required, forbidden, turn, search):
    fixed = tuple(sorted((pair for pair in required if pair[0] in ports), key=lambda p: (_port_key(p[0]), _port_key(p[1]))))
    used = {p for pair in fixed for p in pair}
    free = tuple(p for p in ports if p not in used)
    options = []

    def visit(remaining, pairs):
        search.tick()
        if not remaining:
            full = tuple(sorted((*fixed, *pairs), key=lambda p: (_port_key(p[0]), _port_key(p[1]))))
            cost = sum(turn(a, b) for a, b in full) + .35 * (len(ports) - 2 * len(full))
            options.append((round(cost, 9), full))
            return
        first, *tail = remaining
        visit(tuple(tail), pairs)  # leave this port open: a possible pen lift
        for index, other in enumerate(tail):
            pair = _pair(first, other)
            if pair not in forbidden:
                visit(tuple(tail[:index] + tail[index + 1:]), (*pairs, pair))

    visit(free, ())
    return search.best(options, lambda item: (item[0], item[1]), search.limits.max_local_options)


def _trail_cover(edges, pairings):
    transitions = {p: q for a, b in pairings for p, q in ((a, b), (b, a))}
    ports = tuple(f"{identity}:{side}" for identity in edges for side in ("a", "b"))
    visited, trails = set(), []
    for start in (*tuple(p for p in ports if p not in transitions), *ports):
        if start.split(":")[0] in visited:
            continue
        port, trail = start, []
        while True:
            identity, side = port.split(":")
            if identity in visited:
                if port != start:
                    raise ValueError("TRAJECTORY_TRAIL_REVISIT")
                break
            visited.add(identity)
            trail.append((identity, "forward" if side == "a" else "reverse"))
            end = f"{identity}:{'b' if side == 'a' else 'a'}"
            if end not in transitions:
                break
            port = transitions[end]
        forward = tuple(trail)
        backward = tuple((identity, "reverse" if direction == "forward" else "forward") for identity, direction in reversed(trail))
        trails.append(min(forward, backward))
    return tuple(sorted(trails))


def _stroke(trail, edges, identity="s-0", direction_unknown=False):
    first_edge, first_direction = trail[0]
    last_edge, last_direction = trail[-1]
    first = edges[first_edge]
    last = edges[last_edge]
    start = first.pixels[0 if first_direction == "forward" else -1]
    end = last.pixels[-1 if last_direction == "forward" else 0]
    return InferredStroke(stroke_id=identity, component_id=first.component_id, kind="edge_trail",
                          traversals=tuple(DirectedSkeletonEdge(edge_id=edge, direction="unresolved" if direction_unknown else direction)
                                           for edge, direction in trail), start_pixel=start, end_pixel=end, closed=start == end)


def _marks(graph):
    incident = {edge.node_a for edge in graph.edges} | {edge.node_b for edge in graph.edges}
    return tuple(InferredStroke(stroke_id="s-0", component_id=node.component_id,
                                kind="isolated_mark" if node.kind == "isolated" else "unresolved_region",
                                node_id=node.node_id, start_pixel=node.anchor, end_pixel=node.anchor)
                 for node in graph.nodes if node.node_id not in incident)


def _routes(trails, graph, edges, directions, search):
    choices = []
    for trail in trails:
        backwards = tuple((edge, "reverse" if direction == "forward" else "forward") for edge, direction in reversed(trail))
        variants = tuple(_stroke(value, edges) for value in (trail, backwards)
                         if all(edge not in directions or directions[edge] == direction for edge, direction in value))
        if not variants:
            return []
        choices.append(variants)
    choices.extend((mark,) for mark in _marks(graph))
    if not choices:
        return [(0.0, ())]
    # Joint order/orientation beam. Starts and reverse orders remain alternatives;
    # travel distance ranks hypotheses but never asserts natural writing order.
    beam = [(0.0, (), frozenset())]
    for _ in range(len(choices)):
        expanded = []
        for cost, route, used in beam:
            for index, variants in enumerate(choices):
                if index in used:
                    continue
                for stroke in variants:
                    search.tick()
                    extra = 0.0 if not route else math.dist(route[-1].end_pixel, stroke.start_pixel) / max(graph.width_px, graph.height_px)
                    expanded.append((round(cost + extra, 9), (*route, stroke), used | {index}))
        beam = search.best(expanded, lambda value: (value[0], _route_key(value[1])), search.limits.beam_width)
    return [(cost, route) for cost, route, _ in beam]


def _route_key(route):
    return tuple((stroke.node_id or "", tuple((item.edge_id, item.direction) for item in stroke.traversals)) for stroke in route)


def _hypothesis(graph, route, joins, cost, *, unresolved=False):
    strokes = tuple(stroke.model_copy(update={"stroke_id": f"s-{index}"}) for index, stroke in enumerate(route))
    lifts = () if unresolved else tuple(InferredPenLift(after_stroke_id=a.stroke_id, before_stroke_id=b.stroke_id,
                                  from_pixel=a.end_pixel, to_pixel=b.start_pixel,
                                  reason="between_components" if a.component_id != b.component_id else "separate_trails")
                  for a, b in zip(strokes, strokes[1:]))
    return TrajectoryHypothesis(hypothesis_id="h-0", status="unresolved" if unresolved else "proposed",
                                ranking_cost=None if unresolved else round(cost + .7 * len(lifts), 9), strokes=strokes,
                                order_state="unresolved" if unresolved else "hypothesized",
                                joins=joins, pen_lifts=lifts, constraints_satisfied=not unresolved,
                                unresolved_node_ids=tuple(node.node_id for node in graph.nodes
                                                          if node.kind == "junction" and (len(node.pixels) > 1 or node.internal_holes)))


def infer_trajectories(
    raw: SkeletonGraphRecord, *, cleanup: SkeletonCleanupRecord | None = None,
    constraints: TrajectoryConstraints | None = None, limits: TrajectoryLimits | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> TrajectoryRun:
    if not isinstance(raw, SkeletonGraphRecord):
        raise TypeError("TRAJECTORY_REQUIRES_RAW_GRAPH_RECORD")
    constraints = TrajectoryConstraints.model_validate((constraints or TrajectoryConstraints()).model_dump())
    limits = TrajectoryLimits.model_validate((limits or TrajectoryLimits()).model_dump())
    estimate = raw.graph.width_px * raw.graph.height_px * 8 + len(raw.graph.raw_pixels) * 4096 + 65536
    if estimate > limits.max_working_bytes:
        raise TrajectoryLimitError("TRAJECTORY_MEMORY_LIMIT")
    if cancelled is not None and cancelled():
        raise TrajectoryLimitError("TRAJECTORY_CANCELLED")
    graph = _parents(raw, cleanup)
    if len(graph.edges) <= limits.max_search_edges and len(graph.nodes) <= limits.max_search_nodes:
        # Expanded ordering states carry tuples of prior stroke references.
        # Budget this quadratic workspace too, rather than only the raster.
        items = len(graph.edges) + len(graph.nodes)
        estimate += 64 * limits.beam_width * items * items + (262144 if items else 0)
        if estimate > limits.max_working_bytes:
            raise TrajectoryLimitError("TRAJECTORY_MEMORY_LIMIT")
    edges, at_node, node_of, _, tangent = _ports(graph)
    required, forbidden, directions = _constraint_sets(constraints, edges, node_of)
    search = _Search(limits, cancelled)
    fallback_reason = None
    nodes = {node.node_id: node for node in graph.nodes}

    def turn(a, b):
        ax, ay = tangent[a]
        bx, by = tangent[b]
        return round(max(0.0, min(1.0, (1 + ax * bx + ay * by) / 2)), 9)

    try:
        if len(edges) > limits.max_search_edges or len(nodes) > limits.max_search_nodes or any(
            len(ports) > limits.max_ports_per_node for ports in at_node.values()
        ):
            raise _SearchExhausted("graph_complexity")
        configurations = [(0.0, ())]
        for node in graph.nodes:
            ports = tuple(at_node[node.node_id])
            if len(ports) < 2:
                continue
            # A synthetic cycle anchor records closure, not an actual start.
            if node.kind == "cycle_anchor":
                pair = _pair(*ports)
                options = [(0.0, (pair,))] if pair not in forbidden else [(0.0, ())]
            else:
                options = _local_options(ports, required, forbidden, turn, search)
            expanded = []
            for cost, pairs in configurations:
                for extra, local in options:
                    search.tick()
                    expanded.append((round(cost + extra, 9), (*pairs, *local)))
            configurations = search.best(expanded, lambda item: (item[0], item[1]), limits.beam_width)
        per_configuration = []
        for cost, pairs in configurations:
            search.tick()
            trails = _trail_cover(edges, pairs)
            routes = _routes(trails, graph, edges, directions, search)
            joins = tuple(JunctionPassage(port_a=a, port_b=b, node_id=node_of[a],
                                          geometry="single_pixel" if len(nodes[node_of[a]].pixels) == 1 else "unresolved_region",
                                          turn_cost=turn(a, b)) for a, b in pairs)
            hypotheses = [_hypothesis(graph, route, joins, cost + travel) for travel, route in routes]
            hypotheses.sort(key=lambda h: (h.ranking_cost, _route_key(h.strokes)))
            if hypotheses:
                per_configuration.append(hypotheses)
        # Preserve distinct pairings before filling slots with more direction/
        # order variants of one pairing. Otherwise an X would hide alternatives.
        selected, seen = [], set()
        for rank in range(limits.beam_width):
            for group in per_configuration:
                if rank >= len(group):
                    continue
                hypothesis = group[rank]
                key = (_route_key(hypothesis.strokes), tuple((j.port_a, j.port_b) for j in hypothesis.joins))
                if key not in seen:
                    seen.add(key)
                    selected.append(hypothesis)
        if len(selected) > limits.max_hypotheses:
            search.truncated = True
        hypotheses = selected[:limits.max_hypotheses]
        hypotheses.sort(key=lambda h: (h.ranking_cost, _route_key(h.strokes)))
        if not hypotheses:
            raise _SearchExhausted("constraint_coverage")
    except _SearchExhausted as exc:
        fallback_reason = str(exc)
        # Complete coverage with no chosen directions or invented joins.
        route = tuple(_stroke(((edge.edge_id, "forward"),), edges, direction_unknown=True) for edge in graph.edges) + _marks(graph)
        hypotheses = [_hypothesis(graph, route, (), 0.0, unresolved=True)]
    diagnostics = ("OFFLINE_INFERRED_NOT_ONLINE_CAPTURE", "HEURISTIC_COST_NOT_PROBABILITY",
                   "DIRECTION_ORDER_AND_PEN_LIFTS_UNOBSERVED", "NO_RETRACING_IN_SINGLE_COVER_MODEL",
                   "JUNCTION_INTERIORS_NOT_INTERPOLATED")
    if any(stroke.closed for h in hypotheses for stroke in h.strokes):
        diagnostics += ("CYCLE_START_UNOBSERVED",)
    if fallback_reason is not None:
        diagnostics += (f"UNRESOLVED_{fallback_reason.upper()}",)
    return TrajectoryRun(
        created_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), raw_graph_sha256=raw.sha256,
        cleanup_sha256=None if cleanup is None else cleanup.sha256, provenance=graph.provenance,
        width_px=graph.width_px, height_px=graph.height_px, node_region_ids=tuple(node.node_id for node in graph.nodes),
        constraints=constraints, limits=limits,
        hypotheses=tuple(h.model_copy(update={"hypothesis_id": f"h-{i}"}) for i, h in enumerate(hypotheses)),
        search_expansions=search.count, budget_exhausted=fallback_reason in ("search_limit", "graph_complexity"),
        fallback_reason=fallback_reason, alternatives_truncated=search.truncated or fallback_reason is not None,
        working_memory_estimate_bytes=estimate, diagnostics=diagnostics,
    )


@dataclass(frozen=True, slots=True)
class TrajectoryRecord:
    sha256: str
    path: Path
    run: TrajectoryRun


class TrajectoryRepository:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.raw = SkeletonRepository(root)
        self.cleanups = SkeletonCleanupRepository(root)

    def path_for(self, digest: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("INVALID_TRAJECTORY_HASH")
        root = self.root.resolve()
        path = (root / "trajectory-hypotheses" / digest[:2] / f"{digest}.hp-trajectories.json").resolve()
        if root not in path.parents:
            raise ValueError("TRAJECTORY_PATH_OUTSIDE_DATA_ROOT")
        return path

    def _validate(self, run):
        raw = self.raw.load(run.raw_graph_sha256)
        cleanup = None if run.cleanup_sha256 is None else self.cleanups.load(run.cleanup_sha256)
        run.validate_parent(raw, cleanup)

    def store(self, run: TrajectoryRun) -> TrajectoryRecord:
        run = TrajectoryRun.model_validate(run.model_dump())
        self._validate(run)
        content = canonical_json_bytes(run.model_dump(mode="json"))
        if len(content) > MAX_RECORD_BYTES:
            raise TrajectoryLimitError("TRAJECTORY_RECORD_TOO_LARGE")
        digest = sha256(content).hexdigest()
        path = self.path_for(digest)
        PhotoRepository._store_immutable(path, content, "TRAJECTORY_RECORD_HASH_MISMATCH")
        return TrajectoryRecord(digest, path, run)

    def load(self, digest: str) -> TrajectoryRecord:
        path = self.path_for(digest)
        with path.open("rb") as stream:
            content = stream.read(MAX_RECORD_BYTES + 1)
        if len(content) > MAX_RECORD_BYTES:
            raise TrajectoryLimitError("TRAJECTORY_RECORD_TOO_LARGE")
        if sha256(content).hexdigest() != digest:
            raise ValueError("TRAJECTORY_RECORD_HASH_MISMATCH")
        strict_json_loads(content)
        run = TrajectoryRun.model_validate_json(content, strict=True)
        self._validate(run)
        return TrajectoryRecord(digest, path, run)

    def load_current(
        self, digest: str, *, raw_graph_sha256: str, cleanup_sha256: str | None = None,
        photos: PhotoRepository, source: PhotoRecord, review: TranscriptionReviewRecord, cropper: LineMaskCropper,
    ) -> TrajectoryRecord:
        record = self.load(digest)
        if (record.run.raw_graph_sha256, record.run.cleanup_sha256) != (raw_graph_sha256, cleanup_sha256):
            raise AlignmentStaleError("TRAJECTORY_SELECTION_STALE")
        self.raw.load_current(raw_graph_sha256, photos=photos, source=source, review=review, cropper=cropper)
        return record
