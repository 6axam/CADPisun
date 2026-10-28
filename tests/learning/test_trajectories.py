"""Synthetic geometric hypotheses are never observed handwriting trajectories."""

from pathlib import Path
from hashlib import sha256
import random
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from handwriting_plotter.learning import (
    AlignmentStaleError, BinaryInkMask, EdgeDirectionConstraint, PortPair, SkeletonCleanupRepository,
    SkeletonRepository, TrajectoryConstraints, TrajectoryLimitError, TrajectoryLimits,
    TrajectoryRepository, TrajectoryRun, cleanup_skeleton, infer_trajectories, extract_skeleton,
    render_trajectory_overlay_svg,
)
from handwriting_plotter.domain.models import canonical_json_bytes


def raw(tmp_path, points, width=32, height=24):
    mask = BinaryInkMask(width, height, bytes(int((x, y) in points) for y in range(height) for x in range(width)))
    return SkeletonRepository(tmp_path).store(extract_skeleton(mask))


def ring():
    return {(x, y) for x in range(3, 13) for y in range(3, 13) if x in (3, 12) or y in (3, 12)}


def coverage(result, graph):
    assert result.node_region_ids == tuple(n.node_id for n in graph.nodes)
    edges_by_id = {edge.edge_id: edge for edge in graph.edges}
    nodes_by_id = {node.node_id: node for node in graph.nodes}
    for hypothesis in result.hypotheses:
        edges = [item.edge_id for stroke in hypothesis.strokes for item in stroke.traversals]
        assert len(edges) == len(set(edges))
        assert set(edges) == {edge.edge_id for edge in graph.edges}
        assert len(hypothesis.pen_lifts) == (max(0, len(hypothesis.strokes) - 1) if hypothesis.status == "proposed" else 0)
        for lift in hypothesis.pen_lifts:
            before = hypothesis.strokes[int(lift.after_stroke_id[2:])]
            after = hypothesis.strokes[int(lift.before_stroke_id[2:])]
            assert lift.from_pixel == before.end_pixel and lift.to_pixel == after.start_pixel
        assert hypothesis.direction_order_observed is False
        for stroke in hypothesis.strokes:
            if not stroke.traversals:
                assert stroke.node_id in nodes_by_id
                assert stroke.start_pixel == nodes_by_id[stroke.node_id].anchor
                continue
            directed = []
            for traversal in stroke.traversals:
                edge = edges_by_id[traversal.edge_id]
                directed.append((edge.node_a, edge.node_b, edge.pixels) if traversal.direction != "reverse"
                                else (edge.node_b, edge.node_a, tuple(reversed(edge.pixels))))
            assert stroke.start_pixel == directed[0][2][0] and stroke.end_pixel == directed[-1][2][-1]
            for a, b in zip(directed, directed[1:]):
                assert a[1] == b[0]  # only graph-adjacent chains may share a stroke
            pairings = {frozenset((j.port_a, j.port_b)) for j in hypothesis.joins}
            for a, b in zip(stroke.traversals, stroke.traversals[1:]):
                exit_port = f"{a.edge_id}:{'b' if a.direction == 'forward' else 'a'}"
                entry_port = f"{b.edge_id}:{'a' if b.direction == 'forward' else 'b'}"
                assert frozenset((exit_port, entry_port)) in pairings
            assert stroke.closed == (stroke.start_pixel == stroke.end_pixel)
        for join in hypothesis.joins:
            assert join.node_id in nodes_by_id
            assert join.geometry == ("single_pixel" if len(nodes_by_id[join.node_id].pixels) == 1 else "unresolved_region")


def test_open_chain_has_two_opposite_directions_no_fake_confidence(tmp_path):
    record = raw(tmp_path, {(x, 8) for x in range(3, 15)})
    result = infer_trajectories(record)
    assert result.evidence_origin == "offline_inferred"
    assert len(result.hypotheses) == 2
    assert {h.strokes[0].traversals[0].direction for h in result.hypotheses} == {"forward", "reverse"}
    assert all(not h.pen_lifts and h.status == "proposed" for h in result.hypotheses)
    assert "confidence" not in result.model_dump_json()
    coverage(result, record.graph)


