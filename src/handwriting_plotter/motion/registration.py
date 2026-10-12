"""Explicit page registration for the virtual Cartesian work frame."""

from __future__ import annotations

from dataclasses import dataclass

from handwriting_plotter.domain.models import canonical_hash
from handwriting_plotter.geometry.transforms import Affine2

from .profiles import MachineProfile


@dataclass(frozen=True, slots=True)
class Registration:
    page_id: str
    profile_revision_hash: str
    page_to_work: Affine2
    work_coordinate_system_id: str
    calibration_id: str

    @property
    def registration_hash(self) -> str:
        return canonical_hash({
            "page_id": self.page_id,
            "profile_revision_hash": self.profile_revision_hash,
            "affine": self.page_to_work.__dict__ if hasattr(self.page_to_work, "__dict__") else {
                field: getattr(self.page_to_work, field)
                for field in ("a", "b", "c", "d", "tx", "ty", "from_frame", "to_frame")
            },
            "work_coordinate_system_id": self.work_coordinate_system_id,
            "calibration_id": self.calibration_id,
        })


def virtual_registration(page_id: str, profile: MachineProfile) -> Registration:
    transform = Affine2(1, 0, 0, -1, 0, profile.page_height_mm, "PageFrame", "WorkFrame")
    return Registration(page_id, profile.revision_hash, transform, "virtual-work", "nominal-page-map-v1")

