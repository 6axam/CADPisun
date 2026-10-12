"""Strict machine-profile boundary; only the synthetic profile ships in MVP."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from handwriting_plotter.domain.models import StrictModel, canonical_hash, canonical_json_bytes, strict_json_loads


class AxisRange(StrictModel):
    minimum: float
    maximum: float


class FeedLimits(StrictModel):
    draw_mm_s: float = Field(gt=0)
    travel_mm_s: float = Field(gt=0)
    actuate_mm_s: float = Field(gt=0)


class PenConfig(StrictModel):
    actuator_kind: Literal["z_axis"]
    up_z_mm: float
    down_z_mm: float
    settle_up_s: float = Field(ge=0)
    settle_down_s: float = Field(ge=0)


class MachineProfile(StrictModel):
    format: Literal["hp-machine-profile"]
    schema_version: Literal["1.0"]
    profile_id: Literal["virtual-cartesian-z-v1"]
    revision: str
    simulation_only: Literal[True]
    dialect_id: Literal["virtual-gcode-v1"]
    transport_kind: Literal["none"]
    kinematics_kind: Literal["cartesian"]
    axes: dict[str, AxisRange]
    page_height_mm: float
    page_y_reflected: Literal[True]
    initial_position_mm: tuple[float, float, float]
    initial_pen_state: Literal["UP"]
    pen: PenConfig
    feeds: FeedLimits
    nominal_acceleration_mm_s2: float = Field(gt=0)
    pen_width_mm: float = Field(gt=0)
    flatten_tolerance_mm: float = Field(gt=0, le=0.02)
    quantization_mm: float = Field(gt=0, le=0.001)
    max_segments: int = Field(gt=0, le=2_000_000)

    @property
    def revision_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


def load_profile(path: Path) -> MachineProfile:
    data = strict_json_loads(path.read_bytes())
    return MachineProfile.model_validate_json(canonical_json_bytes(data), strict=True)

