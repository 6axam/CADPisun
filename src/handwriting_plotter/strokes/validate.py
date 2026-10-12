"""Finite-state validation of logical pen plans."""

from __future__ import annotations

from dataclasses import dataclass

from .compile import Checkpoint, Draw, EnsurePenUp, PenDown, PenPlan, PenUp, TravelTo


@dataclass(frozen=True, slots=True)
class PenPlanValidation:
    passed: bool
    errors: tuple[str, ...]
    draw_count: int
    pen_lifts: int


def validate_pen_plan(plan: PenPlan) -> PenPlanValidation:
    errors: list[str] = []
    state = "UNKNOWN"
    position = None
    draws = 0
    lifts = 0
    seen_ids: set[str] = set()
    for operation in plan.operations:
        if operation.op_id in seen_ids:
            errors.append("DUPLICATE_OP_ID")
        seen_ids.add(operation.op_id)
        if isinstance(operation, EnsurePenUp):
            state = "UP"
        elif isinstance(operation, TravelTo):
            if state != "UP":
                errors.append("TRAVEL_WITH_PEN_DOWN")
            position = operation.target
        elif isinstance(operation, PenDown):
            if state != "UP" or position is None:
                errors.append("INVALID_PEN_DOWN")
            state = "DOWN"
        elif isinstance(operation, Draw):
            draws += 1
            if state != "DOWN" or position is None:
                errors.append("DRAW_WITH_PEN_UP")
            elif operation.segments[0].p0 != position:
                errors.append("DRAW_START_MISMATCH")
            for previous, current in zip(operation.segments, operation.segments[1:], strict=False):
                if previous.p1 != current.p0:
                    errors.append("DISCONTINUOUS_DRAW")
            position = operation.segments[-1].p1
        elif isinstance(operation, PenUp):
            if state != "DOWN":
                errors.append("REDUNDANT_PEN_UP")
            else:
                lifts += 1
            state = "UP"
        elif isinstance(operation, Checkpoint):
            if state != "UP":
                errors.append("CHECKPOINT_WITH_PEN_DOWN")
    if not plan.operations or not isinstance(plan.operations[0], EnsurePenUp):
        errors.append("MISSING_INITIAL_ENSURE_UP")
    if state != "UP":
        errors.append("FINAL_PEN_NOT_UP")
    if not plan.operations or not isinstance(plan.operations[-1], Checkpoint) or plan.operations[-1].scope != "page":
        errors.append("MISSING_PAGE_CHECKPOINT")
    return PenPlanValidation(not errors, tuple(errors), draws, lifts)

