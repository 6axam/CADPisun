"""Direct cubic join construction with deterministic lifted fallback."""

from __future__ import annotations

import math
from dataclasses import dataclass

from handwriting_plotter.geometry.curves import Cubic, Point2, Stroke
from handwriting_plotter.geometry.collision import point_segment_distance
from handwriting_plotter.geometry.flatten import FlattenLimits, flatten_segment
from handwriting_plotter.text.breaks import script_of

from .placement import PlacedGlyph


@dataclass(frozen=True, slots=True)
class RejectedJoin:
    reason: str


def _angle(a: Point2, b: Point2) -> float:
    dot = max(-1.0, min(1.0, a.x * b.x + a.y * b.y))
    return math.degrees(math.acos(dot))


def _clearance_ok(
    connector: Cubic,
    left: PlacedGlyph,
    right: PlacedGlyph,
    pen_width_mm: float,
) -> bool:
    connector_lines, _ = flatten_segment(connector, 0.01, FlattenLimits(max_chord_length=0.25))
    obstacles = []
    for glyph, adjacent_id, adjacent_end in (
        (left, left.body_stroke_id, "end"),
        (right, right.body_stroke_id, "start"),
    ):
        for stroke in glyph.strokes:
            for segment_index, segment in enumerate(stroke.segments):
                if stroke.id == adjacent_id:
                    if adjacent_end == "end" and segment_index == len(stroke.segments) - 1:
                        continue
                    if adjacent_end == "start" and segment_index == 0:
                        continue
                lines, _ = flatten_segment(segment, 0.01, FlattenLimits(max_chord_length=0.25))
                obstacles.extend(lines)
    clearance = pen_width_mm + 0.05 + 0.02
    for line in connector_lines:
        midpoint = line.p0.lerp(line.p1, 0.5)
        if any(point_segment_distance(midpoint, obstacle) < clearance for obstacle in obstacles):
            return False
    return True


def connect(
    left: PlacedGlyph,
    right: PlacedGlyph,
    *,
    pen_width_mm: float = 0.35,
) -> Stroke | RejectedJoin:
    if left.join_mode != "single_body_deferred_marks" or right.join_mode != "single_body_deferred_marks":
        return RejectedJoin("JOIN_MODE_NONE")
    if left.no_join_after or right.no_join_before:
        return RejectedJoin("JOIN_FORBIDDEN")
    if left.exit is None or right.entry is None:
        return RejectedJoin("MISSING_ANCHOR")
    if script_of(left.match.key) != script_of(right.match.key) or script_of(left.match.key) not in {"Latin", "Cyrillic"}:
        return RejectedJoin("SCRIPT_BOUNDARY")
    if not left.match.key[-1].isalpha() or not right.match.key[0].isalpha():
        return RejectedJoin("PUNCTUATION_BOUNDARY")
    if (
        right.entry.class_id not in left.exit.allowed_partner_classes
        or left.exit.class_id not in right.entry.allowed_partner_classes
    ):
        return RejectedJoin("ANCHOR_CLASS_DENIED")
    vector = Point2(right.entry.point.x - left.exit.point.x, right.entry.point.y - left.exit.point.y)
    distance = math.hypot(vector.x, vector.y)
    if distance == 0:
        return RejectedJoin("COINCIDENT_ANCHORS")
    if distance > min(left.exit.max_gap_mm, right.entry.max_gap_mm):
        return RejectedJoin("GAP_TOO_LARGE")
    if abs(vector.y) > min(left.exit.max_vertical_delta_mm, right.entry.max_vertical_delta_mm):
        return RejectedJoin("VERTICAL_DELTA")
    direction = Point2(vector.x / distance, vector.y / distance)
    max_left = min(60.0, left.exit.max_angle_deg)
    max_right = min(60.0, right.entry.max_angle_deg)
    if _angle(left.exit.tangent, direction) > max_left or _angle(right.entry.tangent, direction) > max_right:
        return RejectedJoin("TANGENT_MISMATCH")
    c1 = Point2(
        left.exit.point.x + left.exit.tangent.x * distance / 3,
        left.exit.point.y + left.exit.tangent.y * distance / 3,
    )
    c2 = Point2(
        right.entry.point.x - right.entry.tangent.x * distance / 3,
        right.entry.point.y - right.entry.tangent.y * distance / 3,
    )
    if min(c1.x, c2.x, right.entry.point.x) < left.exit.point.x - 1e-9:
        return RejectedJoin("BACKWARD_X")
    connector = Cubic(left.exit.point, c1, c2, right.entry.point)
    if not _clearance_ok(connector, left, right, pen_width_mm):
        return RejectedJoin("CLEARANCE_COLLISION")
    return Stroke(
        f"join:{left.match.occurrence_id}:{right.match.occurrence_id}",
        (connector,),
        tuple(item.id for item in (*left.match.graphemes, *right.match.graphemes)),
        "connector",
        "authored",
    )

