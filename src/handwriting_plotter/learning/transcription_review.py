"""Immutable, local human review records for HTR line transcriptions.

The review store deliberately has no benchmark or provider-request fields.  It
links a human edit to an already-persisted HTR run and immutable line crop, but
never makes a review text available to a recognizer.
"""

from __future__ import annotations

import os
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads

REVIEW_FORMAT = "hp-transcription-review"
REVIEW_ORDER_FORMAT = "hp-transcription-reading-order"
REVIEW_SCHEMA_VERSION = "1.0"
ReviewStatus = Literal["unreviewed", "edited", "accepted", "unresolved"]


class ReviewConflict(RuntimeError):
    """The editor tried to append from an obsolete review/order revision."""


class TranscriptionReviewRevision(StrictModel):
    format: Literal["hp-transcription-review"] = REVIEW_FORMAT
    schema_version: Literal["1.0"] = REVIEW_SCHEMA_VERSION
    revision_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    created_at_utc: str
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    line_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    crop_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    htr_run_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    original_prediction: str | None = Field(default=None, max_length=16_384)
    reviewed_text: str = Field(max_length=16_384)
    status: ReviewStatus
    parent_revision_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("original_prediction", "reviewed_text")
    @classmethod
    def normalize_nfc(cls, value: str | None) -> str | None:
        return None if value is None else unicodedata.normalize("NFC", value)


class ReadingOrderEntry(StrictModel):
    line_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    crop_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReadingOrderRevision(StrictModel):
    format: Literal["hp-transcription-reading-order"] = REVIEW_ORDER_FORMAT
    schema_version: Literal["1.0"] = REVIEW_SCHEMA_VERSION
    revision_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    created_at_utc: str
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: tuple[ReadingOrderEntry, ...] = Field(min_length=1, max_length=256)
    parent_revision_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("entries")
    @classmethod
    def distinct_line_ids(cls, value: tuple[ReadingOrderEntry, ...]) -> tuple[ReadingOrderEntry, ...]:
        if len({entry.line_id for entry in value}) != len(value):
            raise ValueError("DUPLICATE_READING_ORDER_LINE")
        return value


@dataclass(frozen=True, slots=True)
class TranscriptionReviewRecord:
    sha256: str
    path: Path
    revision: TranscriptionReviewRevision


@dataclass(frozen=True, slots=True)
class ReadingOrderRecord:
    sha256: str
    path: Path
    revision: ReadingOrderRevision


