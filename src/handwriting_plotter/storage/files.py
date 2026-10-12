"""Transactional directory publication without partial completed bundles."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("INVALID_ARTIFACT_PATH")
    return path


def publish_bundle(target: Path, files: dict[str, bytes], *, overwrite: bool = False) -> None:
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise FileExistsError("OUTPUT_EXISTS")
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
    backup = target.parent / f".{target.name}.backup"
    try:
        for relative, content in sorted(files.items()):
            path = staging / _safe_relative(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                with path.open("rb") as handle:
                    os.fsync(handle.fileno())
        if target.exists():
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(target, backup)
        try:
            os.replace(staging, target)
        except BaseException:
            if backup.exists() and not target.exists():
                os.replace(backup, target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

