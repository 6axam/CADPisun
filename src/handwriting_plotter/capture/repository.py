"""Canonical serialization and immutable content-addressed capture storage."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from handwriting_plotter.domain.models import canonical_json_bytes, strict_json_loads

from .models import CaptureSession

MAX_CAPTURE_BYTES = 32 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def serialize_capture(session: CaptureSession) -> bytes:
    return canonical_json_bytes(session.model_dump(mode="json"))


def capture_sha256(session: CaptureSession) -> str:
    return sha256(serialize_capture(session)).hexdigest()


def load_capture_bytes(data: bytes) -> CaptureSession:
    if len(data) > MAX_CAPTURE_BYTES:
        raise ValueError("CAPTURE_FILE_TOO_LARGE")
    decoded = strict_json_loads(data)
    if not isinstance(decoded, dict):
        raise ValueError("CAPTURE_ROOT_MUST_BE_OBJECT")
    if decoded.get("format") != "hp-capture":
        raise ValueError("UNSUPPORTED_CAPTURE_FORMAT")
    if decoded.get("schema_version") != "1.0":
        raise ValueError("UNSUPPORTED_CAPTURE_SCHEMA")
    # JSON validation keeps arrays compatible with strict tuple fields while the
    # preceding decoder still rejects duplicate keys and non-finite constants.
    return CaptureSession.model_validate_json(canonical_json_bytes(decoded), strict=True)


@dataclass(frozen=True, slots=True)
class CaptureRecord:
    sha256: str
    path: Path
    session: CaptureSession


class CaptureRepository:
    """Store raw captures once, addressed by the SHA-256 of canonical bytes."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, digest: str) -> Path:
        if not _SHA256.fullmatch(digest):
            raise ValueError("INVALID_CAPTURE_HASH")
        return self.root / "raw" / digest[:2] / f"{digest}.hp-capture.json"

    def store(self, session: CaptureSession) -> CaptureRecord:
        content = serialize_capture(session)
        if len(content) > MAX_CAPTURE_BYTES:
            raise ValueError("CAPTURE_FILE_TOO_LARGE")
        digest = sha256(content).hexdigest()
        target = self.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            self._verify_content(target, digest, content)
            return CaptureRecord(digest, target, session)

        descriptor, staging_name = tempfile.mkstemp(prefix=".capture-", suffix=".tmp", dir=target.parent)
        staging = Path(staging_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(staging, target)
            except FileExistsError:
                self._verify_content(target, digest, content)
            self._sync_directory(target.parent)
        finally:
            staging.unlink(missing_ok=True)
        return CaptureRecord(digest, target, session)

    def load(self, digest: str) -> CaptureSession:
        target = self.path_for(digest)
        if not target.is_file():
            raise FileNotFoundError("CAPTURE_NOT_FOUND")
        content = target.read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("CAPTURE_HASH_MISMATCH")
        return load_capture_bytes(content)

    @staticmethod
    def _verify_content(path: Path, digest: str, expected: bytes) -> None:
        content = path.read_bytes()
        if sha256(content).hexdigest() != digest or content != expected:
            raise ValueError("CAPTURE_HASH_MISMATCH")

    @staticmethod
    def _sync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

