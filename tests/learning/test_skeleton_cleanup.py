"""Synthetic-only TASK 13B acceptance: short does not imply noise."""

from hashlib import sha256
import random
import xml.etree.ElementTree as ET
from collections import deque

import pytest

from handwriting_plotter.domain.models import canonical_json_bytes
from handwriting_plotter.learning import (
    AlignmentStaleError, BinaryInkMask, SkeletonCleanup, SkeletonCleanupLimits, SkeletonCleanupPolicy,
    SkeletonCleanupRepository, SkeletonLimitError, SkeletonRepository,
    cleanup_skeleton, extract_skeleton, render_skeleton_overlay_svg, topology_counts,
)


def mask(points, width=32, height=24):
    return BinaryInkMask(width, height, bytes(int((x, y) in points) for y in range(height) for x in range(width)))


def raw_record(tmp_path, points):
    return SkeletonRepository(tmp_path).store(extract_skeleton(mask(points)))


def tee():
    return {(x, 10) for x in range(3, 23)} | {(12, y) for y in range(8, 11)}


def test_default_preserves_all_ink_and_only_proposes_ambiguous_spur(tmp_path):
    points = tee() | {(3, 2), (6, 2), (26, 6), (27, 6)}
    raw = raw_record(tmp_path, points)
    before = raw.path.read_bytes()
    result = cleanup_skeleton(raw)
    assert result.retained_pixels == raw.graph.raw_pixels
    assert result.nodes == raw.graph.nodes and result.edges == raw.graph.edges
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.ambiguous and candidate.pixel_length == 2
    assert set(candidate.removable_pixels) == {(12, 8), (12, 9)}
    assert not result.removed_edge_ids and not result.removed_pixels
    assert raw.path.read_bytes() == before


def test_explicit_single_pass_removal_keeps_marks_loops_and_collapses_degree_two(tmp_path):
    ring = {(x, y) for x in range(24, 30) for y in range(13, 20) if x in (24, 29) or y in (13, 19)}
    raw = raw_record(tmp_path, tee() | ring | {(3, 2), (6, 2), (26, 6), (27, 6)})
    candidate = cleanup_skeleton(raw).candidates[0]
    result = cleanup_skeleton(raw, remove_edge_ids=(candidate.edge_id,))
    assert set(result.removed_pixels) == {(12, 8), (12, 9)}
    assert set(result.retained_pixels) == set(raw.graph.raw_pixels) - set(result.removed_pixels)
    assert topology_counts(result.skeleton_mask()) == raw.graph.skeleton_topology
    assert len(result.components) == len(raw.graph.components)
    assert sum(c.cycle_rank for c in result.components) == 1
    assert {(3, 2), (6, 2), (26, 6), (27, 6)} <= set(result.retained_pixels)
    assert len(result.edges) == len(raw.graph.edges) - 2  # two remaining arms become one chain
    assert result.provenance == raw.graph.provenance
    assert result.raw_graph_sha256 == raw.sha256
    result.validate_raw(raw)


def test_no_cascading_or_automatic_removal_on_t_x_and_cycles(tmp_path):
    points = {(x, 10) for x in range(10, 15)} | {(12, y) for y in range(8, 13)}
    raw = raw_record(tmp_path, points)
    preview = cleanup_skeleton(raw)
    assert len(preview.candidates) == 4
    with pytest.raises(ValueError, match="JUNCTION_SUPPORT"):
        cleanup_skeleton(raw, remove_edge_ids=tuple(c.edge_id for c in preview.candidates))
    selected = tuple(c.edge_id for c in preview.candidates[:2])
    result = cleanup_skeleton(raw, remove_edge_ids=selected)
    assert len(result.removed_edge_ids) == 2 and len(result.edges) == 1
    assert len(result.candidates) == 4  # snapshot of raw graph, no iterative erosion


@pytest.mark.parametrize("points", [set(), {(0, 0)}, {(0, 0), (1, 1)},
    {(x, y) for x in range(2, 9) for y in range(2, 9) if x in (2, 8) or y in (2, 8)},
    {(x, 10) for x in range(4, 24)}])
