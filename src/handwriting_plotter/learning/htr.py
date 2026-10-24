"""Optional, subprocess-isolated HTR protocol and private result persistence.

This module intentionally depends only on the default application dependencies.
Torch/Transformers live exclusively in ``htr_provider_worker.py`` and in the
user-configured external Python environment.
"""

from __future__ import annotations

import base64
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable, Literal

from pydantic import Field, field_validator

from handwriting_plotter.domain.models import StrictModel, canonical_json_bytes, strict_json_loads

HTR_WORKER_PROTOCOL_VERSION = "hp-htr-worker/1"
HTR_RUN_FORMAT = "hp-htr-run"
HTR_RUN_SCHEMA_VERSION = "1.0"
MAX_HTR_LINES = 256
MAX_HTR_CROP_BYTES = 4 * 1024 * 1024
MAX_HTR_TIMEOUT_SECONDS = 15 * 60

HtrProviderId = Literal["crnn-rukopys", "trocr-rukopys"]


class HtrLineRequest(StrictModel):
    """Ephemeral line crop only. Ground truth is deliberately not representable."""

    line_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    crop_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    png_base64: str = Field(min_length=4, max_length=((MAX_HTR_CROP_BYTES + 2) // 3) * 4)

    @field_validator("png_base64")
    @classmethod
    def valid_png_payload(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError) as exc:
            raise ValueError("INVALID_HTR_CROP_ENCODING") from exc
        if not decoded or len(decoded) > MAX_HTR_CROP_BYTES:
            raise ValueError("HTR_CROP_SIZE_LIMIT")
        return value


class HtrWorkerRequest(StrictModel):
    protocol_version: Literal["hp-htr-worker/1"] = HTR_WORKER_PROTOCOL_VERSION
    request_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    provider_id: HtrProviderId
    timeout_seconds: int = Field(ge=1, le=MAX_HTR_TIMEOUT_SECONDS)
    memory_limit_bytes: int = Field(ge=256 * 1024 * 1024, le=16 * 1024 * 1024 * 1024)
    lines: tuple[HtrLineRequest, ...] = Field(min_length=1, max_length=MAX_HTR_LINES)

    @field_validator("lines")
    @classmethod
    def distinct_line_ids(cls, value: tuple[HtrLineRequest, ...]) -> tuple[HtrLineRequest, ...]:
        if len({item.line_id for item in value}) != len(value):
            raise ValueError("DUPLICATE_HTR_LINE_ID")
        return value

    def to_wire(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json")) + b"\n"


class HtrLineResult(StrictModel):
    line_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    crop_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text: str = Field(max_length=16_384)
    elapsed_ms: float = Field(ge=0.0)
    confidence: None = None


class HtrRun(StrictModel):
    format: Literal["hp-htr-run"] = HTR_RUN_FORMAT
    schema_version: Literal["1.0"] = HTR_RUN_SCHEMA_VERSION
    run_id: str = Field(pattern=r"^[a-f0-9-]{36}$")
    created_at_utc: str
    status: Literal["succeeded", "cancelled", "failed"]
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frame_id: str = Field(min_length=1, max_length=128)
    provider_id: HtrProviderId
    worker_protocol_version: Literal["hp-htr-worker/1"] = HTR_WORKER_PROTOCOL_VERSION
    model_revision: str | None = Field(default=None, max_length=128)
    model_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    memory_limit_bytes: int = Field(ge=256 * 1024 * 1024)
    lines: tuple[HtrLineResult, ...] = ()
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=1_024)

    @field_validator("lines")
    @classmethod
    def result_line_ids_are_distinct(cls, value: tuple[HtrLineResult, ...]) -> tuple[HtrLineResult, ...]:
        if len({item.line_id for item in value}) != len(value):
            raise ValueError("DUPLICATE_HTR_RESULT_LINE_ID")
        return value


@dataclass(frozen=True, slots=True)
class HtrRunRecord:
    sha256: str
    path: Path
    run: HtrRun


class HtrResultRepository:
    """Content-addressed local result records; no results enter the project file."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for(self, digest: str) -> Path:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("INVALID_HTR_RUN_HASH")
        return self.root / "htr-runs" / digest[:2] / f"{digest}.hp-htr-run.json"

    def store(self, run: HtrRun) -> HtrRunRecord:
        content = canonical_json_bytes(run.model_dump(mode="json"))
        digest = sha256(content).hexdigest()
        target = self.path_for(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != content:
                raise ValueError("HTR_RUN_HASH_MISMATCH")
        else:
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_bytes(content)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return HtrRunRecord(sha256=digest, path=target, run=run)

    def load(self, digest: str) -> HtrRunRecord:
        path = self.path_for(digest)
        content = path.read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("HTR_RUN_HASH_MISMATCH")
        decoded = strict_json_loads(content)
        if not isinstance(decoded, dict):
            raise ValueError("INVALID_HTR_RUN")
        # ``strict_json_loads`` above rejects duplicate keys. Pydantic's JSON
        # parser then restores JSON arrays into the strict tuple fields.
        run = HtrRun.model_validate_json(content, strict=True)
        return HtrRunRecord(sha256=digest, path=path, run=run)

    def list_for_source(self, source_manifest_sha256: str) -> tuple[HtrRunRecord, ...]:
        directory = self.root / "htr-runs"
        if not directory.is_dir():
            return ()
        records: list[HtrRunRecord] = []
        for path in directory.glob("[0-9a-f][0-9a-f]/*.hp-htr-run.json"):
            try:
                digest = path.name.removesuffix(".hp-htr-run.json")
                record = self.load(digest)
            except (OSError, ValueError):
                continue
            if record.run.source_manifest_sha256 == source_manifest_sha256:
                records.append(record)
        return tuple(sorted(records, key=lambda item: item.run.created_at_utc, reverse=True))


@dataclass(frozen=True, slots=True)
class HtrRuntime:
    """Explicit local provider installation; paths are never persisted in a run."""

    python_executable: Path
    model_root: Path
    timeout_seconds: int
    memory_limit_bytes: int

    def validate(self) -> None:
        if not self.python_executable.is_file():
            raise FileNotFoundError("HTR_PYTHON_NOT_FOUND")
        if not self.model_root.is_dir():
            raise FileNotFoundError("HTR_MODEL_ROOT_NOT_FOUND")
        if not 1 <= self.timeout_seconds <= MAX_HTR_TIMEOUT_SECONDS:
            raise ValueError("INVALID_HTR_TIMEOUT")
        if not 256 * 1024 * 1024 <= self.memory_limit_bytes <= 16 * 1024 * 1024 * 1024:
            raise ValueError("INVALID_HTR_MEMORY_LIMIT")


class HtrProcessError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class HtrCancelled(RuntimeError):
    pass


class HtrProcessClient:
    """Run exactly one provider process and relay structured progress safely."""

    def __init__(self, runtime: HtrRuntime, *, worker_script: Path | None = None) -> None:
        self.runtime = runtime
        self.worker_script = worker_script or Path(__file__).with_name("htr_provider_worker.py")

    def recognize(
        self,
        request: HtrWorkerRequest,
        *,
        progress: Callable[[int, int, str], None],
        cancelled: Callable[[], bool],
    ) -> tuple[tuple[HtrLineResult, ...], str, str]:
        self.runtime.validate()
        if not self.worker_script.is_file():
            raise FileNotFoundError("HTR_WORKER_SCRIPT_NOT_FOUND")
        command = [
            str(self.runtime.python_executable), str(self.worker_script),
            "--model-root", str(self.runtime.model_root),
        ]
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        process.stdin.write(request.to_wire().decode("utf-8"))
        process.stdin.close()
        messages: queue.Queue[tuple[str, str | None]] = queue.Queue()

        def collect(kind: str, stream) -> None:  # noqa: ANN001
            try:
                for line in stream:
                    messages.put((kind, line))
            finally:
                messages.put((kind, None))

        threads = (
            threading.Thread(target=collect, args=("stdout", process.stdout), daemon=True),
            threading.Thread(target=collect, args=("stderr", process.stderr), daemon=True),
        )
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + request.timeout_seconds
        final: dict[str, object] | None = None
        stderr: list[str] = []
        while process.poll() is None or not messages.empty():
            if cancelled():
                self._stop(process)
                raise HtrCancelled("HTR_CANCELLED")
            if time.monotonic() >= deadline:
                self._stop(process)
                raise HtrProcessError("HTR_TIMEOUT", f"provider exceeded {request.timeout_seconds}s")
            try:
                kind, line = messages.get(timeout=0.05)
            except queue.Empty:
                continue
            if line is None:
                continue
            if kind == "stderr":
                stderr.append(line.rstrip())
                continue
            try:
                event = strict_json_loads(line)
            except (UnicodeDecodeError, ValueError) as exc:
                self._stop(process)
                raise HtrProcessError("HTR_PROTOCOL_INVALID", "worker returned invalid JSON") from exc
            if not isinstance(event, dict):
                raise HtrProcessError("HTR_PROTOCOL_INVALID", "worker event must be an object")
            if event.get("event") == "progress":
                progress(int(event["completed"]), int(event["total"]), str(event.get("stage", "recognizing")))
            elif event.get("event") == "complete":
                final = event
            elif event.get("event") == "error":
                raise HtrProcessError(str(event.get("code", "HTR_PROVIDER_FAILED")), str(event.get("message", "provider failed")))
        for thread in threads:
            thread.join(timeout=0.2)
        if process.returncode not in (0, None):
            detail = "\n".join(stderr[-8:]).strip()
            raise HtrProcessError("HTR_PROVIDER_CRASHED", detail or f"worker exited {process.returncode}")
        if final is None:
            raise HtrProcessError("HTR_PROTOCOL_INCOMPLETE", "worker did not return a completion event")
        try:
            lines = tuple(HtrLineResult.model_validate(item, strict=True) for item in final["lines"])
            expected = {item.line_id for item in request.lines}
            if {item.line_id for item in lines} != expected:
                raise ValueError("HTR_RESULT_LINE_SET_MISMATCH")
            return lines, str(final["model_revision"]), str(final["model_sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HtrProcessError("HTR_PROTOCOL_INVALID", "worker completion is invalid") from exc

    @staticmethod
    def _stop(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def make_htr_request(
    provider_id: HtrProviderId, lines: tuple[tuple[str, str, bytes], ...], *, timeout_seconds: int,
    memory_limit_bytes: int,
) -> HtrWorkerRequest:
    """Build the only provider payload from line pixels and technical identifiers."""

    return HtrWorkerRequest(
        request_id=str(uuid.uuid4()), provider_id=provider_id, timeout_seconds=timeout_seconds,
        memory_limit_bytes=memory_limit_bytes,
        lines=tuple(
            HtrLineRequest(
                line_id=line_id, crop_sha256=crop_sha256,
                png_base64=base64.b64encode(content).decode("ascii"),
            )
            for line_id, crop_sha256, content in lines
        ),
    )


def new_htr_run(
    *, source_manifest_sha256: str, original_sha256: str, frame_id: str,
    request: HtrWorkerRequest, status: Literal["succeeded", "cancelled", "failed"],
    lines: tuple[HtrLineResult, ...] = (), model_revision: str | None = None,
    model_sha256: str | None = None, error_code: str | None = None,
    error_message: str | None = None,
) -> HtrRun:
    return HtrRun(
        run_id=str(uuid.uuid4()), created_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status=status, source_manifest_sha256=source_manifest_sha256,
        original_sha256=original_sha256, frame_id=frame_id, provider_id=request.provider_id,
        memory_limit_bytes=request.memory_limit_bytes, lines=lines, model_revision=model_revision,
        model_sha256=model_sha256, error_code=error_code, error_message=error_message,
    )
