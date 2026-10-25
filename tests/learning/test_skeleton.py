"""Synthetic-only digital topology and raw graph tests for TASK 13A."""

from collections import deque
from pathlib import Path
import random
import subprocess
import sys

import pytest
from pydantic import ValidationError

from handwriting_plotter.learning import (
    AlignmentStaleError, BinaryInkMask, SkeletonGraph, SkeletonLimitError,
    SkeletonLimits, SkeletonRepository, extract_skeleton, topology_counts,
)


def _mask(points, width=24, height=20):
    return BinaryInkMask(width, height, bytes(int((x, y) in points) for y in range(height) for x in range(width)))


def _regions(points, connectivity):
    remaining = set(points)
    regions = []
    while remaining:
        start = min(remaining, key=lambda item: (item[1], item[0]))
        queue = deque([start])
        remaining.remove(start)
        region = {start}
        while queue:
            x, y = queue.popleft()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if (not dx and not dy) or (connectivity == 4 and abs(dx) + abs(dy) != 1):
                        continue
                    point = x + dx, y + dy
                    if point in remaining:
                        remaining.remove(point)
                        region.add(point)
                        queue.append(point)
        regions.append(region)
    return regions


def _independent_topology(mask):
    pixels = {(x, y) for y in range(mask.height_px) for x in range(mask.width_px) if mask.foreground[y * mask.width_px + x]}
    # Independent flood fill, not the implementation's local Euler formula.
    background = {(x, y) for y in range(-1, mask.height_px + 1) for x in range(-1, mask.width_px + 1)} - pixels
    return len(_regions(pixels, 8)), len(_regions(background, 4)) - 1


def _assert_geometry_and_topology(mask, graph):
    original = {(x, y) for y in range(mask.height_px) for x in range(mask.width_px) if mask.foreground[y * mask.width_px + x]}
    raw = set(graph.raw_pixels)
    assert raw <= original
    assert _independent_topology(mask) == _independent_topology(graph.skeleton_mask())
    assert (graph.input_topology.foreground_components, graph.input_topology.background_holes) == _independent_topology(mask)
    original_regions, raw_regions = _regions(original, 8), _regions(raw, 8)
    assert len(original_regions) == len(raw_regions)
    assert all(sum(bool(region & before) for region in raw_regions) == 1 for before in original_regions)
    assert all(any(region <= before for before in original_regions) for region in raw_regions)
    represented = {pixel for node in graph.nodes for pixel in node.pixels} | {pixel for edge in graph.edges for pixel in edge.pixels}
    assert represented == raw
    nodes = {node.node_id: node for node in graph.nodes}
    for edge in graph.edges:
        assert edge.pixels[0] in nodes[edge.node_a].pixels
        assert edge.pixels[-1] in nodes[edge.node_b].pixels
        assert all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1 for a, b in zip(edge.pixels, edge.pixels[1:]))
        assert set(edge.pixels) <= raw
        assert edge.closed == (edge.node_a == edge.node_b)
    assert [node.node_id for node in graph.nodes] == [f"n-{index}" for index in range(len(graph.nodes))]
    assert [edge.edge_id for edge in graph.edges] == [f"e-{index}" for index in range(len(graph.edges))]
    assert [node.anchor for node in graph.nodes] == sorted((node.anchor for node in graph.nodes), key=lambda p: (p[1], p[0]))
    for component in graph.components:
        assert component.cycle_rank == len(component.edge_ids) - len(component.node_ids) + 1 + sum(nodes[identity].internal_holes for identity in component.node_ids)
        anchor = nodes[component.node_ids[0]].anchor
        original_region = next(region for region in original_regions if anchor in region)
        assert component.cycle_rank == _independent_topology(_mask(original_region, mask.width_px, mask.height_px))[1]
    assert sum(component.cycle_rank for component in graph.components) == graph.skeleton_topology.background_holes
    graph.validate_input(mask)


