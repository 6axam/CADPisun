"""Qt-free immutable persistence contracts for paper/ink masks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .models import InkMask, NotebookPhoto, RulingEstimate
from .repository import PhotoRecord, PhotoRepository


@dataclass(frozen=True, slots=True)
class InkMaskRaster:
    """Encoded binary raw and conservative-cleaned mask outputs."""

    frame_id: str
    raw_png: bytes
    cleaned_png: bytes
    method: str
    diagnostics: tuple[str, ...] = ()


class InkSeparator(Protocol):
    def separate(
        self, content: bytes, *, frame_id: str, ruling: RulingEstimate
    ) -> InkMaskRaster: ...


def persist_ink_mask(
    repository: PhotoRepository, source: PhotoRecord, raster: InkMaskRaster
) -> PhotoRecord:
    """Store both masks by content hash and publish a new source revision."""

    if raster.frame_id not in {frame.frame_id for frame in source.photo.frames}:
        raise ValueError("INK_MASK_FRAME_NOT_FOUND")
    raw_digest, raw_path = repository.store_derivative(raster.raw_png, suffix="png")
    cleaned_digest, cleaned_path = repository.store_derivative(raster.cleaned_png, suffix="png")
    payload = source.photo.model_dump(mode="python")
    payload["ink_mask"] = InkMask(
        frame_id=raster.frame_id,
        method=raster.method,
        raw_sha256=raw_digest,
        raw_relative_path=str(raw_path.relative_to(repository.root)),
        cleaned_sha256=cleaned_digest,
        cleaned_relative_path=str(cleaned_path.relative_to(repository.root)),
        diagnostics=raster.diagnostics,
    )
    updated = NotebookPhoto.model_validate(payload, strict=True)
    return repository.store(updated, repository.read_original(source.photo))


def select_ink_mask_variant(
    repository: PhotoRepository,
    source: PhotoRecord,
    variant: Literal["raw", "cleaned"],
) -> PhotoRecord:
    """Save an explicit user choice without replacing either artifact."""

    if source.photo.ink_mask is None:
        raise ValueError("INK_MASK_NOT_AVAILABLE")
    payload = source.photo.model_dump(mode="python")
    payload["ink_mask"] = source.photo.ink_mask.model_copy(
        update={"status": "overridden", "selected_variant": variant}
    )
    updated = NotebookPhoto.model_validate(payload, strict=True)
    return repository.store(updated, repository.read_original(source.photo))
