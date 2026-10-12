"""Independent restricted parser and modal interpreter for virtual G-code."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from handwriting_plotter.motion.planning import Dwell, MoveLinear, MotionPlan, Point3, expanded_operations
from handwriting_plotter.motion.profiles import MachineProfile


_NUMBER = r"-?(?:\d+(?:\.\d*)?|\.\d+)"
_G1 = re.compile(rf"^G1(?: ([XYZF])({_NUMBER})){{2,3}}$")
_G4 = re.compile(rf"^G4 P({_NUMBER})$")


@dataclass(frozen=True, slots=True)
class DecodedProgram:
    moves: tuple[MoveLinear, ...]
    dwells: tuple[Dwell, ...]
    final_position: Point3


def decode_virtual_gcode(content: bytes, profile: MachineProfile) -> DecodedProgram:
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("NON_ASCII_GCODE") from error
    if any(ord(char) < 32 and char not in "\n" for char in text):
        raise ValueError("CONTROL_CHARACTER")
    lines = text.splitlines()
    if lines[:3] != ["G21", "G90", "G94"]:
        raise ValueError("INVALID_PREAMBLE")
    position = Point3(*profile.initial_position_mm)
    moves: list[MoveLinear] = []
    dwells: list[Dwell] = []
    for line_number, line in enumerate(lines[3:], start=4):
        dwell_match = _G4.fullmatch(line)
        if dwell_match:
            seconds = float(dwell_match.group(1))
            if seconds < 0 or not math.isfinite(seconds):
                raise ValueError("INVALID_DWELL")
            dwells.append(Dwell(seconds, f"line-{line_number}"))
            continue
        if not _G1.fullmatch(line):
            raise ValueError(f"UNSUPPORTED_GCODE:{line_number}")
        words = line.split()[1:]
        values: dict[str, float] = {}
        for word in words:
            letter, value = word[0], float(word[1:])
            if letter in values or not math.isfinite(value):
                raise ValueError("INVALID_GCODE_WORD")
            values[letter] = value
        if "F" not in values or values["F"] <= 0:
            raise ValueError("MISSING_FEED")
        has_xy = "X" in values or "Y" in values
        has_z = "Z" in values
        if has_xy == has_z or (has_xy and not {"X", "Y"}.issubset(values)):
            raise ValueError("MIXED_OR_INCOMPLETE_AXES")
        target = Point3(values.get("X", position.x), values.get("Y", position.y), values.get("Z", position.z))
        for axis, value in zip(("X", "Y", "Z"), (target.x, target.y, target.z), strict=True):
            limits = profile.axes[axis]
            if not limits.minimum <= value <= limits.maximum:
                raise ValueError(f"MOVE_OUT_OF_BOUNDS:{axis}")
        mode = "actuate" if has_z else ("draw" if target.z == profile.pen.down_z_mm else "travel")
        moves.append(MoveLinear(target, values["F"] / 60, mode, f"line-{line_number}"))
        position = target
    return DecodedProgram(tuple(moves), tuple(dwells), position)


def compare_decoded(plan: MotionPlan, decoded: DecodedProgram, tolerance: float = 0.00051) -> tuple[str, ...]:
    expected_moves = [item for item in expanded_operations(plan) if isinstance(item, MoveLinear)]
    expected_dwells = [item for item in expanded_operations(plan) if isinstance(item, Dwell)]
    errors: list[str] = []
    if len(expected_moves) != len(decoded.moves):
        errors.append("MOVE_COUNT_MISMATCH")
    if len(expected_dwells) != len(decoded.dwells):
        errors.append("DWELL_COUNT_MISMATCH")
    for expected, actual in zip(expected_moves, decoded.moves, strict=False):
        if math.dist((expected.target.x, expected.target.y, expected.target.z), (actual.target.x, actual.target.y, actual.target.z)) > tolerance:
            errors.append("MOVE_GEOMETRY_MISMATCH")
        if abs(expected.feed_mm_s - actual.feed_mm_s) > tolerance:
            errors.append("FEED_MISMATCH")
    for expected, actual in zip(expected_dwells, decoded.dwells, strict=False):
        if abs(expected.seconds - actual.seconds) > tolerance:
            errors.append("DWELL_MISMATCH")
    return tuple(errors)