@pytest.mark.parametrize("points,endpoints", [
    ({(x, 4) for x in range(2, 12)}, {(2, 4), (11, 4)}),
    ({(4, y) for y in range(2, 12)}, {(4, 2), (4, 11)}),
    ({(x, x) for x in range(2, 12)}, {(2, 2), (11, 11)}),
    ({(x, 4) for x in range(0, 24)}, {(0, 4), (23, 4)}),
])
def test_single_pixel_chains_have_exact_ordered_geometry_and_endpoints(points, endpoints):
    mask = _mask(points)
    graph = extract_skeleton(mask)
    assert {node.anchor for node in graph.nodes} == endpoints
    assert all(node.kind == "endpoint" for node in graph.nodes)
    assert len(graph.edges) == 1 and set(graph.edges[0].pixels) == points
    assert graph.removed_pixels == 0
    _assert_geometry_and_topology(mask, graph)


@pytest.mark.parametrize("points,arms", [
    ({(x, 3) for x in range(2, 13)} | {(7, y) for y in range(3, 12)}, 3),
    ({(i, i) for i in range(2, 13)} | {(i, 14 - i) for i in range(2, 13)}, 4),
])
def test_t_and_x_junctions_keep_branches_without_pen_order(points, arms):
    mask = _mask(points)
    graph = extract_skeleton(mask)
    assert sum(node.kind == "endpoint" for node in graph.nodes) == arms
    assert sum(node.kind == "junction" for node in graph.nodes) == 1
    assert len(graph.edges) == arms and graph.components[0].cycle_rank == 0
    assert "UNDIRECTED_NO_STROKE_ORDER" in graph.diagnostics
    _assert_geometry_and_topology(mask, graph)


def _ring(left, top, right, bottom):
    return {(x, y) for y in range(top, bottom + 1) for x in range(left, right + 1) if x in (left, right) or y in (top, bottom)}


def test_cycle_without_endpoint_has_canonical_anchor_and_closed_edge():
    points = _ring(2, 2, 10, 10)
    mask = _mask(points)
    graph = extract_skeleton(mask)
    assert len(graph.nodes) == len(graph.edges) == 1
    assert graph.nodes[0].kind == "cycle_anchor" and graph.nodes[0].anchor == (2, 2)
    edge = graph.edges[0]
    assert edge.closed and edge.pixels[0] == edge.pixels[-1] == (2, 2)
    assert len(edge.pixels) == len(points) + 1
    assert set(edge.pixels) == points
    _assert_geometry_and_topology(mask, graph)


@pytest.mark.parametrize("joined", [False, True])
def test_two_loops_remain_two_cycles_with_or_without_connecting_stroke(joined):
    points = _ring(1, 2, 7, 10) | _ring(12, 2, 18, 10)
    if joined:
        points |= {(x, 6) for x in range(7, 13)}
    mask = _mask(points)
    graph = extract_skeleton(mask)
    assert graph.input_topology.foreground_components == (1 if joined else 2)
    assert sum(component.cycle_rank for component in graph.components) == 2
    _assert_geometry_and_topology(mask, graph)


@pytest.mark.parametrize("dots", [{(7, 1)}, {(5, 1), (9, 1)}])
def test_i_yi_marks_survive_as_independent_original_components(dots):
    points = dots | {(x, y) for y in range(5, 15) for x in range(5, 10)}
    mask = _mask(points)
    original = mask.foreground
    graph = extract_skeleton(mask)
    assert mask.foreground == original
    assert {node.anchor for node in graph.nodes if node.kind == "isolated"} == dots
    assert len(graph.components) == len(dots) + 1
    assert dots <= set(graph.raw_pixels)
    _assert_geometry_and_topology(mask, graph)


def test_isolated_pixels_short_strokes_and_boundary_components_are_not_pruned():
    points = {(0, 0), (23, 19), (4, 5), (5, 5), (10, 6), (11, 7)}
    mask = _mask(points)
    graph = extract_skeleton(mask)
    assert set(graph.raw_pixels) == points
    assert len(graph.components) == 4
    assert sum(node.kind == "isolated" for node in graph.nodes) == 2
    assert len(graph.edges) == 2
    _assert_geometry_and_topology(mask, graph)


