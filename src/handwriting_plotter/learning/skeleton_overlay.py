"""Bounded SVG diagnostics; never a toolpath or an export to a plotter."""

from __future__ import annotations

from html import escape

from .skeleton import SkeletonGraphRecord, SkeletonLimitError
from .skeleton_cleanup import SkeletonCleanup, _verify_raw
from .word_alignment import BinaryInkMask


def render_skeleton_overlay_svg(
    raw: SkeletonGraphRecord, *, cleanup: SkeletonCleanup | None = None,
    input_mask: BinaryInkMask | None = None, max_bytes: int = 16 * 1024 * 1024,
) -> str:
    """Pixel-aligned layers with titles, IDs, regions, loops and ambiguity.

    Gray: input/raw ink; blue: retained chains; orange: compact junctions and
    ambiguous candidates; green: endpoints; cyan: isolated marks; purple:
    cycle anchors/closed edges; red: explicitly removed raw pixels.
    Coordinates stay in the crop frame; translation is metadata, not baked in.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= 16 * 1024 * 1024:
        raise SkeletonLimitError("SKELETON_OVERLAY_LIMIT")
    _verify_raw(raw)
    graph = raw.graph
    if cleanup is not None:
        cleanup.validate_raw(raw)
    if input_mask is not None:
        graph.validate_input(input_mask)
    parts: list[str] = []
    size = 0

    def append(value: str) -> None:
        nonlocal size
        size += len(value.encode("utf-8"))
        if size > max_bytes:
            raise SkeletonLimitError("SKELETON_OVERLAY_LIMIT")
        parts.append(value)

    append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {graph.width_px} {graph.height_px}" '
           f'width="{graph.width_px}" height="{graph.height_px}" data-purpose="diagnostic-only">')
    append('<title>Skeleton diagnostic — no pen order</title><desc>'
           'Gray ink; blue retained chains; orange junction regions and ambiguous short branches; '
           'green endpoints; cyan isolated marks; purple loops; red explicitly removed pixels. '
           'Geometric ambiguity is not confidence. No stroke direction or plotter output.</desc>')
    append(f'<metadata>raw-sha256={raw.sha256}; coordinate-system={graph.coordinate_system}; '
           f'frame={escape(graph.provenance.frame_id or "synthetic")}; '
           f'offset={graph.provenance.crop_left_px},{graph.provenance.crop_top_px}</metadata>')
    append(f'<rect width="{graph.width_px}" height="{graph.height_px}" fill="white"/>')
    pixels = graph.raw_pixels if input_mask is None else (
        (index % graph.width_px, index // graph.width_px) for index, value in enumerate(input_mask.foreground) if value
    )
    append('<g fill="#d1d5db" shape-rendering="crispEdges">')
    for x, y in pixels:
        append(f'<rect x="{x}" y="{y}" width="1" height="1" data-layer="ink"/>')
    append('</g>')
    nodes = graph.nodes if cleanup is None else cleanup.nodes
    edges = graph.edges if cleanup is None else cleanup.edges
    for edge in edges:
        points = " ".join(f"{x + .5:g},{y + .5:g}" for x, y in edge.pixels)
        color = "#7c3aed" if edge.closed else "#2563eb"
        append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="0.55" '
               f'data-layer="edge" data-id="{edge.edge_id}" data-component="{edge.component_id}">'
               f'<title>{edge.edge_id}: undirected; closed={str(edge.closed).lower()}</title></polyline>')
    colors = {"endpoint": "#15803d", "junction": "#d97706", "isolated": "#0891b2", "cycle_anchor": "#7c3aed"}
    for node in nodes:
        append(f'<g fill="{colors[node.kind]}" fill-opacity="0.8" data-layer="node" '
               f'data-kind="{node.kind}" data-id="{node.node_id}" data-component="{node.component_id}">'
               f'<title>{node.node_id}: {node.kind}; internal holes={node.internal_holes}; '
               'junction structure is ambiguous</title>')
        for x, y in node.pixels:
            append(f'<rect x="{x}" y="{y}" width="1" height="1"/>')
        append('</g>')
    if cleanup is not None:
        for candidate in cleanup.candidates:
            # Raw IDs deliberately differ from re-canonicalized derived IDs.
            edge = graph.edges[int(candidate.edge_id[2:])]
            points = " ".join(f"{x + .5:g},{y + .5:g}" for x, y in edge.pixels)
            append(f'<polyline points="{points}" fill="none" stroke="#d97706" stroke-width="0.35" '
                   f'stroke-dasharray="0.6 0.5" data-layer="ambiguous-candidate" data-raw-edge="{candidate.edge_id}">'
                   '<title>Ambiguous short branch: real mark or spur; explicit selection required</title></polyline>')
        for x, y in cleanup.removed_pixels:
            append(f'<rect x="{x}" y="{y}" width="1" height="1" fill="#dc2626" '
                   'fill-opacity="0.85" data-layer="removed-pixel"><title>Explicitly removed; raw ink retained</title></rect>')
    append('</svg>')
    return "".join(parts)