class TranscriptionReviewRepository:
    """Content-addressed append-only local records, intentionally outside projects."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _validate_digest(digest: str, *, code: str) -> None:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(code)

    def _path_for(self, directory: str, digest: str, suffix: str) -> Path:
        self._validate_digest(digest, code="INVALID_REVIEW_HASH")
        return self.root / directory / digest[:2] / f"{digest}.{suffix}.json"

    def path_for(self, digest: str) -> Path:
        return self._path_for("transcription-reviews", digest, "hp-review")

    def order_path_for(self, digest: str) -> Path:
        return self._path_for("transcription-reading-orders", digest, "hp-reading-order")

    @staticmethod
    def _store_content(target: Path, content: bytes, *, mismatch_code: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != content:
                raise ValueError(mismatch_code)
            return
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def store(self, revision: TranscriptionReviewRevision) -> TranscriptionReviewRecord:
        content = canonical_json_bytes(revision.model_dump(mode="json"))
        digest = sha256(content).hexdigest()
        target = self.path_for(digest)
        self._store_content(target, content, mismatch_code="REVIEW_HASH_MISMATCH")
        return TranscriptionReviewRecord(digest, target, revision)

    def load(self, digest: str) -> TranscriptionReviewRecord:
        path = self.path_for(digest)
        content = path.read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("REVIEW_HASH_MISMATCH")
        if not isinstance(strict_json_loads(content), dict):
            raise ValueError("INVALID_REVIEW_RECORD")
        return TranscriptionReviewRecord(digest, path, TranscriptionReviewRevision.model_validate_json(content, strict=True))

    def _records_for_source(self, source_manifest_sha256: str) -> tuple[TranscriptionReviewRecord, ...]:
        self._validate_digest(source_manifest_sha256, code="INVALID_SOURCE_MANIFEST_HASH")
        directory = self.root / "transcription-reviews"
        if not directory.is_dir():
            return ()
        records: list[TranscriptionReviewRecord] = []
        for path in directory.glob("[0-9a-f][0-9a-f]/*.hp-review.json"):
            try:
                record = self.load(path.name.removesuffix(".hp-review.json"))
            except (OSError, ValueError):
                continue
            if record.revision.source_manifest_sha256 == source_manifest_sha256:
                records.append(record)
        return tuple(sorted(records, key=lambda item: (item.revision.created_at_utc, item.sha256)))

    def list_for_source(self, source_manifest_sha256: str) -> tuple[TranscriptionReviewRecord, ...]:
        return self._records_for_source(source_manifest_sha256)

    def latest_for_line(
        self, source_manifest_sha256: str, line_id: str, crop_sha256: str
    ) -> TranscriptionReviewRecord | None:
        matches = [
            record for record in self._records_for_source(source_manifest_sha256)
            if record.revision.line_id == line_id and record.revision.crop_sha256 == crop_sha256
        ]
        return matches[-1] if matches else None

    def append(
        self,
        *,
        source_manifest_sha256: str,
        line_id: str,
        crop_sha256: str,
        htr_run_sha256: str | None,
        original_prediction: str | None,
        reviewed_text: str,
        status: ReviewStatus,
        expected_parent_revision_sha256: str | None,
        created_at_utc: str | None = None,
    ) -> TranscriptionReviewRecord:
        latest = self.latest_for_line(source_manifest_sha256, line_id, crop_sha256)
        latest_digest = latest.sha256 if latest else None
        if latest_digest != expected_parent_revision_sha256:
            raise ReviewConflict("REVIEW_REVISION_CONFLICT")
        revision = TranscriptionReviewRevision(
            revision_id=str(uuid.uuid4()),
            created_at_utc=created_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            source_manifest_sha256=source_manifest_sha256,
            line_id=line_id,
            crop_sha256=crop_sha256,
            htr_run_sha256=htr_run_sha256,
            original_prediction=original_prediction,
            reviewed_text=reviewed_text,
            status=status,
            parent_revision_sha256=expected_parent_revision_sha256,
        )
        return self.store(revision)

    def store_order(self, revision: ReadingOrderRevision) -> ReadingOrderRecord:
        content = canonical_json_bytes(revision.model_dump(mode="json"))
        digest = sha256(content).hexdigest()
        target = self.order_path_for(digest)
        self._store_content(target, content, mismatch_code="READING_ORDER_HASH_MISMATCH")
        return ReadingOrderRecord(digest, target, revision)

    def load_order(self, digest: str) -> ReadingOrderRecord:
        path = self.order_path_for(digest)
        content = path.read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("READING_ORDER_HASH_MISMATCH")
        if not isinstance(strict_json_loads(content), dict):
            raise ValueError("INVALID_READING_ORDER_RECORD")
        return ReadingOrderRecord(digest, path, ReadingOrderRevision.model_validate_json(content, strict=True))

    def latest_order(self, source_manifest_sha256: str) -> ReadingOrderRecord | None:
        self._validate_digest(source_manifest_sha256, code="INVALID_SOURCE_MANIFEST_HASH")
        directory = self.root / "transcription-reading-orders"
        if not directory.is_dir():
            return None
        records: list[ReadingOrderRecord] = []
        for path in directory.glob("[0-9a-f][0-9a-f]/*.hp-reading-order.json"):
            try:
                record = self.load_order(path.name.removesuffix(".hp-reading-order.json"))
            except (OSError, ValueError):
                continue
            if record.revision.source_manifest_sha256 == source_manifest_sha256:
                records.append(record)
        return max(records, key=lambda item: (item.revision.created_at_utc, item.sha256), default=None)

    def append_order(
        self,
        *,
        source_manifest_sha256: str,
        entries: tuple[ReadingOrderEntry, ...],
        expected_parent_revision_sha256: str | None,
        created_at_utc: str | None = None,
    ) -> ReadingOrderRecord:
        latest = self.latest_order(source_manifest_sha256)
        latest_digest = latest.sha256 if latest else None
        if latest_digest != expected_parent_revision_sha256:
            raise ReviewConflict("READING_ORDER_REVISION_CONFLICT")
        return self.store_order(ReadingOrderRevision(
            revision_id=str(uuid.uuid4()),
            created_at_utc=created_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            source_manifest_sha256=source_manifest_sha256,
            entries=entries,
            parent_revision_sha256=expected_parent_revision_sha256,
        ))
