"""Compact GlyphFrame preview with explicit physical dimensions."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPaintEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from handwriting_plotter.capture.metrics import NormalizedGlyph
from handwriting_plotter.geometry.flatten import FlattenLimits, flatten_segment

from .theme import COLORS


class NormalizationPreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studio-normalization-preview")
        self.setMinimumSize(220, 170)
        self._glyph: NormalizedGlyph | None = None
        self._empty_text = ""

    @property
    def glyph(self) -> NormalizedGlyph | None:
        return self._glyph

    def set_glyph(self, glyph: NormalizedGlyph | None) -> None:
        self._glyph = glyph
        self.update()

    def set_empty_text(self, value: str) -> None:
        self._empty_text = value
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(COLORS["paper"]))
        glyph = self._glyph
        if glyph is None:
            painter.setPen(QColor("#687589"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_text)
            return

        profile = glyph.metric_profile
        top, bottom = profile.ascender_gu, profile.descender_gu
        vertical_span = max(1.0, top - bottom)
        padding_x, padding_top, padding_bottom = 14.0, 30.0, 14.0
        width = max(1.0, self.width() - 2 * padding_x)
        height = max(1.0, self.height() - padding_top - padding_bottom)

        def point(x: float, y: float) -> QPointF:
            return QPointF(
                padding_x + x / glyph.advance_gu * width,
                padding_top + (top - y) / vertical_span * height,
            )

        for y, color, style in (
            (1000.0, "#aeb7c4", Qt.PenStyle.DashLine),
            (0.0, "#687589", Qt.PenStyle.SolidLine),
            (profile.ascender_gu, "#d6d9de", Qt.PenStyle.DotLine),
            (profile.descender_gu, "#d6d9de", Qt.PenStyle.DotLine),
        ):
            painter.setPen(QPen(QColor(color), 1.0, style))
            painter.drawLine(point(0.0, y), point(glyph.advance_gu, y))

        painter.setPen(QPen(
            QColor(COLORS["accent"]), 2.2, Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
        ))
        for stroke in glyph.to_strokes():
            for segment in stroke.segments:
                lines, _ = flatten_segment(
                    segment, 0.05, FlattenLimits(max_chord_length=5.0, max_segments=100_000)
                )
                for line in lines:
                    painter.drawLine(point(line.p0.x, line.p0.y), point(line.p1.x, line.p1.y))

        advance_mm = glyph.advance_gu * glyph.preview_x_height_mm / 1000.0
        painter.setPen(QColor("#20242a"))
        painter.drawText(
            8,
            18,
            f"x-height {glyph.preview_x_height_mm:.2f} mm · advance {advance_mm:.2f} mm",
        )
