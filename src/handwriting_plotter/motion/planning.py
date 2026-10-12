"""PenPlan to bounded, quantized virtual XYZ MotionPlan."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Literal, TypeAlias

from handwriting_plotter.geometry.curves import Point2
from handwriting_plotter.geometry.flatten import FlattenLimits, flatten_segment
from handwriting_plotter.geometry.transforms import transform_segment
from handwriting_plotter.strokes.compile import Checkpoint as PenCheckpoint
from handwriting_plotter.strokes.compile import Draw, EnsurePenUp, PenDown, PenPlan, PenUp, TravelTo
from handwriting_plotter.strokes.validate import validate_pen_plan

from .profiles import MachineProfile
from .registration import Registration


@dataclass(frozen=True, slots=True)
class Point3:
    x: float
    y: float
    z: float


@dataclass(frozen=True, slots=True)
class MoveLinear:
    target: Point3
    feed_mm_s: float
    mode: Literal["travel", "draw", "actuate"]
    source_op_id: str


@dataclass(frozen=True, slots=True)
class Dwell:
    seconds: float
    source_op_id: str


LowLevel: TypeAlias = MoveLinear | Dwell


@dataclass(frozen=True, slots=True)
class SetPen:
    target_state: Literal["UP", "DOWN"]
    actuator_kind: Literal["z_axis"]
    expansion: tuple[LowLevel, ...]
    settle_s: float
    synchronization_evidence_ref: str
    source_op_id: str


@dataclass(frozen=True, slots=True)
class Barrier:
    source_op_id: str


@dataclass(frozen=True, slots=True)
class MotionCheckpoint:
    scope: Literal["word", "page"]
    source_op_id: str


MotionOperation: TypeAlias = MoveLinear | SetPen | Barrier | MotionCheckpoint


@dataclass(frozen=True, slots=True)
class ApproximationSummary:
    tolerance_mm: float
    quantization_mm: float
    segment_count: int
    max_deviation_mm: float


@dataclass(frozen=True, slots=True)
class MotionPlan:
    format: Literal["hp-motion-plan"]
    schema_version: Literal["1.0"]
    page_id: str
    profile_id: str
    profile_revision_hash: str
    registration_hash: str
    start_position: Point3
    start_pen_state: Literal["UP"]
    operations: tuple[MotionOperation, ...]
    bounds_all_moves: tuple[Point3, Point3]
    approximation_report: ApproximationSummary
    lower_bound_time_s: float
    end_position: Point3
    end_pen_state: Literal["UP"]
    simulation_only: Literal[True]


def _quantize(value: float, quantum: float) -> float:
    result = Decimal(str(value)).quantize(Decimal(str(quantum)), rounding=ROUND_HALF_EVEN)
    value = float(result)
    return 0.0 if value == 0 else value


def _validate_point(point: Point3, profile: MachineProfile) -> None:
    for axis, value in zip(("X", "Y", "Z"), (point.x, point.y, point.z), strict=True):
        limits = profile.axes[axis]
        if not limits.minimum <= value <= limits.maximum:
            raise ValueError(f"MOTION_OUT_OF_BOUNDS:{axis}:{value}")


def expanded_operations(plan: MotionPlan) -> tuple[LowLevel | Barrier | MotionCheckpoint, ...]:
    output: list[LowLevel | Barrier | MotionCheckpoint] = []
    for operation in plan.operations:
        if isinstance(operation, SetPen):
            output.extend(operation.expansion)
        else:
            output.append(operation)
    return tuple(output)


def plan_virtual_page(plan: PenPlan, profile: MachineProfile, registration: Registration) -> MotionPlan:
    validation = validate_pen_plan(plan)
    if not validation.passed:
        raise ValueError("INVALID_PEN_PLAN")
    if not profile.simulation_only or profile.profile_id != "virtual-cartesian-z-v1":
        raise ValueError("UNSUPPORTED_MACHINE_PROFILE")
    if registration.page_id != plan.page_id or registration.profile_revision_hash != profile.revision_hash:
        raise ValueError("PROFILE_OR_REGISTRATION_MISMATCH")
    q = profile.quantization_mm
    initial = Point3(*profile.initial_position_mm)
    _validate_point(initial, profile)
    position = initial
    pen_state = "UP"
    operations: list[MotionOperation] = []
    all_points = [initial]
    segment_count = 0
    time_s = 0.0

    def move(target: Point3, feed: float, mode: Literal["travel", "draw", "actuate"], source: str) -> MoveLinear:
        nonlocal position, time_s
        _validate_point(target, profile)
        distance = math.dist((position.x, position.y, position.z), (target.x, target.y, target.z))
        time_s += distance / feed
        position = target
        all_points.append(target)
        return MoveLinear(target, feed, mode, source)

    for operation in plan.operations:
        if isinstance(operation, EnsurePenUp):
            if pen_state != "UP":
                raise ValueError("UNKNOWN_INITIAL_PEN_STATE")
        elif isinstance(operation, TravelTo):
            if pen_state != "UP":
                raise ValueError("TRAVEL_WITH_PEN_DOWN")
            point = registration.page_to_work.apply(operation.target)
            target = Point3(_quantize(point.x, q), _quantize(point.y, q), position.z)
            operations.append(move(target, profile.feeds.travel_mm_s, "travel", operation.op_id))
        elif isinstance(operation, PenDown):
            target = Point3(position.x, position.y, profile.pen.down_z_mm)
            expansion_move = move(target, profile.feeds.actuate_mm_s, "actuate", operation.op_id)
            dwell = Dwell(profile.pen.settle_down_s, operation.op_id)
            time_s += dwell.seconds
            operations.append(SetPen("DOWN", "z_axis", (expansion_move, dwell), dwell.seconds, "virtual-sequential-v1", operation.op_id))
            pen_state = "DOWN"
        elif isinstance(operation, Draw):
            if pen_state != "DOWN":
                raise ValueError("DRAW_WITH_PEN_UP")
            emitted = 0
            for segment in operation.segments:
                transformed = transform_segment(segment, registration.page_to_work)
                lines, _ = flatten_segment(
                    transformed,
                    profile.flatten_tolerance_mm,
                    FlattenLimits(max_depth=24, max_segments=profile.max_segments, max_chord_length=1.0),
                )
                for line in lines:
                    target = Point3(_quantize(line.p1.x, q), _quantize(line.p1.y, q), profile.pen.down_z_mm)
                    if target == position:
                        continue
                    operations.append(move(target, profile.feeds.draw_mm_s, "draw", operation.op_id))
                    emitted += 1
                    segment_count += 1
                    if segment_count > profile.max_segments:
                        raise ValueError("GEOMETRY_BUDGET_EXCEEDED")
            if emitted == 0:
                raise ValueError("RESOLUTION_INSUFFICIENT")
        elif isinstance(operation, PenUp):
            target = Point3(position.x, position.y, profile.pen.up_z_mm)
            expansion_move = move(target, profile.feeds.actuate_mm_s, "actuate", operation.op_id)
            dwell = Dwell(profile.pen.settle_up_s, operation.op_id)
            time_s += dwell.seconds
            operations.append(SetPen("UP", "z_axis", (expansion_move, dwell), dwell.seconds, "virtual-sequential-v1", operation.op_id))
            pen_state = "UP"
        elif isinstance(operation, PenCheckpoint):
            if pen_state != "UP":
                raise ValueError("CHECKPOINT_WITH_PEN_DOWN")
            operations.append(MotionCheckpoint(operation.scope, operation.op_id))
    if pen_state != "UP":
        raise ValueError("FINAL_PEN_NOT_UP")
    operations.append(Barrier("eof"))
    low = Point3(min(p.x for p in all_points), min(p.y for p in all_points), min(p.z for p in all_points))
    high = Point3(max(p.x for p in all_points), max(p.y for p in all_points), max(p.z for p in all_points))
    deviation = profile.flatten_tolerance_mm + math.sqrt(2) * q / 2 + 0.002
    if deviation > 0.05:
        raise ValueError("ACCURACY_BUDGET_EXCEEDED")
    return MotionPlan(
        "hp-motion-plan", "1.0", plan.page_id, profile.profile_id, profile.revision_hash,
        registration.registration_hash, initial, "UP", tuple(operations), (low, high),
        ApproximationSummary(profile.flatten_tolerance_mm, q, segment_count, deviation),
        time_s, position, "UP", True,
    )