def test_thick_cursive_and_ring_are_thinned_without_hole_or_component_loss():
    ring = {(x, y) for x in range(2, 21) for y in range(2, 17) if not (6 <= x <= 16 and 6 <= y <= 12)}
    mask = _mask(ring)
    graph = extract_skeleton(mask)
    assert 0 < len(graph.raw_pixels) < len(ring)
    assert graph.components[0].cycle_rank == 1
    assert graph.removed_pixels > 0 and graph.thinning_iterations > 1
    _assert_geometry_and_topology(mask, graph)


def test_thick_junction_region_preserves_raw_pixels_and_internal_links():
    # This seeded pattern exercises a thick junction with a chain just outside
    # its boundary. Recomputing adjacency on the region alone adds a false
    # diagonal; internal cycle accounting must use full-raster adjacency.
    rows = ("#...####", ".#####..", "###.....", "..#.#..#", "####....", "..#.####", "##.#####", "###..#..")
    points = {(x, y) for y, row in enumerate(rows) for x, value in enumerate(row) if value == "#"}
    mask = _mask(points, 8, 8)
    graph = extract_skeleton(mask)
    assert any(node.kind == "junction" and len(node.pixels) > 1 for node in graph.nodes)
    assert "COMPACT_JUNCTION_REGIONS_RETAINED" in graph.diagnostics
    assert graph.components[0].cycle_rank == 2
    _assert_geometry_and_topology(mask, graph)


def test_filled_2x2_never_disappears_or_becomes_a_false_ring():
    points = {(x, y) for x in (2, 3) for y in (2, 3)}
    mask = _mask(points)
    graph = extract_skeleton(mask)
    assert graph.raw_pixels and graph.components[0].cycle_rank == 0
    _assert_geometry_and_topology(mask, graph)


def test_empty_mask_is_an_explicit_empty_graph():
    graph = extract_skeleton(_mask(set()))
    assert not graph.raw_pixels and not graph.nodes and not graph.edges and not graph.components
    assert graph.skeleton_topology.foreground_components == graph.skeleton_topology.background_holes == 0


def test_all_512_local_patterns_preserve_independent_digital_topology():
    for value in range(512):
        mask = BinaryInkMask(3, 3, bytes((value >> index) & 1 for index in range(9)))
        _assert_geometry_and_topology(mask, extract_skeleton(mask))


def test_seeded_thick_masks_preserve_component_identity_and_cycle_geometry():
    rng = random.Random(13)
    for _ in range(128):
        mask = BinaryInkMask(8, 8, bytes(int(rng.random() < 0.55) for _ in range(64)))
        _assert_geometry_and_topology(mask, extract_skeleton(mask))


def test_reproducible_geometry_and_canonical_ids_with_independent_event_metadata():
    mask = _mask(_ring(2, 2, 10, 10) | {(18, y) for y in range(3, 12)})
    first, second = extract_skeleton(mask), extract_skeleton(mask)
    assert first.graph_id != second.graph_id
    assert first.model_dump(exclude={"graph_id", "created_at_utc"}) == second.model_dump(exclude={"graph_id", "created_at_utc"})


def test_thinning_is_idempotent_and_retains_the_unpruned_raw_skeleton():
    points = {(x, y) for x in range(2, 21) for y in range(2, 17) if not (6 <= x <= 16 and 6 <= y <= 12)}
    first = extract_skeleton(_mask(points))
    second = extract_skeleton(first.skeleton_mask())
    assert first.raw_pixels == second.raw_pixels
    assert first.skeleton_sha256 == second.skeleton_sha256
    assert first.nodes == second.nodes and first.edges == second.edges
    assert second.removed_pixels == 0


