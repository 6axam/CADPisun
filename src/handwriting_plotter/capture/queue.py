"""Persistent editable capture queues, separate from immutable raw traces."""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CaptureQueueState(StrictModel):
    format: Literal["hp-capture-queue"] = "hp-capture-queue"
    schema_version: Literal["1.0"] = "1.0"
    queue_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=256)
    tokens: tuple[str, ...]
    current_index: int = Field(default=0, ge=0)
    required_variants: int = Field(default=1, ge=1, le=99)
    skipped_tokens: frozenset[str] = frozenset()
    rejected_capture_hashes: frozenset[str] = frozenset()

    @field_validator("tokens")
    @classmethod
    def valid_tokens(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("capture queue must contain tokens")
        if len(value) > 100_000:
            raise ValueError("capture queue has too many tokens")
        if any(not token.strip() or len(token) > 256 for token in value):
            raise ValueError("invalid queue token")
        if any(unicodedata.normalize("NFC", token) != token for token in value):
            raise ValueError("queue tokens must be NFC normalized")
        if len(value) != len(set(value)):
            raise ValueError("duplicate queue token")
        return value

    @field_validator("rejected_capture_hashes")
    @classmethod
    def valid_hashes(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not _SHA256.fullmatch(item) for item in value):
            raise ValueError("invalid rejected capture hash")
        return value

    @model_validator(mode="after")
    def valid_progress(self) -> CaptureQueueState:
        if self.current_index >= len(self.tokens):
            raise ValueError("current_index is outside queue")
        if not self.skipped_tokens <= set(self.tokens):
            raise ValueError("skipped token is outside queue")
        return self


class CaptureQueueStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, queue_id: str) -> Path:
        if not _SAFE_ID.fullmatch(queue_id):
            raise ValueError("INVALID_QUEUE_ID")
        return self.root / "drafts" / "queues" / f"{queue_id}.json"

    def load(self, queue_id: str) -> CaptureQueueState:
        path = self.path_for(queue_id)
        data = strict_json_loads(path.read_bytes())
        if not isinstance(data, dict) or data.get("format") != "hp-capture-queue":
            raise ValueError("UNSUPPORTED_QUEUE_FORMAT")
        if data.get("schema_version") != "1.0":
            raise ValueError("UNSUPPORTED_QUEUE_SCHEMA")
        return CaptureQueueState.model_validate_json(canonical_json_bytes(data), strict=True)

    def save(self, state: CaptureQueueState) -> Path:
        path = self.path_for(state.queue_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = canonical_json_bytes(state.model_dump(mode="json"))
        descriptor, staging_name = tempfile.mkstemp(prefix=f".{state.queue_id}-", suffix=".tmp", dir=path.parent)
        staging = Path(staging_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(staging, path)
            if os.name != "nt":
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            staging.unlink(missing_ok=True)
        return path

