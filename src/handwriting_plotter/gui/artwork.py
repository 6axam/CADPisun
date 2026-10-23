"""Validated import of portable SVG and raster reference artwork."""

from __future__ import annotations

import base64
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QImage
from PySide6.QtSvg import QSvgRenderer

from .document import ArtworkObject

MAX_ARTWORK_BYTES = 20 * 1024 * 1024
MEDIA_TYPES = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
}


def import_artwork(path: Path) -> ArtworkObject:
    """Read and decode an artwork file before embedding it in a project."""

    path = path.expanduser().resolve()
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise ValueError("UNSUPPORTED_ARTWORK_FORMAT")
    content = path.read_bytes()
    if not content:
        raise ValueError("EMPTY_ARTWORK_FILE")
    if len(content) > MAX_ARTWORK_BYTES:
        raise ValueError("ARTWORK_FILE_TOO_LARGE")
    if media_type == "image/svg+xml":
        renderer = QSvgRenderer(QByteArray(content))
        if not renderer.isValid():
            raise ValueError("INVALID_SVG_ARTWORK")
        size = renderer.defaultSize()
        pixel_width, pixel_height = size.width(), size.height()
    else:
        image = QImage.fromData(content)
        if image.isNull():
            raise ValueError("INVALID_RASTER_ARTWORK")
        pixel_width, pixel_height = image.width(), image.height()
    if pixel_width <= 0 or pixel_height <= 0:
        raise ValueError("ARTWORK_HAS_NO_DIMENSIONS")
    width_mm = min(120.0, max(20.0, pixel_width * 25.4 / 96.0))
    height_mm = width_mm * pixel_height / pixel_width
    if height_mm > 180.0:
        scale = 180.0 / height_mm
        width_mm *= scale
        height_mm = 180.0
    return ArtworkObject(
        object_id=str(uuid4()),
        name=path.stem[:120] or "Artwork",
        media_type=media_type,
        data_base64=base64.b64encode(content).decode("ascii"),
        sha256=sha256(content).hexdigest(),
        width_mm=width_mm,
        height_mm=height_mm,
    )
