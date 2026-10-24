"""Qt-free line-region proposals and immutable persistence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol

from .models import ConfidenceValue, NotebookPhoto, PhotoRegion, PixelPoint
from .repository import PhotoRecord, PhotoRepository


class LineSegmenter(Protocol):
    def segment(
        self, mask_png: bytes, *, frame_id: str, cancelled: Callable[[], bool] | None = None
    ) -> tuple[PhotoRegion, ...]: ...


def persist_line_regions(
    repository: PhotoRepository, source: PhotoRecord, regions: tuple[PhotoRegion, ...]
) -> PhotoRecord:
    """Replace only prior line proposals for their frame, retaining page regions."""

    if any(region.kind != "line" for region in regions):
        raise ValueError("INVALID_LINE_REGION_SET")
    return persist_regions(repository, source, regions)


def persist_regions(
    repository: PhotoRepository, source: PhotoRecord, regions: tuple[PhotoRegion, ...]
) -> PhotoRecord:
    """Publish explicit readable regions and a deterministic reading order."""

    frames = {frame.frame_id for frame in source.photo.frames}
    supported = {"line", "header", "marginalia"}
    if not regions or any(region.frame_id not in frames or region.kind not in supported for region in regions):
        raise ValueError("INVALID_READABLE_REGION_SET")
    if len({region.region_id for region in regions}) != len(regions):
        raise ValueError("DUPLICATE_LINE_REGION")
    frame_ids = {region.frame_id for region in regions}
    retained = tuple(
        region for region in source.photo.regions
        if region.kind not in supported or region.frame_id not in frame_ids
    )
    payload = source.photo.model_dump(mode="python")
    payload["regions"] = (*retained, *regions)
    payload["reading_order"] = reading_order_for_regions(payload["regions"])
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


def manual_region(
    *,
    frame_id: str,
    region_id: str,
    kind: Literal["header", "marginalia", "line"],
    left: float,
    top: float,
    right: float,
    bottom: float,
) -> PhotoRegion:
    """Create a human-labelled header, marginalia, or line fallback region."""

    if kind == "line":
        return manual_line_region(
            frame_id=frame_id, region_id=region_id, left=left, top=top, right=right, bottom=bottom
        )
    if right <= left or bottom <= top:
        raise ValueError("INVALID_MANUAL_REGION_BOUNDS")
    return PhotoRegion(
        region_id=region_id, kind=kind, frame_id=frame_id,
        polygon=(PixelPoint(x=left, y=top), PixelPoint(x=right, y=top), PixelPoint(x=right, y=bottom), PixelPoint(x=left, y=bottom)),
        confidence=ConfidenceValue(value=1.0, origin="human", meaning=f"manual {kind} region"),
    )


def reading_order_for_regions(regions: tuple[PhotoRegion, ...]) -> tuple[str, ...]:
    """Stable top-to-bottom, left-to-right order for readable page regions."""

    readable = (region for region in regions if region.kind in {"header", "line", "marginalia"})
    return tuple(
        region.region_id for region in sorted(
            readable,
            key=lambda region: (
                min(point.y for point in region.polygon),
                min(point.x for point in region.polygon),
                region.region_id,
            ),
        )
    )
