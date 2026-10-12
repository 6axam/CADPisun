"""Emitter for the allowlisted virtual XYZ dialect."""

from __future__ import annotations

from hashlib import sha256

from handwriting_plotter.adapters.svg.writer import decimal
from handwriting_plotter.motion.planning import Barrier, Dwell, MotionCheckpoint, MotionPlan, MoveLinear, SetPen

from .base import CommandArtifact


def emit_virtual_gcode(plan: MotionPlan) -> CommandArtifact:
    if not plan.simulation_only or plan.profile_id != "virtual-cartesian-z-v1":
        raise ValueError("UNSUPPORTED_PROFILE")
    lines = ["G21", "G90", "G94"]
    mapping: list[tuple[str, int]] = []

    def emit_low(operation: MoveLinear | Dwell) -> None:
        if isinstance(operation, MoveLinear):
            if operation.mode == "actuate":
                line = f"G1 Z{decimal(operation.target.z)} F{decimal(operation.feed_mm_s * 60)}"
            else:
                line = (
                    f"G1 X{decimal(operation.target.x)} Y{decimal(operation.target.y)} "
                    f"F{decimal(operation.feed_mm_s * 60)}"
                )
        else:
            line = f"G4 P{decimal(operation.seconds)}"
        lines.append(line)
        mapping.append((operation.source_op_id, len(lines)))

    for operation in plan.operations:
        if isinstance(operation, SetPen):
            for item in operation.expansion:
                emit_low(item)
        elif isinstance(operation, MoveLinear):
            emit_low(operation)
        elif isinstance(operation, (Barrier, MotionCheckpoint)):
            continue
        else:
            raise TypeError("unknown motion operation")
    content = ("\n".join(lines) + "\n").encode("ascii")
    return CommandArtifact(
        "virtual-gcode-v1", plan.profile_id, "text/x-gcode", content, plan.page_id,
        sha256(content).hexdigest(), tuple(mapping), True,
    )

