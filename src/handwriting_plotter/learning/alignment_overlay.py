"""Diagnostic-only SVG for TASK 12A/12B hypotheses; never a pen or G-code plan."""

from __future__ import annotations

import base64
from hashlib import sha256
from html import escape

from .grapheme_alignment import GraphemeAlignment, InkBounds
from .word_alignment import AlignmentStaleError, WordAlignmentRecord


def render_alignment_overlay_svg(
    *, alignment: GraphemeAlignment, words: WordAlignmentRecord, crop_png: bytes,
    hypothesis_id: str | None = None,
) -> str:
    """Embed the exact original PNG plus selectable hypotheses and a text ledger.

    Orange boxes are shared groups; cyan boxes associate one grapheme (still
    ambiguous). Red numbered entries have no assigned geometry. No line cuts
    are drawn through ink, and labels are placed in a separate ledger.
    """
    alignment = GraphemeAlignment.model_validate(alignment.model_dump())
    alignment.validate_parent(words)
    if sha256(crop_png).hexdigest() != alignment.crop_sha256:
        raise AlignmentStaleError("OVERLAY_CROP_HASH_MISMATCH")
    if not crop_png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("OVERLAY_REQUIRES_PNG")
    hypothesis = next((item for item in alignment.hypotheses
                       if item.hypothesis_id == (hypothesis_id or alignment.hypotheses[0].hypothesis_id)), None)
    if hypothesis is None:
        raise ValueError("OVERLAY_HYPOTHESIS_NOT_FOUND")
    word_alt = next(item for item in words.alignment.alternatives if item.alternative_id == hypothesis.word_alternative_id)
    tokens = {token.grapheme_id: token for token in alignment.tokens}
    candidates = {item.candidate_id: item for item in words.alignment.geometry_candidates}
    width, height = alignment.width_px, alignment.height_px
    # Scale the image for inspection without changing any crop coordinates.
    scale = min(32.0, max(1.0, 800.0 / width))
    canvas_width = max(860, round(width * scale) + 24)
    image_height = height * scale
    legend_y = int(image_height) + 94
    canvas_height = legend_y + 24 * (len(hypothesis.groups) + len(word_alt.assignments) + 4)
    rows = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}" height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        '<text x="12" y="22" font-family="sans-serif" font-size="15">DIAGNOSTIC ALIGNMENT — ambiguous hypotheses; no stroke paths</text>',
        f'<text x="12" y="42" font-family="sans-serif" font-size="12">{escape(hypothesis.hypothesis_id)} / {escape(hypothesis.word_alternative_id)}; heuristic cost {hypothesis.ranking_cost:.4f}; coarse={hypothesis.coarse}; budget exhausted={alignment.budget_exhausted}</text>',
        f'<g transform="translate(12 58) scale({scale})">',
        f'<image width="{width}" height="{height}" href="data:image/png;base64,{base64.b64encode(crop_png).decode("ascii")}"/>',
    ]

    def box(bounds: InkBounds, *, color: str, label: str, dashed: bool = False) -> None:
        dash = ' stroke-dasharray="4 2"' if dashed else ''
        rows.append(
            f'<rect x="{bounds.left_px}" y="{bounds.top_px}" width="{bounds.right_px - bounds.left_px}" '
            f'height="{bounds.bottom_px - bounds.top_px}" fill="none" stroke="{color}" stroke-width="1.5" '
            f'vector-effect="non-scaling-stroke"{dash}><title>{escape(label)}</title></rect>'
        )

    for assignment in word_alt.assignments:
        for identity in assignment.geometry_candidate_ids:
            candidate = candidates[identity]
            box(InkBounds(left_px=candidate.left_px, top_px=candidate.top_px,
                          right_px=candidate.right_px, bottom_px=candidate.bottom_px),
                color="#168a3e", label=f"word span {assignment.span_id}; {assignment.state}", dashed=True)
    for index, group in enumerate(hypothesis.groups, 1):
        if group.bounds is not None:
            text = "".join(tokens[identity].text for identity in group.grapheme_ids)
            box(group.bounds, color="#ad4e00" if len(group.grapheme_ids) > 1 else "#007a9e",
                label=f"group {index}: {text}; {group.relation}; {len(group.unresolved_joins)} unresolved joins")
    rows.append('</g>')

    def ledger(message: str, color: str = "#202124") -> None:
        nonlocal legend_y
        rows.append(f'<text x="12" y="{legend_y}" fill="{color}" font-family="sans-serif" font-size="13" xml:space="preserve">{escape(message)}</text>')
        legend_y += 24

    ledger("Green dashed: words. Orange: shared ink. Cyan: single-grapheme candidate. Red: unresolved geometry.")
    for span in words.alignment.spans:
        ledger(f"{span.span_id} [{span.start}:{span.end}] {span.kind}: {span.text!r}", "#168a3e")
    for index, group in enumerate(hypothesis.groups, 1):
        text = "".join(tokens[identity].text for identity in group.grapheme_ids)
        offsets = ",".join(f"{tokens[identity].start}:{tokens[identity].end}" for identity in group.grapheme_ids)
        ledger(f"{index}. [{offsets}] {text!r}: {group.state}, {group.relation}; unresolved joins={len(group.unresolved_joins)}",
               "#ac162c" if group.state == "unresolved" else "#202124")
    ledger(f"Unassigned ink components retained: {', '.join(hypothesis.unassigned_component_ids) or 'none'}")
    rows.append('</svg>')
    return "\n".join(rows)
