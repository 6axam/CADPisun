"""Diagnostic directions/lifts for one offline hypothesis, never PenPlan."""

from .skeleton import SkeletonGraphRecord
from .skeleton_cleanup import SkeletonCleanupRecord
from .trajectories import TrajectoryLimitError, TrajectoryRun


def render_trajectory_overlay_svg(
    raw: SkeletonGraphRecord, run: TrajectoryRun, *, cleanup: SkeletonCleanupRecord | None = None,
    hypothesis_id: str = "h-0", max_bytes: int = 16 * 1024 * 1024,
) -> str:
    run.validate_parent(raw, cleanup)
    if type(max_bytes) is not int or not 1 <= max_bytes <= 16 * 1024 * 1024:
        raise TrajectoryLimitError("TRAJECTORY_OVERLAY_LIMIT")
    hypothesis = next((h for h in run.hypotheses if h.hypothesis_id == hypothesis_id), None)
    if hypothesis is None:
        raise ValueError("TRAJECTORY_HYPOTHESIS_NOT_FOUND")
    graph = raw.graph if cleanup is None else cleanup.cleanup
    edges = {edge.edge_id: edge for edge in graph.edges}
    rows, size = [], 0

    def append(value):
        nonlocal size
        size += len(value.encode("utf-8"))
        if size > max_bytes:
            raise TrajectoryLimitError("TRAJECTORY_OVERLAY_LIMIT")
        rows.append(value)

    append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {run.width_px} {run.height_px}" '
           'data-purpose="offline-hypothesis-diagnostic-only">')
    append(f'<title>{hypothesis_id}: {hypothesis.status}; offline_inferred — not observed pen movement</title>'
           '<desc>Blue: hypothesized direction along real chains. Orange: unresolved junction pixels. '
           'Red dashed: inferred pen-up transfer, never ink or a toolpath. Cyan: isolated marks. '
           'Gray chains without arrows: unresolved direction. Costs are heuristic, not probabilities.</desc>')
    append('<defs><marker id="direction" markerWidth="3" markerHeight="3" refX="2" refY="1.5" orient="auto" '
           'markerUnits="userSpaceOnUse"><path d="M0,0 L3,1.5 L0,3" fill="#2563eb"/></marker></defs>')
    append(f'<rect width="{run.width_px}" height="{run.height_px}" fill="white"/>')
    # Pen-up transfers are background annotations. Drawing them last obscures
    # tiny dots and can make proposed travel look like replacement source ink.
    for lift in hypothesis.pen_lifts:
        a, b = lift.from_pixel, lift.to_pixel
        append(f'<line x1="{a[0] + .5:g}" y1="{a[1] + .5:g}" x2="{b[0] + .5:g}" y2="{b[1] + .5:g}" '
               'stroke="#dc2626" stroke-width="0.25" stroke-dasharray="0.7 0.5" '
               'data-layer="inferred-pen-up"><title>Unobserved pen-up hypothesis; not ink</title></line>')
    for stroke in hypothesis.strokes:
        for traversal in stroke.traversals:
            edge = edges[traversal.edge_id]
            pixels = edge.pixels if traversal.direction != "reverse" else tuple(reversed(edge.pixels))
            points = " ".join(f"{x + .5:g},{y + .5:g}" for x, y in pixels)
            color = "#6b7280" if traversal.direction == "unresolved" else "#2563eb"
            append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="0.5" '
                   f'data-stroke="{stroke.stroke_id}" data-edge="{edge.edge_id}" data-direction="{traversal.direction}"/>')
            if traversal.direction != "unresolved":
                index = min(len(pixels) - 2, len(pixels) // 2)
                a, b = pixels[index:index + 2]
                append(f'<line x1="{a[0] + .5:g}" y1="{a[1] + .5:g}" x2="{b[0] + .5:g}" y2="{b[1] + .5:g}" '
                       'stroke="#2563eb" stroke-width="0.35" marker-end="url(#direction)" data-layer="direction-hypothesis"/>')
        if hypothesis.order_state == "hypothesized":
            append(f'<text x="{stroke.start_pixel[0] + .6:g}" y="{stroke.start_pixel[1] + .2:g}" '
                   f'font-size="1.5" fill="#111827" data-layer="order-hypothesis">{stroke.stroke_id[2:]}</text>')
    for node in graph.nodes:
        color = "#0891b2" if node.kind == "isolated" else "#d97706"
        if node.kind not in ("junction", "isolated"):
            continue
        for x, y in node.pixels:
            append(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{color}" fill-opacity="0.7" '
                   f'data-layer="node-region" data-node="{node.node_id}"><title>Node pixels retained; no interpolated interior</title></rect>')
    append('</svg>')
    return "".join(rows)
