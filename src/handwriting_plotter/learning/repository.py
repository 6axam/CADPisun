"""Safe import and immutable content-addressed storage for notebook photos."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from pydantic import Field

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads

from .models import (
    NotebookPhoto,
    PageDimensions,
    PhotoImportMetadata,
    PixelFrame,
    RulingEstimate,
)

MAX_PHOTO_BYTES = 32 * 1024 * 1024
MAX_PHOTO_PIXELS = 60_000_000
MAX_PHOTO_DIMENSION = 20_000
MAX_PHOTO_MANIFEST_BYTES = 8 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PhotoImportLimits(StrictModel):
    max_encoded_bytes: int = Field(default=MAX_PHOTO_BYTES, gt=0)
    max_decoded_pixels: int = Field(default=MAX_PHOTO_PIXELS, gt=0)
    max_dimension_px: int = Field(default=MAX_PHOTO_DIMENSION, gt=0)


@dataclass(frozen=True, slots=True)
class DecodedImageInfo:
    width_px: int
    height_px: int
    detected_format: str
    media_type: str
    decoder_id: str
    decoder_version: str
    embedded_orientation: str = "none"


class ImageDecoder(Protocol):
    def probe(self, content: bytes, limits: PhotoImportLimits) -> DecodedImageInfo: ...


@dataclass(frozen=True, slots=True)
class PhotoRecord:
    sha256: str
    path: Path
    photo: NotebookPhoto


def serialize_photo(photo: NotebookPhoto) -> bytes:
    return canonical_json_bytes(photo.model_dump(mode="json"))


def load_photo_bytes(data: bytes) -> NotebookPhoto:
    if len(data) > MAX_PHOTO_MANIFEST_BYTES:
        raise ValueError("PHOTO_MANIFEST_TOO_LARGE")
    decoded = strict_json_loads(data)
    if not isinstance(decoded, dict):
        raise ValueError("PHOTO_MANIFEST_ROOT_MUST_BE_OBJECT")
    if decoded.get("format") != "hp-notebook-photo":
        raise ValueError("UNSUPPORTED_PHOTO_FORMAT")
    if decoded.get("schema_version") != "1.0":
        raise ValueError("UNSUPPORTED_PHOTO_SCHEMA")
    return NotebookPhoto.model_validate_json(canonical_json_bytes(decoded), strict=True)


class PhotoRepository:
    """Store immutable manifests and exact original bytes under a trusted root."""

    def __init__(self, root: Path, *, limits: PhotoImportLimits | None = None) -> None:
        self.root = root
        self.limits = limits or PhotoImportLimits()

    @staticmethod
    def _valid_digest(digest: str) -> str:
        if not _SHA256.fullmatch(digest):
            raise ValueError("INVALID_PHOTO_HASH")
        return digest

    def original_relative_path(self, digest: str) -> str:
        digest = self._valid_digest(digest)
        return f"originals/{digest[:2]}/{digest}.bin"

    def original_path(self, digest: str) -> Path:
        return self._safe_child(self.original_relative_path(digest))

    def manifest_path(self, digest: str) -> Path:
        digest = self._valid_digest(digest)
        return self._safe_child(f"manifests/{digest[:2]}/{digest}.hp-photo.json")

    def import_file(
        self,
        path: Path,
        decoder: ImageDecoder,
        *,
        imported_at_utc: str,
        application_version: str,
        source_kind: str = "unknown",
        rights_status: str = "unknown",
        consent_ref: str | None = None,
        source_id: str | None = None,
    ) -> PhotoRecord:
        source_path = path.expanduser()
        if not source_path.is_file():
            raise FileNotFoundError("PHOTO_SOURCE_NOT_FOUND")
        file_size = source_path.stat().st_size
        if file_size <= 0:
            raise ValueError("EMPTY_PHOTO_FILE")
        if file_size > self.limits.max_encoded_bytes:
            raise ValueError("PHOTO_FILE_TOO_LARGE")
        content = source_path.read_bytes()
        if len(content) != file_size:
            raise ValueError("PHOTO_SOURCE_CHANGED_DURING_IMPORT")
        if len(content) > self.limits.max_encoded_bytes:
            raise ValueError("PHOTO_FILE_TOO_LARGE")

        info = decoder.probe(content, self.limits)
        self._validate_decoded_info(info)
        original_digest = sha256(content).hexdigest()
        relative = self.original_relative_path(original_digest)
        frame = PixelFrame(frame_id="source-pixels", width_px=info.width_px, height_px=info.height_px)
        photo = NotebookPhoto(
            source_id=source_id or f"photo-{uuid4()}",
            original_sha256=original_digest,
            original_relative_path=relative,
            metadata=PhotoImportMetadata(
                original_filename=source_path.name,
                imported_at_utc=imported_at_utc,
                application_version=application_version,
                source_kind=source_kind,
                detected_format=info.detected_format,
                media_type=info.media_type,
                encoded_bytes=len(content),
                decoder_id=info.decoder_id,
                decoder_version=info.decoder_version,
                embedded_orientation=info.embedded_orientation,
                rights_status=rights_status,
                consent_ref=consent_ref,
            ),
            page_dimensions=PageDimensions(width_px=info.width_px, height_px=info.height_px),
            frames=(frame,),
            ruling=RulingEstimate(frame_id=frame.frame_id),
        )
        return self.store(photo, content)

    def store(self, photo: NotebookPhoto, original: bytes) -> PhotoRecord:
        if not original:
            raise ValueError("EMPTY_PHOTO_FILE")
        if len(original) > self.limits.max_encoded_bytes:
            raise ValueError("PHOTO_FILE_TOO_LARGE")
        digest = sha256(original).hexdigest()
        if digest != photo.original_sha256:
            raise ValueError("PHOTO_ORIGINAL_HASH_MISMATCH")
        if len(original) != photo.metadata.encoded_bytes:
            raise ValueError("PHOTO_ORIGINAL_SIZE_MISMATCH")
        self._validate_dimensions(photo.page_dimensions.width_px, photo.page_dimensions.height_px)
        expected_relative = self.original_relative_path(digest)
        if photo.original_relative_path != expected_relative:
            raise ValueError("PHOTO_ORIGINAL_PATH_MISMATCH")

        original_target = self.original_path(digest)
        self._store_immutable(original_target, original, "PHOTO_ORIGINAL_HASH_MISMATCH")
        manifest = serialize_photo(photo)
        if len(manifest) > MAX_PHOTO_MANIFEST_BYTES:
            raise ValueError("PHOTO_MANIFEST_TOO_LARGE")
        record_digest = sha256(manifest).hexdigest()
        manifest_target = self.manifest_path(record_digest)
        self._store_immutable(manifest_target, manifest, "PHOTO_MANIFEST_HASH_MISMATCH")
        return PhotoRecord(record_digest, manifest_target, photo)

    def load(self, digest: str) -> NotebookPhoto:
        target = self.manifest_path(digest)
        if not target.is_file():
            raise FileNotFoundError("PHOTO_MANIFEST_NOT_FOUND")
        content = target.read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("PHOTO_MANIFEST_HASH_MISMATCH")
        photo = load_photo_bytes(content)
        expected_relative = self.original_relative_path(photo.original_sha256)
        if photo.original_relative_path != expected_relative:
            raise ValueError("PHOTO_ORIGINAL_PATH_MISMATCH")
        self.read_original(photo)
        return photo

    def read_original(self, photo: NotebookPhoto) -> bytes:
        expected_relative = self.original_relative_path(photo.original_sha256)
        if photo.original_relative_path != expected_relative:
            raise ValueError("PHOTO_ORIGINAL_PATH_MISMATCH")
        target = self._safe_child(photo.original_relative_path)
        if not target.is_file():
            raise FileNotFoundError("PHOTO_ORIGINAL_NOT_FOUND")
        content = target.read_bytes()
        if len(content) != photo.metadata.encoded_bytes or sha256(content).hexdigest() != photo.original_sha256:
            raise ValueError("PHOTO_ORIGINAL_HASH_MISMATCH")
        return content

    def list_records(self) -> tuple[PhotoRecord, ...]:
        root = self._safe_child("manifests")
        if not root.is_dir():
            return ()
        records: list[PhotoRecord] = []
        for path in sorted(root.glob("[0-9a-f][0-9a-f]/*.hp-photo.json")):
            digest = path.name.removesuffix(".hp-photo.json")
            photo = self.load(digest)
            records.append(PhotoRecord(digest, path, photo))
        return tuple(records)

    def _validate_decoded_info(self, info: DecodedImageInfo) -> None:
        self._validate_dimensions(info.width_px, info.height_px)

    def _validate_dimensions(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("PHOTO_HAS_NO_DIMENSIONS")
        if width > self.limits.max_dimension_px or height > self.limits.max_dimension_px:
            raise ValueError("PHOTO_DIMENSION_LIMIT_EXCEEDED")
        if width * height > self.limits.max_decoded_pixels:
            raise ValueError("PHOTO_PIXEL_LIMIT_EXCEEDED")

    def _safe_child(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("PHOTO_PATH_OUTSIDE_DATA_ROOT")
        root = self.root.resolve()
        candidate = (root / path).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("PHOTO_PATH_OUTSIDE_DATA_ROOT")
        return candidate

    @staticmethod
    def _store_immutable(target: Path, content: bytes, mismatch_error: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file() or target.read_bytes() != content:
                raise ValueError(mismatch_error)
            return
        descriptor, staging_name = tempfile.mkstemp(prefix=".photo-", suffix=".tmp", dir=target.parent)
        staging = Path(staging_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(staging, target)
            except FileExistsError:
                if not target.is_file() or target.read_bytes() != content:
                    raise ValueError(mismatch_error)
            if os.name != "nt":
                directory = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            staging.unlink(missing_ok=True)
