"""Qt image decoder adapter with bounded allocation before full decode."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, qVersion
from PySide6.QtGui import QImageIOHandler, QImageReader

from handwriting_plotter.learning.repository import DecodedImageInfo, PhotoImportLimits

_FORMAT_ALIASES = {"jpg": "jpeg", "jfif": "jpeg"}
_MEDIA_TYPES = {
    "bmp": "image/bmp",
    "gif": "image/gif",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
_ORIENTATIONS = {
    QImageIOHandler.Transformation.TransformationNone: "none",
    QImageIOHandler.Transformation.TransformationMirror: "mirror_horizontal",
    QImageIOHandler.Transformation.TransformationFlip: "flip_vertical",
    QImageIOHandler.Transformation.TransformationRotate180: "rotate_180",
    QImageIOHandler.Transformation.TransformationRotate90: "rotate_90",
    QImageIOHandler.Transformation.TransformationMirrorAndRotate90: "mirror_horizontal_rotate_90",
    QImageIOHandler.Transformation.TransformationFlipAndRotate90: "flip_vertical_rotate_90",
    QImageIOHandler.Transformation.TransformationRotate270: "rotate_270",
}


class QtImageDecoder:
    """Probe and fully decode a supported raster without applying EXIF transforms."""

    def probe(self, content: bytes, limits: PhotoImportLimits) -> DecodedImageInfo:
        if not content:
            raise ValueError("EMPTY_PHOTO_FILE")
        if len(content) > limits.max_encoded_bytes:
            raise ValueError("PHOTO_FILE_TOO_LARGE")

        encoded = QByteArray(content)
        buffer = QBuffer()
        buffer.setData(encoded)
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            raise ValueError("PHOTO_DECODE_BUFFER_FAILED")
        reader = QImageReader(buffer)
        reader.setAutoDetectImageFormat(True)
        reader.setDecideFormatFromContent(True)
        reader.setAutoTransform(False)
        raw_format = bytes(reader.format()).decode("ascii", errors="strict").lower()
        detected_format = _FORMAT_ALIASES.get(raw_format, raw_format)
        if detected_format not in _MEDIA_TYPES:
            raise ValueError("UNSUPPORTED_PHOTO_FORMAT")
        if not reader.canRead():
            raise ValueError(f"INVALID_PHOTO_IMAGE:{reader.errorString()}")
        size = reader.size()
        width, height = size.width(), size.height()
        self._validate_dimensions(width, height, limits)
        image_count = reader.imageCount()
        if image_count > 1:
            raise ValueError("MULTI_FRAME_PHOTO_NOT_SUPPORTED")
        orientation = _ORIENTATIONS.get(reader.transformation())
        if orientation is None:
            raise ValueError("UNSUPPORTED_PHOTO_ORIENTATION")

        image = reader.read()
        if image.isNull():
            raise ValueError(f"INVALID_PHOTO_IMAGE:{reader.errorString()}")
        if image.width() != width or image.height() != height:
            raise ValueError("PHOTO_DIMENSIONS_CHANGED_DURING_DECODE")
        self._validate_dimensions(image.width(), image.height(), limits)
        return DecodedImageInfo(
            width_px=image.width(),
            height_px=image.height(),
            detected_format=detected_format,
            media_type=_MEDIA_TYPES[detected_format],
            decoder_id="qt-qimagereader",
            decoder_version=qVersion(),
            embedded_orientation=orientation,
        )

    @staticmethod
    def _validate_dimensions(width: int, height: int, limits: PhotoImportLimits) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("PHOTO_HAS_NO_DIMENSIONS")
        if width > limits.max_dimension_px or height > limits.max_dimension_px:
            raise ValueError("PHOTO_DIMENSION_LIMIT_EXCEEDED")
        if width * height > limits.max_decoded_pixels:
            raise ValueError("PHOTO_PIXEL_LIMIT_EXCEEDED")