def test_dots_short_components_empty_loops_and_straights_are_never_candidates(tmp_path, points):
    raw = raw_record(tmp_path, points)
    result = cleanup_skeleton(raw)
    assert not result.candidates and result.retained_pixels == raw.graph.raw_pixels
    assert result.nodes == raw.graph.nodes and result.components == raw.graph.components


def test_threshold_selection_validation_and_reproducibility(tmp_path):
    raw = raw_record(tmp_path, tee())
    assert not cleanup_skeleton(raw, policy=SkeletonCleanupPolicy(max_spur_length_px=1)).candidates
    a, b = cleanup_skeleton(raw), cleanup_skeleton(raw)
    assert a.model_dump(exclude={"created_at_utc"}) == b.model_dump(exclude={"created_at_utc"})
    identity = a.candidates[0].edge_id
    for selected in (("e-999",), (identity, identity)):
        with pytest.raises(ValueError, match="SPUR_SELECTION"):
            cleanup_skeleton(raw, remove_edge_ids=selected)
    with pytest.raises(ValueError):
        SkeletonCleanupPolicy(max_spur_length_px=float("nan"))


@pytest.mark.parametrize("limits,code", [
    ({"max_work_units": 1}, "WORK_LIMIT"), ({"max_working_bytes": 1024}, "MEMORY_LIMIT"),
    ({"max_candidates": 1}, "CANDIDATE_LIMIT"),
])
def test_budgets_refuse_without_partial_results(tmp_path, limits, code):
    points = {(x, 10) for x in range(10, 15)} | {(12, y) for y in range(8, 13)}
    raw = raw_record(tmp_path, points)
    before = raw.path.read_bytes()
    with pytest.raises(SkeletonLimitError, match=code):
        cleanup_skeleton(raw, limits=SkeletonCleanupLimits(**limits))
    assert raw.path.read_bytes() == before


def test_cancel_and_removal_limit(tmp_path):
    raw = raw_record(tmp_path, tee())
    with pytest.raises(SkeletonLimitError, match="CANCELLED"):
        cleanup_skeleton(raw, cancelled=lambda: True)
    candidate = cleanup_skeleton(raw).candidates[0]
    with pytest.raises(SkeletonLimitError, match="REMOVAL_LIMIT"):
        cleanup_skeleton(raw, remove_edge_ids=(candidate.edge_id,), limits=SkeletonCleanupLimits(max_removals=0))


