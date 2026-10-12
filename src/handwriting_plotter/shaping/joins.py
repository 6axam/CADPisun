"""Direct cubic join construction with deterministic lifted fallback."""

from __future__ import annotations

import math
from dataclasses import dataclass

from handwriting_plotter.geometry.curves import Cubic, Point2, Stroke
from handwriting_plotter.text.breaks import script_of

from .placement import PlacedGlyph


@dataclass(frozen=True, slots=True)
class RejectedJoin:
    reason: str


def _angle(a: Point2, b: Point2) -> float:
    dot = max(-1.0, min(1.0, a.x * b.x + a.y * b.y))
    return math.degrees(math.acos(dot))


def connect(left: PlacedGlyph, right: PlacedGlyph) -> Stroke | RejectedJoin:
    if left.join_mode != "single_body_deferred_marks" or right.join_mode != "single_body_deferred_marks":
        return RejectedJoin("JOIN_MODE_NONE")
    if left.exit is None or right.entry is None:
        return RejectedJoin("MISSING_ANCHOR")
    if script_of(left.match.key) != script_of(right.match.key) or script_of(left.match.key) not in {"Latin", "Cyrillic"}:
        return RejectedJoin("SCRIPT_BOUNDARY")
    if not left.match.key[-1].isalpha() or not right.match.key[0].isalpha():
        return RejectedJoin("PUNCTUATION_BOUNDARY")
    if right.entry.class_id not in left.exit.allowed_partner_classes:
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
    return Stroke(
        f"join:{left.match.occurrence_id}:{right.match.occurrence_id}",
        (Cubic(left.exit.point, c1, c2, right.entry.point),),
        tuple(item.id for item in (*left.match.graphemes, *right.match.graphemes)),
        "connector",
        "authored",
    )

