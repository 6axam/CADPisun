"""Qt-free contracts and persistence orchestration for planar page correction."""

from __future__ import annotations

import math
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, Protocol

from pydantic import Field, model_validator

from handwriting_plotter.domain.models import StrictModel

from .models import (
    ConfidenceValue,
    ImageTransform,
    NotebookPhoto,
    PhotoRegion,
    PixelFrame,
    PixelPoint,
)
from .repository import PhotoRecord, PhotoRepository

Matrix3 = tuple[float, float, float, float, float, float, float, float, float]


class PageCorners(StrictModel):
    """Clockwise page corners in top-left, top-right, bottom-right, bottom-left order."""

    frame_id: str = Field(min_length=1, max_length=128)
    top_left: PixelPoint
    top_right: PixelPoint
    bottom_right: PixelPoint
    bottom_left: PixelPoint

    @property
    def points(self) -> tuple[PixelPoint, PixelPoint, PixelPoint, PixelPoint]:
        return (self.top_left, self.top_right, self.bottom_right, self.bottom_left)

    @model_validator(mode="after")
    def is_convex_clockwise_screen_polygon(self) -> PageCorners:
        points = self.points
        if len({(point.x, point.y) for point in points}) != 4:
            raise ValueError("PAGE_CORNERS_MUST_BE_DISTINCT")
        crosses = []
        for index in range(4):
            a, b, c = points[index], points[(index + 1) % 4], points[(index + 2) % 4]
            crosses.append((b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x))
        if min(crosses) <= 1e-6:
            raise ValueError("PAGE_CORNERS_MUST_BE_CLOCKWISE_CONVEX")
        if polygon_area(points) < 16.0:
            raise ValueError("PAGE_QUADRILATERAL_TOO_SMALL")
        return self


class PageCorrectionProposal(StrictModel):
    status: Literal["proposed", "not_found"]
    method: str = Field(min_length=1, max_length=128)
    corners: PageCorners | None = None
    confidence: ConfidenceValue | None = None
    diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def fields_match_status(self) -> PageCorrectionProposal:
        if self.status == "proposed" and (self.corners is None or self.confidence is None):
            raise ValueError("PAGE_PROPOSAL_REQUIRES_CORNERS_AND_CONFIDENCE")
        if self.status == "not_found" and self.corners is not None:
            raise ValueError("NOT_FOUND_PROPOSAL_CANNOT_HAVE_CORNERS")
        return self


@dataclass(frozen=True, slots=True)
class CorrectedRaster:
    content: bytes
    width_px: int
    height_px: int
    forward_matrix: Matrix3
    inverse_matrix: Matrix3
    source_corners: PageCorners
    algorithm_id: str
    parameters: dict[str, object]


@dataclass(frozen=True, slots=True)
class CorrectionRecord:
    record: PhotoRecord
    raster_sha256: str
    raster_path: str
    raster: CorrectedRaster


class PageCorrectionAdapter(Protocol):
    def propose(
        self, content: bytes, *, orientation: str, source_frame_id: str
    ) -> PageCorrectionProposal: ...

    def correct(
        self,
        content: bytes,
        corners: PageCorners,
        *,
        orientation: str,
        deskew_degrees: float = 0.0,
    ) -> CorrectedRaster: ...


def polygon_area(points: tuple[PixelPoint, ...]) -> float:
    return abs(
        sum(
            left.x * right.y - right.x * left.y
            for left, right in zip(points, (*points[1:], points[0]), strict=True)
        )
    ) / 2.0


def order_page_corners(
    points: tuple[PixelPoint, PixelPoint, PixelPoint, PixelPoint], *, frame_id: str
) -> PageCorners:
    """Normalize an arbitrary quadrilateral to screen-clockwise page order."""

    center_x = sum(point.x for point in points) / 4.0
    center_y = sum(point.y for point in points) / 4.0
    ordered = sorted(points, key=lambda point: math.atan2(point.y - center_y, point.x - center_x))
    start = min(range(4), key=lambda index: ordered[index].x + ordered[index].y)
    rotated = ordered[start:] + ordered[:start]
    if rotated[1].x < rotated[-1].x:
        rotated = [rotated[0], *reversed(rotated[1:])]
    return PageCorners(
        frame_id=frame_id,
        top_left=rotated[0],
        top_right=rotated[1],
        bottom_right=rotated[2],
        bottom_left=rotated[3],
    )