def test_immutable_persistence_raw_binding_and_corruption(tmp_path):
    raw = raw_record(tmp_path, tee())
    repo = SkeletonCleanupRepository(tmp_path)
    result = cleanup_skeleton(raw)
    record = repo.store(result)
    assert repo.store(result) == record and repo.load(record.sha256) == record
    data = result.model_dump()
    data["retained_pixels"] = data["retained_pixels"][:-1]
    bad = SkeletonCleanup.model_validate(data)
    with pytest.raises(ValueError, match="CLEANUP_CONTENT_MISMATCH"):
        repo.store(bad)
    content = canonical_json_bytes(data)
    digest = sha256(content).hexdigest()
    path = repo.path_for(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    with pytest.raises(ValueError, match="CLEANUP_CONTENT_MISMATCH"):
        repo.load(digest)
    record.path.write_bytes(b"broken synthetic cleanup")
    with pytest.raises(ValueError, match="CLEANUP_RECORD_HASH"):
        repo.load(record.sha256)
    raw.path.write_bytes(b"broken synthetic raw")
    with pytest.raises(ValueError, match="SKELETON_RECORD_HASH"):
        repo.store(result)
    with pytest.raises(ValueError, match="INVALID_CLEANUP_RECORD_HASH"):
        repo.path_for("../escape")


def test_seeded_masks_have_exact_noop_geometry_and_no_semantic_noise_claim(tmp_path):
    rng = random.Random(1302)
    for _ in range(32):
        points = {(x, y) for y in range(8) for x in range(8) if rng.random() < .5}
        raw = raw_record(tmp_path, points)
        result = cleanup_skeleton(raw)
        assert result.retained_pixels == raw.graph.raw_pixels
        assert (result.nodes, result.edges, result.components) == (raw.graph.nodes, raw.graph.edges, raw.graph.components)
        assert all(candidate.ambiguous for candidate in result.candidates)


def test_svg_diagnostic_geometry_legend_and_removed_raw_pixels(tmp_path):
    raw = raw_record(tmp_path, tee() | {(0, 0)})
    candidate = cleanup_skeleton(raw).candidates[0]
    result = cleanup_skeleton(raw, remove_edge_ids=(candidate.edge_id,))
    svg = render_skeleton_overlay_svg(raw, cleanup=result)
    root = ET.fromstring(svg)
    assert root.attrib["viewBox"] == "0 0 32 24"
    assert root.attrib["data-purpose"] == "diagnostic-only"
    assert "marker-end" not in svg
    elements = list(root.iter())
    assert len([el for el in elements if el.get("data-layer") == "removed-pixel"]) == 2
    assert any(el.get("data-kind") == "isolated" for el in elements)
    assert "ambiguous" in svg and "no pen order" in svg
    assert "12,8" in svg or 'x="12" y="8"' in svg


def test_overlay_size_budget_and_wrong_raw_are_refused(tmp_path):
    raw = raw_record(tmp_path, tee())
    result = cleanup_skeleton(raw)
    other = raw_record(tmp_path, {(1, 1)})
    with pytest.raises(AlignmentStaleError, match="RAW_REFERENCE"):
        render_skeleton_overlay_svg(other, cleanup=result)
    with pytest.raises(SkeletonLimitError, match="OVERLAY_LIMIT"):
        render_skeleton_overlay_svg(raw, max_bytes=10)


def test_original_component_identity_survives_canonical_reordering(tmp_path):
    raw = raw_record(tmp_path, tee() | {(28, 9)})
    result = cleanup_skeleton(raw, remove_edge_ids=(cleanup_skeleton(raw).candidates[0].edge_id,))
    assert [c.input_ink_component.component_id for c in result.components] == ["component-1", "component-0"]
    assert result.nodes[0].anchor == (28, 9)
    assert result.components[0].component_id == "c-0"


def test_removing_an_explicit_loop_tail_preserves_closed_cycle_and_anchor(tmp_path):
    ring = {(x, y) for x in range(5, 16) for y in range(6, 17) if x in (5, 15) or y in (6, 16)}
    raw = raw_record(tmp_path, ring | {(10, 4), (10, 5)})
    candidate = cleanup_skeleton(raw).candidates[0]
    result = cleanup_skeleton(raw, remove_edge_ids=(candidate.edge_id,))
    assert set(result.retained_pixels) == ring
    assert len(result.nodes) == len(result.edges) == 1
    assert result.nodes[0].kind == "cycle_anchor"
    assert result.edges[0].closed and result.components[0].cycle_rank == 1
    assert result.edges[0].pixels[0] == result.edges[0].pixels[-1] == (5, 6)


def test_selection_order_is_canonical_and_prior_derivative_cannot_cascade(tmp_path):
    points = {(x, 10) for x in range(10, 15)} | {(12, y) for y in range(8, 13)}
    raw = raw_record(tmp_path, points)
    candidates = cleanup_skeleton(raw).candidates
    selected = tuple(candidate.edge_id for candidate in candidates[:2])
    first = cleanup_skeleton(raw, remove_edge_ids=selected)
    second = cleanup_skeleton(raw, remove_edge_ids=tuple(reversed(selected)))
    assert first.model_dump(exclude={"created_at_utc"}) == second.model_dump(exclude={"created_at_utc"})
    # A derived record is not an accepted raw input type.
    derived = SkeletonCleanupRepository(tmp_path).store(first)
    with pytest.raises((AttributeError, TypeError)):
        cleanup_skeleton(derived)


def test_synthetic_selection_preserves_independent_flood_fill_topology(tmp_path):
    def regions(points, connectivity):
        remaining = set(points)
        groups = []
        while remaining:
            start = remaining.pop()
            queue, group = deque([start]), {start}
            while queue:
                x, y = queue.popleft()
                for dx, dy in ((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                               if (dx or dy) and (connectivity == 8 or abs(dx) + abs(dy) == 1)):
                    pixel = x + dx, y + dy
                    if pixel in remaining:
                        remaining.remove(pixel)
                        group.add(pixel)
                        queue.append(pixel)
            groups.append(group)
        return groups

    def topology(points):
        exterior = {(x, y) for x in range(-1, 33) for y in range(-1, 25)} - points
        return len(regions(points, 8)), len(regions(exterior, 4)) - 1

    rng = random.Random(1303)
    admitted, refused = 0, 0
    for _ in range(32):
        points = {(x + 2, y + 2) for y in range(8) for x in range(8) if rng.random() < .5}
        raw = raw_record(tmp_path, points)
        proposed = cleanup_skeleton(raw)
        for candidate in proposed.candidates:
            try:
                result = cleanup_skeleton(raw, remove_edge_ids=(candidate.edge_id,))
            except ValueError as exc:
                assert "CLEANUP_" in str(exc) or "SKELETON_" in str(exc)
                refused += 1
                continue
            admitted += 1
            retained = set(result.retained_pixels)
            assert topology(set(raw.graph.raw_pixels)) == topology(retained)
            assert retained <= set(raw.graph.raw_pixels)
            original_groups = regions(set(raw.graph.raw_pixels), 8)
            groups = regions(retained, 8)
            assert all(sum(bool(a & b) for b in groups) == 1 for a in original_groups)
            assert all(set(node.pixels) <= retained for node in result.nodes)
            assert all(set(edge.pixels) <= retained for edge in result.edges)
            assert {p for n in result.nodes for p in n.pixels} | {p for e in result.edges for p in e.pixels} == retained
            assert all(set(node.pixels) <= retained for node in raw.graph.nodes if node.kind == "junction")
    assert admitted > 0
    assert admitted + refused > 10


@pytest.mark.parametrize("field,value", [
    ("provenance", None), ("work_units", 0), ("working_memory_estimate_bytes", 0),
    ("width_px", 33), ("nodes", ()), ("candidates", ()), ("diagnostics", ()),
])
def test_derived_metadata_and_geometry_cannot_be_forged(tmp_path, field, value):
    raw = raw_record(tmp_path, tee())
    result = cleanup_skeleton(raw)
    data = result.model_dump()
    data[field] = value if field != "provenance" else result.provenance.model_copy(update={"input_mask_sha256": "f" * 64})
    altered = SkeletonCleanup.model_validate(data)
    with pytest.raises(ValueError, match="CLEANUP_CONTENT_MISMATCH"):
        SkeletonCleanupRepository(tmp_path).store(altered)


def test_bounded_records_missing_raw_and_invalid_json(tmp_path, monkeypatch):
    import handwriting_plotter.learning.skeleton_cleanup as module

    raw = raw_record(tmp_path, tee())
    repo = SkeletonCleanupRepository(tmp_path)
    result = cleanup_skeleton(raw)
    record = repo.store(result)
    monkeypatch.setattr(module, "MAX_RECORD_BYTES", 16)
    with pytest.raises(SkeletonLimitError, match="CLEANUP_RECORD_TOO_LARGE"):
        repo.load(record.sha256)
    monkeypatch.undo()
    raw.path.unlink()
    with pytest.raises(FileNotFoundError):
        repo.load(record.sha256)
    for content in (b'{"format":"a","format":"b"}', b'{"value":NaN}'):
        digest = sha256(content).hexdigest()
        path = repo.path_for(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        with pytest.raises(ValueError, match="duplicate|non-finite"):
            repo.load(digest)


def test_input_overlay_requires_original_mask_and_exact_raw_reference(tmp_path):
    points = tee()
    raw = raw_record(tmp_path, points)
    svg = render_skeleton_overlay_svg(raw, input_mask=mask(points))
    assert 'data-layer="ink"' in svg
    with pytest.raises(AlignmentStaleError, match="INPUT_MASK_STALE"):
        render_skeleton_overlay_svg(raw, input_mask=mask({(0, 0)}))
    forged = type(raw)("f" * 64, raw.path, raw.graph)
    with pytest.raises(ValueError, match="RAW_RECORD_HASH"):
        cleanup_skeleton(forged)
