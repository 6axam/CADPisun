"""Compact GlyphFrame preview with explicit physical dimensions."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPaintEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from handwriting_plotter.capture.metrics import NormalizedGlyph
from handwriting_plotter.capture.annotation import PairJoinPreview
from handwriting_plotter.geometry.bounds import curve_bounds
from handwriting_plotter.geometry.curves import Stroke
from handwriting_plotter.geometry.flatten import FlattenLimits, flatten_segment
from handwriting_plotter.shaping.placement import place_glyph
from handwriting_plotter.shaping.resolve import GlyphMatch
from handwriting_plotter.shaping.variants import EffectiveVariation
from handwriting_plotter.styles.models import GlyphVariantFile, to_segment, to_variant
from handwriting_plotter.text.normalize import normalize

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


class JoinPairPreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studio-join-preview")
        self.setMinimumSize(220, 130)
        self._strokes: tuple[Stroke, ...] = ()
        self._connector_id: str | None = None
        self._status = ""
        self._empty_text = ""

    def set_empty_text(self, value: str) -> None:
        self._empty_text = value
        self.update()

    def clear(self) -> None:
        self._strokes = ()
        self._connector_id = None
        self._status = ""
        self.update()

    def set_pair(
        self,
        left_file: GlyphVariantFile,
        right_file: GlyphVariantFile,
        result: PairJoinPreview,
        status: str,
        *,
        x_height_mm: float = 3.5,
    ) -> None:
        left, right = to_variant(left_file), to_variant(right_file)
        left_match = GlyphMatch(left.key, normalize(left.key).graphemes, (left,), "initial", "preview:left")
        right_match = GlyphMatch(right.key, normalize(right.key).graphemes, (right,), "final", "preview:right")
        variation = EffectiveVariation(1.0, 0.0, 0.0)
        placed_left = place_glyph(left_match, left, 0.0, x_height_mm, variation)
        placed_right = place_glyph(
            right_match, right, left.advance_gu * x_height_mm / 1000.0,
            x_height_mm, variation,
        )
        strokes = [*placed_left.strokes, *placed_right.strokes]
        self._connector_id = None
        if result.connector is not None:
            connector = Stroke(
                result.connector.id,
                tuple(to_segment(segment) for segment in result.connector.segments),
                result.connector.source_refs,
                result.connector.role,
                result.connector.direction_provenance,
            )
            strokes.append(connector)
            self._connector_id = connector.id
        self._strokes = tuple(strokes)
        self._status = status
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(COLORS["paper"]))
        if not self._strokes:
            painter.setPen(QColor("#687589"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_text)
            return
        parts = [curve_bounds(segment) for stroke in self._strokes for segment in stroke.segments]
        bounds = parts[0]
        for item in parts[1:]:
            bounds = bounds.union(item)
        pad_x, top, bottom = 14.0, 30.0, 12.0
        span_x = max(0.1, bounds.max_x - bounds.min_x)
        span_y = max(3.5, bounds.max_y - bounds.min_y)
        width = max(1.0, self.width() - 2 * pad_x)
        height = max(1.0, self.height() - top - bottom)

        def point(x: float, y: float) -> QPointF:
            return QPointF(
                pad_x + (x - bounds.min_x) / span_x * width,
                top + (y - min(bounds.min_y, 0.0)) / max(span_y, bounds.max_y - min(bounds.min_y, 0.0)) * height,
            )

        painter.setPen(QPen(QColor("#aeb7c4"), 1.0, Qt.PenStyle.DashLine))
        painter.drawLine(point(bounds.min_x, 0.0), point(bounds.max_x, 0.0))
        for stroke in self._strokes:
            color = COLORS["success"] if stroke.id == self._connector_id else COLORS["accent"]
            painter.setPen(QPen(QColor(color), 2.0, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            for segment in stroke.segments:
                lines, _ = flatten_segment(segment, 0.01, FlattenLimits(max_chord_length=0.2))
                for line in lines:
                    painter.drawLine(point(line.p0.x, line.p0.y), point(line.p1.x, line.p1.y))
        painter.setPen(QColor("#20242a"))
        painter.drawText(8, 18, self._status)
