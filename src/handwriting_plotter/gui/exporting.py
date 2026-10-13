"""Exact, atomic export of accepted generation artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from handwriting_plotter.application.service import GenerationResult


EXPORTABLE_ARTIFACTS = frozenset({
    "page-0001.svg",
    "page-0001.preview.svg",
    "page-0001.gcode",
    "report.json",
})


def export_artifact(result: GenerationResult, artifact: str, target: Path) -> None:
    if artifact not in EXPORTABLE_ARTIFACTS:
        raise ValueError("ARTIFACT_NOT_EXPORTABLE")
    if artifact not in result.files:
        raise ValueError("ARTIFACT_NOT_AVAILABLE")
    target = target.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(result.files[artifact])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