@pytest.mark.parametrize("limit,code", [
    ({"max_pixels": 10}, "SKELETON_PIXEL_LIMIT"),
    ({"max_foreground": 1}, "SKELETON_FOREGROUND_LIMIT"),
    ({"max_work_units": 1}, "SKELETON_WORK_LIMIT"),
    ({"max_working_bytes": 1024}, "SKELETON_MEMORY_LIMIT"),
    ({"max_iterations": 1}, "SKELETON_ITERATION_LIMIT"),
    ({"max_nodes": 1}, "SKELETON_NODE_LIMIT"),
    ({"max_graph_points": 1}, "SKELETON_EDGE_OR_POINT_LIMIT"),
])
def test_limits_refuse_without_partial_result_or_changed_input(limit, code):
    mask = _mask({(x, y) for x in range(2, 12) for y in range(2, 12)})
    before = mask.foreground
    with pytest.raises(SkeletonLimitError, match=code):
        extract_skeleton(mask, limits=SkeletonLimits(**limit))
    assert mask.foreground == before


def test_component_edge_limits_and_cancellation():
    with pytest.raises(SkeletonLimitError, match="SKELETON_COMPONENT_LIMIT"):
        extract_skeleton(_mask({(1, 1), (10, 10)}), limits=SkeletonLimits(max_components=1))
    points = {(x, 3) for x in range(2, 13)} | {(7, y) for y in range(3, 12)}
    with pytest.raises(SkeletonLimitError, match="SKELETON_EDGE_OR_POINT_LIMIT"):
        extract_skeleton(_mask(points), limits=SkeletonLimits(max_edges=1))
    with pytest.raises(SkeletonLimitError, match="SKELETON_CANCELLED"):
        extract_skeleton(_mask(points), cancelled=lambda: True)


def test_malformed_and_mutable_binary_masks_are_refused():
    with pytest.raises(ValueError, match="INVALID_SKELETON_BINARY_MASK"):
        extract_skeleton(BinaryInkMask(2, 2, bytearray((0, 1, 0, 1))))
    with pytest.raises(ValueError, match="INVALID_BINARY_MASK_VALUE"):
        BinaryInkMask(2, 2, bytes((0, 2, 0, 1)))


def test_immutable_storage_reopen_tampering_and_graph_geometry_validation(tmp_path: Path):
    mask = _mask(_ring(2, 2, 10, 10))
    graph = extract_skeleton(mask)
    repository = SkeletonRepository(tmp_path)
    stored = repository.store(graph)
    assert repository.load(stored.sha256) == stored
    assert repository.store(graph) == stored
    altered = graph.model_dump()
    altered["edges"] = (graph.edges[0].model_copy(update={"pixels": tuple(reversed(graph.edges[0].pixels))}),)
    with pytest.raises(ValidationError, match="SKELETON_GRAPH_GEOMETRY_MISMATCH"):
        SkeletonGraph.model_validate(altered)
    altered = graph.model_dump()
    altered["skeleton_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="SKELETON_RASTER_HASH_MISMATCH"):
        SkeletonGraph.model_validate(altered)
    with pytest.raises(AlignmentStaleError, match="SKELETON_INPUT_MASK_STALE"):
        graph.validate_input(_mask({(2, 2)}))
    stored.path.write_bytes(b"corrupt synthetic skeleton record")
    with pytest.raises(ValueError, match="SKELETON_RECORD_HASH_MISMATCH"):
        repository.load(stored.sha256)
    with pytest.raises(ValueError, match="SKELETON_RECORD_HASH_MISMATCH"):
        repository.store(graph)
    with pytest.raises(ValueError, match="INVALID_SKELETON_RECORD_HASH"):
        repository.path_for("../../bad")


def test_module_import_has_no_optional_runtime_side_effects():
    process = subprocess.run([sys.executable, "-c", """
import sys
from handwriting_plotter.learning import extract_skeleton
assert not any(name in sys.modules for name in ('cv2', 'numpy', 'PySide6', 'torch', 'transformers'))
"""], capture_output=True, text=True, timeout=10)
    assert process.returncode == 0, process.stderr