def validate_corners_in_frame(corners: PageCorners, width_px: int, height_px: int) -> None:
    if any(point.x > width_px - 1 or point.y > height_px - 1 for point in corners.points):
        raise ValueError("PAGE_CORNER_OUTSIDE_FRAME")
    if polygon_area(corners.points) < width_px * height_px * 0.01:
        raise ValueError("PAGE_QUADRILATERAL_TOO_SMALL")


def map_point(matrix: Matrix3, point: PixelPoint) -> PixelPoint:
    denominator = matrix[6] * point.x + matrix[7] * point.y + matrix[8]
    if abs(denominator) < 1e-12:
        raise ValueError("POINT_MAP_AT_INFINITY")
    x = (matrix[0] * point.x + matrix[1] * point.y + matrix[2]) / denominator
    y = (matrix[3] * point.x + matrix[4] * point.y + matrix[5]) / denominator
    # Matrix inversion may produce a tiny negative epsilon for a point exactly
    # on the top/left pixel boundary. Preserve the pixel-frame invariant without
    # hiding a materially out-of-frame mapping.
    if -1e-9 < x < 0:
        x = 0.0
    if -1e-9 < y < 0:
        y = 0.0
    return PixelPoint(x=x, y=y)


def persist_correction(
    repository: PhotoRepository,
    source: PhotoRecord,
    raster: CorrectedRaster,
    *,
    proposal_method: str,
    confidence: ConfidenceValue | None,
) -> CorrectionRecord:
    """Append a correction frame/transform while retaining exact original bytes."""

    source_frame = source.photo.frames[0]
    if raster.source_corners.frame_id != source_frame.frame_id:
        raise ValueError("CORRECTION_SOURCE_FRAME_MISMATCH")
    validate_corners_in_frame(raster.source_corners, source_frame.width_px, source_frame.height_px)
    raster_digest, raster_path = repository.store_derivative(raster.content, suffix="png")
    if raster_digest != sha256(raster.content).hexdigest():
        raise ValueError("CORRECTED_RASTER_HASH_MISMATCH")
    if any(item.output_sha256 == raster_digest for item in source.photo.transforms):
        return CorrectionRecord(
            record=source,
            raster_sha256=raster_digest,
            raster_path=str(raster_path),
            raster=raster,
        )
    frame_id = f"corrected-{raster_digest[:16]}"
    transform_id = f"page-correction-{raster_digest[:16]}"
    region_id = f"page-{raster_digest[:16]}"
    parameters = dict(raster.parameters)
    parameters.update(
        {
            "artifact_relative_path": repository.derivative_relative_path(raster_digest, "png"),
            "proposal_method": proposal_method,
            "source_corners": [point.model_dump(mode="json") for point in raster.source_corners.points],
            "planar_only": True,
        }
    )
    if confidence is not None:
        parameters["proposal_confidence"] = confidence.model_dump(mode="json")
    transform = ImageTransform(
        transform_id=transform_id,
        kind="homography",
        algorithm_id=raster.algorithm_id,
        input_sha256=source.photo.original_sha256,
        output_sha256=raster_digest,
        input_frame_id=source_frame.frame_id,
        output_frame_id=frame_id,
        forward_matrix=raster.forward_matrix,
        inverse_matrix=raster.inverse_matrix,
        parameters=parameters,
    )
    corrected_frame = PixelFrame(
        frame_id=frame_id,
        width_px=raster.width_px,
        height_px=raster.height_px,
    )
    page_region = PhotoRegion(
        region_id=region_id,
        kind="page",
        frame_id=source_frame.frame_id,
        polygon=raster.source_corners.points,
        confidence=confidence,
    )
    payload = source.photo.model_dump(mode="json")
    payload.update(
        frames=(*source.photo.frames, corrected_frame),
        transforms=(*source.photo.transforms, transform),
        regions=(*source.photo.regions, page_region),
        reading_order=source.photo.reading_order,
    )
    updated = NotebookPhoto.model_validate(payload, strict=True)
    updated_record = repository.store(updated, repository.read_original(source.photo))
    return CorrectionRecord(
        record=updated_record,
        raster_sha256=raster_digest,
        raster_path=str(raster_path),
        raster=raster,
    )