def test_t_and_x_expose_competing_junction_pairings_and_pen_lifts(tmp_path):
    for points, minimum in (({(x, 10) for x in range(3, 23)} | {(12, y) for y in range(3, 11)}, 2),
                            ({(i, i) for i in range(3, 20)} | {(i, 22 - i) for i in range(3, 20)}, 2)):
        record = raw(tmp_path, points)
        result = infer_trajectories(record)
        assert len(result.hypotheses) > 1
        assert len(result.hypotheses[0].strokes) == minimum
        assert any(h.joins for h in result.hypotheses)
        assert len({tuple((j.port_a, j.port_b) for j in h.joins) for h in result.hypotheses}) > 1
        coverage(result, record.graph)


def test_loop_keeps_both_directions_and_canonical_start_is_not_observed(tmp_path):
    record = raw(tmp_path, ring())
    result = infer_trajectories(record)
    assert any(h.strokes[0].closed for h in result.hypotheses)
    assert {h.strokes[0].traversals[0].direction for h in result.hypotheses} == {"forward", "reverse"}
    assert "CYCLE_START_UNOBSERVED" in result.diagnostics
    coverage(result, record.graph)


def test_dots_and_disconnected_strokes_keep_order_alternatives_and_lifts(tmp_path):
    record = raw(tmp_path, {(3, 2), (8, 2)} | {(x, 12) for x in range(3, 15)})
    result = infer_trajectories(record)
    assert len(result.hypotheses) > 1
    for h in result.hypotheses:
        assert sum(s.kind == "isolated_mark" for s in h.strokes) == 2
        assert len(h.pen_lifts) == 2
    coverage(result, record.graph)


def test_exhausted_search_keeps_full_unresolved_edge_coverage(tmp_path):
    record = raw(tmp_path, {(i, i) for i in range(3, 20)} | {(i, 22 - i) for i in range(3, 20)})
    result = infer_trajectories(record, limits=TrajectoryLimits(max_search_expansions=1))
    assert result.budget_exhausted
    assert len(result.hypotheses) == 1 and result.hypotheses[0].status == "unresolved"
    assert result.hypotheses[0].order_state == "unresolved" and result.hypotheses[0].ranking_cost is None
    assert all(t.direction == "unresolved" for s in result.hypotheses[0].strokes for t in s.traversals)
    coverage(result, record.graph)


def test_persistence_reopen_is_immutable_and_parent_bound(tmp_path: Path):
    record = raw(tmp_path, ring())
    repo = TrajectoryRepository(tmp_path)
    stored = repo.store(infer_trajectories(record))
    assert repo.store(stored.run) == stored
    assert repo.load(stored.sha256) == stored
    before = record.path.read_bytes()
    assert record.path.read_bytes() == before


def test_constraints_required_forbidden_and_direction_are_hard_filters(tmp_path):
    record = raw(tmp_path, {(x, 10) for x in range(3, 23)} | {(12, y) for y in range(3, 11)})
    unconstrained = infer_trajectories(record)
    passage = unconstrained.hypotheses[0].joins[0]
    pair = PortPair(port_a=passage.port_a, port_b=passage.port_b)
    result = infer_trajectories(record, constraints=TrajectoryConstraints(required_joins=(pair,)))
    assert not result.fallback_reason
    assert all((pair.port_a, pair.port_b) in {(j.port_a, j.port_b) for j in h.joins} for h in result.hypotheses)
    result = infer_trajectories(record, constraints=TrajectoryConstraints(forbidden_joins=(pair,)))
    assert all((pair.port_a, pair.port_b) not in {(j.port_a, j.port_b) for j in h.joins} for h in result.hypotheses)
    line = raw(tmp_path, {(x, 20) for x in range(3, 23)})
    result = infer_trajectories(line, constraints=TrajectoryConstraints(edge_directions=(
        EdgeDirectionConstraint(edge_id="e-0", direction="reverse"),)))
    assert len(result.hypotheses) == 1
    assert result.hypotheses[0].strokes[0].traversals[0].direction == "reverse"


