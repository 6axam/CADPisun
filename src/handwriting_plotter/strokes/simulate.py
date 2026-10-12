"""Logical PenPlan metrics without machine assumptions."""

from __future__ import annotations

from dataclasses import dataclass

from handwriting_plotter.geometry.curves import Line, Point2
from handwriting_plotter.geometry.flatten import FlattenLimits, flatten_segment

from .compile import Draw, PenPlan, TravelTo
from .validate import validate_pen_plan


@dataclass(frozen=True, slots=True)
class LogicalSimulationReport:
    completion_state: str
    drawn_length_mm: float
    travel_length_mm: float
    pen_lifts: int
    segment_count: int
    limitations: tuple[str, ...]


def simulate_pen_plan(plan: PenPlan) -> LogicalSimulationReport:
    validation = validate_pen_plan(plan)
    if not validation.passed:
        raise ValueError("INVALID_PEN_PLAN:" + ",".join(validation.errors))
    drawn = 0.0
    travel = 0.0
    segments = 0
    position: Point2 | None = None
    for operation in plan.operations:
        if isinstance(operation, TravelTo):
            if position is not None:
                travel += position.distance_to(operation.target)
            position = operation.target
        elif isinstance(operation, Draw):
            for segment in operation.segments:
                lines, _ = flatten_segment(segment, 0.02, FlattenLimits(max_chord_length=1.0))
                drawn += sum(line.p0.distance_to(line.p1) for line in lines)
                segments += len(lines)
            position = operation.segments[-1].p1
    return LogicalSimulationReport(
        "complete",
        drawn,
        travel,
        validation.pen_lifts,
        segments,
        ("logical geometry only; no backlash, pressure, missed-step or device timing model",),
    )

