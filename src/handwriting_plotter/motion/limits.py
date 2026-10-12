"""Independent expanded-plan bounds validation."""

from __future__ import annotations

from .planning import MoveLinear, MotionPlan, expanded_operations
from .profiles import MachineProfile


def validate_motion_limits(plan: MotionPlan, profile: MachineProfile) -> tuple[str, ...]:
    errors: list[str] = []
    if plan.profile_revision_hash != profile.revision_hash:
        errors.append("PROFILE_HASH_MISMATCH")
    for operation in expanded_operations(plan):
        if isinstance(operation, MoveLinear):
            for axis, value in zip(("X", "Y", "Z"), (operation.target.x, operation.target.y, operation.target.z), strict=True):
                limits = profile.axes[axis]
                if not limits.minimum <= value <= limits.maximum:
                    errors.append(f"MOVE_OUT_OF_BOUNDS:{axis}")
    return tuple(errors)