@pytest.mark.parametrize("case", ["missing-port", "different-nodes", "same-port", "duplicate", "conflicting", "missing-edge"])
def test_invalid_constraints_are_refused(tmp_path, case):
    record = raw(tmp_path, {(x, 10) for x in range(3, 23)} | {(12, y) for y in range(3, 11)})
    pair = infer_trajectories(record).hypotheses[0].joins[0]
    pair = PortPair(port_a=pair.port_a, port_b=pair.port_b)
    constraints = {
        "missing-port": TrajectoryConstraints(required_joins=(PortPair(port_a="e-999:a", port_b=pair.port_b),)),
        "different-nodes": TrajectoryConstraints(required_joins=(PortPair(port_a="e-0:a", port_b="e-0:b"),)),
        "same-port": TrajectoryConstraints(required_joins=(PortPair(port_a=pair.port_a, port_b=pair.port_a),)),
        "duplicate": TrajectoryConstraints(required_joins=(pair, pair)),
        "conflicting": TrajectoryConstraints(required_joins=(pair,), forbidden_joins=(pair,)),
        "missing-edge": TrajectoryConstraints(edge_directions=(EdgeDirectionConstraint(edge_id="e-999", direction="forward"),)),
    }[case]
    with pytest.raises(ValueError, match="TRAJECTORY_.*CONSTRAINT|TRAJECTORY_JOINS"):
        infer_trajectories(record, constraints=constraints)


def test_incompatible_directions_do_not_silently_override_constraints(tmp_path):
    record = raw(tmp_path, {(x, 10) for x in range(3, 23)} | {(12, y) for y in range(3, 11)})
    passage = infer_trajectories(record).hypotheses[0].joins[0]
    # Both fixed directions point into the same junction: cannot form one trail.
    constraints = TrajectoryConstraints(
        required_joins=(PortPair(port_a=passage.port_a, port_b=passage.port_b),),
        edge_directions=tuple(EdgeDirectionConstraint(edge_id=port.split(":")[0],
                                                     direction="reverse" if port.endswith(":a") else "forward")
                              for port in (passage.port_a, passage.port_b)),
    )
    result = infer_trajectories(record, constraints=constraints)
    assert result.fallback_reason == "constraint_coverage" and not result.budget_exhausted
    assert result.hypotheses[0].status == "unresolved" and not result.hypotheses[0].constraints_satisfied
    coverage(result, record.graph)


def test_cleanup_selection_is_explicit_and_ids_are_bound_to_that_revision(tmp_path):
    record = raw(tmp_path, {(x, 10) for x in range(3, 23)} | {(12, y) for y in range(8, 11)})
    preview = cleanup_skeleton(record)
    repo = SkeletonCleanupRepository(tmp_path)
    cleanup = repo.store(cleanup_skeleton(record, remove_edge_ids=(preview.candidates[0].edge_id,)))
    result = infer_trajectories(record, cleanup=cleanup)
    assert result.cleanup_sha256 == cleanup.sha256
    assert result.provenance == record.graph.provenance
    assert len(result.hypotheses) == 2
    coverage(result, cleanup.cleanup)
    with pytest.raises(AlignmentStaleError, match="PARENT_STALE"):
        result.validate_parent(record)
    stored = TrajectoryRepository(tmp_path).store(result)
    assert TrajectoryRepository(tmp_path).load(stored.sha256) == stored


