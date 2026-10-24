"""Qt-free line-region proposals and immutable persistence."""

from __future__ import annotations

from typing import Protocol

from .models import ConfidenceValue, NotebookPhoto, PhotoRegion, PixelPoint
from .repository import PhotoRecord, PhotoRepository


class LineSegmenter(Protocol):
    def segment(self, mask_png: bytes, *, frame_id: str) -> tuple[PhotoRegion, ...]: ...


def persist_line_regions(
    repository: PhotoRepository, source: PhotoRecord, regions: tuple[PhotoRegion, ...]
) -> PhotoRecord:
    """Replace only prior line proposals for their frame, retaining page regions."""

    frames = {frame.frame_id for frame in source.photo.frames}
    if not regions or any(region.frame_id not in frames or region.kind != "line" for region in regions):
        raise ValueError("INVALID_LINE_REGION_SET")
    if len({region.region_id for region in regions}) != len(regions):
        raise ValueError("DUPLICATE_LINE_REGION")
    frame_ids = {region.frame_id for region in regions}
    retained = tuple(
        region for region in source.photo.regions
        if not (region.kind == "line" and region.frame_id in frame_ids)
    )
    payload = source.photo.model_dump(mode="python")
    payload["regions"] = (*retained, *regions)
    updated = NotebookPhoto.model_validate(payload, strict=True)
    return repository.store(updated, repository.read_original(source.photo))


def manual_line_region(
    *, frame_id: str, region_id: str, left: float, top: float, right: float, bottom: float
) -> PhotoRegion:
    """Make an explicit rectangular fallback line proposal with a center baseline."""

    if right <= left or bottom <= top:
        raise ValueError("INVALID_MANUAL_LINE_BOUNDS")
    baseline_y = (top + bottom) / 2.0
    return PhotoRegion(
        region_id=region_id,
        kind="line",
        frame_id=frame_id,
        polygon=(
            PixelPoint(x=left, y=top), PixelPoint(x=right, y=top),
            PixelPoint(x=right, y=bottom), PixelPoint(x=left, y=bottom),
        ),
        baseline=(PixelPoint(x=left, y=baseline_y), PixelPoint(x=right, y=baseline_y)),
        confidence=ConfidenceValue(value=1.0, origin="human", meaning="manual line region"),
    )
