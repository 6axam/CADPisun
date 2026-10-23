"""Exact, atomic export of accepted generation artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

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


def export_page_png(result: GenerationResult, target: Path, *, width_px: int = 2480) -> None:
    """Render the accepted production SVG into a high-resolution PNG."""

    content = result.files.get("page-0001.svg")
    if content is None:
        raise ValueError("ARTIFACT_NOT_AVAILABLE")
    renderer = QSvgRenderer(QByteArray(content))
    if not renderer.isValid():
        raise ValueError("INVALID_SVG_ARTIFACT")
    height_px = round(width_px * 297 / 210)
    image = QImage(width_px, height_px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    renderer.render(painter, QRectF(0, 0, width_px, height_px))
    painter.end()
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("PNG_ENCODING_FAILED")
    buffer.close()
    _atomic_write(target, bytes(encoded))


def _atomic_write(target: Path, content: bytes) -> None:
    target = target.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