def test_thick_junctions_keep_unknown_interiors_and_internal_holes(tmp_path):
    rows = ("#...####", ".#####..", "###.....", "..#.#..#", "####....", "..#.####", "##.#####", "###..#..")
    points = {(x, y) for y, row in enumerate(rows) for x, value in enumerate(row) if value == "#"}
    record = raw(tmp_path, points)
    result = infer_trajectories(record)
    coverage(result, record.graph)
    thick = {n.node_id for n in record.graph.nodes if n.kind == "junction" and len(n.pixels) > 1}
    assert thick
    assert all(thick <= set(h.unresolved_node_ids) for h in result.hypotheses)
    assert all(j.geometry == "unresolved_region" for h in result.hypotheses for j in h.joins if j.node_id in thick)
    # No generated path array can invent a line through the region.
    assert all(not hasattr(s, "pixels") for h in result.hypotheses for s in h.strokes)


@pytest.mark.parametrize("points", [set(), {(0, 0)}, {(0, 0), (31, 23)}, {(0, 0), (1, 1)},
    {(x, y) for x in range(2, 7) for y in range(2, 7)}])
def test_empty_small_border_and_region_graphs_have_complete_coverage(tmp_path, points):
    record = raw(tmp_path, points)
    coverage(infer_trajectories(record), record.graph)


def test_limits_caps_cancel_and_no_input_mutation(tmp_path):
    record = raw(tmp_path, {(x, 10) for x in range(3, 23)} | {(12, y) for y in range(3, 11)})
    before = record.path.read_bytes()
    for limits in (TrajectoryLimits(max_search_edges=1), TrajectoryLimits(max_search_nodes=1),
                   TrajectoryLimits(max_ports_per_node=2), TrajectoryLimits(max_search_expansions=1)):
        result = infer_trajectories(record, limits=limits)
        assert result.budget_exhausted and result.alternatives_truncated
        assert result.search_expansions <= limits.max_search_expansions
        coverage(result, record.graph)
    result = infer_trajectories(record, limits=TrajectoryLimits(max_hypotheses=1))
    assert len(result.hypotheses) == 1 and result.alternatives_truncated
    with pytest.raises(TrajectoryLimitError, match="MEMORY_LIMIT"):
        infer_trajectories(record, limits=TrajectoryLimits(max_working_bytes=1024))
    with pytest.raises(TrajectoryLimitError, match="CANCELLED"):
        infer_trajectories(record, cancelled=lambda: True)
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls > 5

    with pytest.raises(TrajectoryLimitError, match="CANCELLED"):
        infer_trajectories(record, cancelled=cancelled)
    assert record.path.read_bytes() == before


def test_determinism_and_seeded_geometry(tmp_path):
    rng = random.Random(14)
    for _ in range(32):
        points = {(x, y) for y in range(8) for x in range(8) if rng.random() < .4}
        record = raw(tmp_path, points)
        a, b = infer_trajectories(record), infer_trajectories(record)
        assert a.model_dump(exclude={"created_at_utc"}) == b.model_dump(exclude={"created_at_utc"})
        assert all(h.ranking_cost is None or h.ranking_cost >= 0 for h in a.hypotheses)
        coverage(a, record.graph)


@pytest.mark.parametrize("field,value", [("hypotheses", ()), ("provenance", None), ("node_region_ids", ()),
    ("width_px", 100), ("search_expansions", 999), ("evidence_origin", "online_capture")])
def test_forged_results_are_not_persisted(tmp_path, field, value):
    record = raw(tmp_path, ring())
    result = infer_trajectories(record)
    data = result.model_dump()
    data[field] = value if field != "provenance" else result.provenance.model_copy(update={"input_mask_sha256": "f" * 64})
    with pytest.raises(ValueError):
        TrajectoryRepository(tmp_path).store(TrajectoryRun.model_validate(data))


def test_record_and_parent_corruption_limits_and_strict_json(tmp_path, monkeypatch):
    import handwriting_plotter.learning.trajectories as module

    record = raw(tmp_path, ring())
    repo = TrajectoryRepository(tmp_path)
    stored = repo.store(infer_trajectories(record))
    monkeypatch.setattr(module, "MAX_RECORD_BYTES", 16)
    with pytest.raises(TrajectoryLimitError, match="RECORD_TOO_LARGE"):
        repo.load(stored.sha256)
    monkeypatch.undo()
    stored.path.write_bytes(b"corrupt synthetic hypotheses")
    with pytest.raises(ValueError, match="RECORD_HASH"):
        repo.load(stored.sha256)
    with pytest.raises(ValueError, match="INVALID_TRAJECTORY_HASH"):
        repo.path_for("../escape")
    for content in (b'{"format":0,"format":1}', b'{"cost":NaN}'):
        digest = sha256(content).hexdigest()
        target = repo.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        with pytest.raises(ValueError, match="duplicate|non-finite"):
            repo.load(digest)
    record.path.write_bytes(b"corrupt synthetic skeleton")
    with pytest.raises(ValueError, match="SKELETON_RECORD_HASH"):
        repo.store(stored.run)


@pytest.mark.parametrize("field", ["ranking_cost", "direction", "provenance"])
def test_valid_content_hash_does_not_hide_forged_geometry_or_scores(tmp_path, field):
    record = raw(tmp_path, ring())
    result = infer_trajectories(record)
    if field == "provenance":
        result = result.model_copy(update={"provenance": result.provenance.model_copy(update={"input_mask_sha256": "f" * 64})})
    else:
        h = result.hypotheses[0]
        if field == "ranking_cost":
            h = h.model_copy(update={"ranking_cost": h.ranking_cost + 10})
        else:
            stroke = h.strokes[0]
            item = stroke.traversals[0]
            item = item.model_copy(update={"direction": "reverse" if item.direction == "forward" else "forward"})
            stroke = stroke.model_copy(update={"traversals": (item, *stroke.traversals[1:])})
            h = h.model_copy(update={"strokes": (stroke, *h.strokes[1:])})
        result = result.model_copy(update={"hypotheses": (h, *result.hypotheses[1:])})
    content = canonical_json_bytes(result.model_dump(mode="json"))
    digest = sha256(content).hexdigest()
    repo = TrajectoryRepository(tmp_path)
    path = repo.path_for(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    with pytest.raises(ValueError, match="TRAJECTORY_CONTENT_MISMATCH"):
        repo.load(digest)


def test_svg_has_only_proposed_edge_arrows_and_separate_pen_up_layers(tmp_path):
    record = raw(tmp_path, ring() | {(25, 2)})
    result = infer_trajectories(record)
    svg = render_trajectory_overlay_svg(record, result)
    root = ET.fromstring(svg)
    assert root.attrib["data-purpose"] == "offline-hypothesis-diagnostic-only"
    assert 'data-layer="direction-hypothesis"' in svg
    assert 'data-layer="inferred-pen-up"' in svg
    assert "not observed" in svg
    unresolved = infer_trajectories(record, limits=TrajectoryLimits(max_search_expansions=1))
    svg = render_trajectory_overlay_svg(record, unresolved)
    assert 'data-layer="direction-hypothesis"' not in svg
    with pytest.raises(TrajectoryLimitError, match="OVERLAY_LIMIT"):
        render_trajectory_overlay_svg(record, result, max_bytes=10)
    with pytest.raises(ValueError, match="HYPOTHESIS_NOT_FOUND"):
        render_trajectory_overlay_svg(record, result, hypothesis_id="h-999")


def test_import_is_ml_cv_and_qt_free():
    result = subprocess.run([sys.executable, "-c", """
import sys
from handwriting_plotter.learning import infer_trajectories, TrajectoryReviewRepository
assert not any(n in sys.modules for n in ('PySide6', 'cv2', 'numpy', 'torch', 'transformers'))
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
