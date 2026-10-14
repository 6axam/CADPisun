"""Physical A4 canvas for backend-produced SVG artifacts."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QByteArray, QPointF, QRectF, Signal, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)

from .theme import COLORS


OBJECT_ID_ROLE = 0


class SvgPageItem(QGraphicsItem):
    """Render an SVG into an explicit millimetre-sized scene rectangle."""

    def __init__(self, svg: bytes, page_rect: QRectF, parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self._rect = QRectF(page_rect)
        self._renderer = QSvgRenderer(QByteArray(svg))
        if not self._renderer.isValid():
            raise ValueError("INVALID_SVG_ARTIFACT")
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API
        return self._rect

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: ANN001
        self._renderer.render(painter, self._rect)


class PageCanvas(QGraphicsView):
    """A zoomable scene whose coordinates are physical millimetres."""

    selection_changed = Signal(object)

    PAGE_WIDTH_MM = 210.0
    PAGE_HEIGHT_MM = 297.0

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        scene = QGraphicsScene(parent)
        super().__init__(scene, parent)
        self._scene = scene
        self.setObjectName("page-canvas")
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setBackgroundBrush(QColor(COLORS["window"]))
        self._fit_mode = True
        self._production_item: SvgPageItem | None = None
        self._preview_item: SvgPageItem | None = None
        self._marker_items: list[QGraphicsItem] = []
        self._object_frames: dict[str, QGraphicsRectItem] = {}
        self._selected_object_ids: set[str] = set()
        self._selection_origin: QPointF | None = None
        self._selection_current: QPointF | None = None
        self._selection_additive = False
        self._pressed_object_id: str | None = None
        self._selection_item = QGraphicsRectItem()
        self._selection_item.setBrush(Qt.BrushStyle.NoBrush)
        self._selection_item.setZValue(20)
        self._selection_item.hide()
        self.scene().addItem(self._selection_item)
        self._show_travel = False
        self._show_markers = False
        self._page_rect = QRectF(0.0, 0.0, self.PAGE_WIDTH_MM, self.PAGE_HEIGHT_MM)
        self._build_page()

    @property
    def page_rect_mm(self) -> QRectF:
        return QRectF(self._page_rect)

    @property
    def has_artifact(self) -> bool:
        return self._production_item is not None

    @property
    def zoom_factor(self) -> float:
        return self.transform().m11()

    def _build_page(self) -> None:
        self.scene().setSceneRect(-25.0, -25.0, self.PAGE_WIDTH_MM + 50.0, self.PAGE_HEIGHT_MM + 50.0)
        paper = QGraphicsRectItem(self._page_rect)
        paper.setBrush(QColor(COLORS["paper"]))
        paper.setPen(QPen(QColor("#c7c9ce"), 0.25))
        paper.setZValue(0)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 120))
        paper.setGraphicsEffect(shadow)
        self.scene().addItem(paper)
        self._paper_item = paper
        self.set_margins(15.0, 15.0, 15.0, 15.0)

    def set_margins(self, left: float, top: float, right: float, bottom: float) -> None:
        rect = QRectF(left, top, self.PAGE_WIDTH_MM - left - right, self.PAGE_HEIGHT_MM - top - bottom)
        if hasattr(self, "_margin_item"):
            self._margin_item.setRect(rect)
            return
        margin = QGraphicsRectItem(rect)
        pen = QPen(QColor("#8ba1bd"), 0.25, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        margin.setPen(pen)
        margin.setBrush(Qt.BrushStyle.NoBrush)
        margin.setZValue(1)
        self.scene().addItem(margin)
        self._margin_item = margin

    def set_artifacts(self, production_svg: bytes, preview_svg: bytes, plan_json: bytes | None = None) -> None:
        self.clear_artifacts()
        self._production_item = SvgPageItem(production_svg, self._page_rect)
        self._production_item.setZValue(2)
        self.scene().addItem(self._production_item)
        self._preview_item = SvgPageItem(preview_svg, self._page_rect)
        self._preview_item.setZValue(3)
        self.scene().addItem(self._preview_item)
        if plan_json:
            self._add_markers(json.loads(plan_json))
        self._sync_layer_visibility()

    def clear_artifacts(self) -> None:
        for item in (self._production_item, self._preview_item, *self._marker_items):
            if item is not None and item.scene() is self.scene():
                self.scene().removeItem(item)
        self._production_item = None
        self._preview_item = None
        self._marker_items.clear()

    def set_object_frames(self, objects, selected_ids=()) -> None:  # noqa: ANN001
        for item in self._object_frames.values():
            if item.scene() is self.scene():
                self.scene().removeItem(item)
        self._object_frames.clear()
        self._selected_object_ids = set(selected_ids)
        for obj in objects:
            if not obj.visible:
                continue
            frame = QGraphicsRectItem(
                obj.frame_x_mm,
                obj.frame_y_mm,
                obj.frame_width_mm,
                obj.frame_height_mm,
            )
            frame.setData(OBJECT_ID_ROLE, obj.object_id)
            frame.setBrush(Qt.BrushStyle.NoBrush)
            frame.setZValue(8)
            self.scene().addItem(frame)
            self._object_frames[obj.object_id] = frame
        self._sync_object_frame_styles()

    def set_selected_objects(self, object_ids) -> None:  # noqa: ANN001
        self._selected_object_ids = set(object_ids)
        self._sync_object_frame_styles()

    def _sync_object_frame_styles(self) -> None:
        for object_id, frame in self._object_frames.items():
            selected = object_id in self._selected_object_ids
            color = QColor(COLORS["accent"] if selected else COLORS["muted"])
            color.setAlpha(255 if selected else 105)
            pen = QPen(color, 0.45 if selected else 0.25,
                       Qt.PenStyle.SolidLine if selected else Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            frame.setPen(pen)

    def _object_at(self, point: QPointF) -> str | None:
        for object_id, frame in reversed(tuple(self._object_frames.items())):
            if frame.sceneBoundingRect().contains(point):
                return object_id
        return None

    def _objects_in_selection(self, rect: QRectF, *, crossing: bool) -> set[str]:
        normalized = rect.normalized()
        selected: set[str] = set()
        for object_id, frame in self._object_frames.items():
            bounds = frame.sceneBoundingRect()
            if (crossing and normalized.intersects(bounds)) or (not crossing and normalized.contains(bounds)):
                selected.add(object_id)
        return selected

    def _publish_selection(self, object_ids: set[str]) -> None:
        self.set_selected_objects(object_ids)
        self.selection_changed.emit(tuple(sorted(object_ids)))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.dragMode() == QGraphicsView.DragMode.NoDrag:
            point = self.mapToScene(event.position().toPoint())
            self._selection_origin = point
            self._selection_current = point
            self._selection_additive = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self._pressed_object_id = self._object_at(point)
            self._selection_item.setRect(QRectF(point, point))
            self._selection_item.hide()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._selection_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._selection_current = self.mapToScene(event.position().toPoint())
            rect = QRectF(self._selection_origin, self._selection_current).normalized()
            if rect.width() >= 0.5 or rect.height() >= 0.5:
                crossing = self._selection_current.x() < self._selection_origin.x()
                color = QColor("#36c48d" if crossing else COLORS["accent"])
                color.setAlpha(210)
                pen = QPen(color, 0.3, Qt.PenStyle.DashLine if crossing else Qt.PenStyle.SolidLine)
                pen.setCosmetic(True)
                self._selection_item.setPen(pen)
                self._selection_item.setRect(rect)
                self._selection_item.show()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._selection_origin is not None:
            end = self.mapToScene(event.position().toPoint())
            rect = QRectF(self._selection_origin, end).normalized()
            dragged = rect.width() >= 0.5 or rect.height() >= 0.5
            if dragged:
                selected = self._objects_in_selection(
                    rect,
                    crossing=end.x() < self._selection_origin.x(),
                )
                if self._selection_additive:
                    selected |= self._selected_object_ids
            elif self._pressed_object_id is not None:
                selected = set(self._selected_object_ids) if self._selection_additive else set()
                if self._selection_additive and self._pressed_object_id in selected:
                    selected.remove(self._pressed_object_id)
                else:
                    selected.add(self._pressed_object_id)
            else:
                selected = set(self._selected_object_ids) if self._selection_additive else set()
            self._selection_item.hide()
            self._selection_origin = None
            self._selection_current = None
            self._pressed_object_id = None
            self._publish_selection(selected)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_show_travel(self, visible: bool) -> None:
        self._show_travel = visible
        self._sync_layer_visibility()

    def set_show_markers(self, visible: bool) -> None:
        self._show_markers = visible
        self._sync_layer_visibility()

    def _sync_layer_visibility(self) -> None:
        if self._production_item:
            self._production_item.setVisible(not self._show_travel)
        if self._preview_item:
            self._preview_item.setVisible(self._show_travel)
        for item in self._marker_items:
            item.setVisible(self._show_markers)

    def _add_markers(self, plan: dict[str, Any]) -> None:
        points: list[QPointF] = []
        for operation in plan.get("operations", []):
            if operation.get("op") == "travel_to":
                target = operation.get("target", {})
                points.append(QPointF(float(target["x"]), float(target["y"])))
            elif operation.get("op") == "draw":
                for segment in operation.get("segments", []):
                    end = segment.get("p3") or segment.get("p1")
                    if end:
                        points.append(QPointF(float(end["x"]), float(end["y"])))
        if not points:
            return
        for point, color in ((points[0], "#36c48d"), (points[-1], "#ef6b73")):
            marker = QGraphicsEllipseItem(point.x() - 1.4, point.y() - 1.4, 2.8, 2.8)
            marker.setPen(QPen(QColor("#ffffff"), 0.35))
            marker.setBrush(QColor(color))
            marker.setZValue(5)
            marker.setVisible(self._show_markers)
            self.scene().addItem(marker)
            self._marker_items.append(marker)

    def zoom_to_fit(self) -> None:
        self.fitInView(self._page_rect.adjusted(-8.0, -8.0, 8.0, 8.0), Qt.AspectRatioMode.KeepAspectRatio)
        self._fit_mode = True

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt API
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
            candidate = self.zoom_factor * factor
            if 0.25 <= candidate <= 20.0:
                self.scale(factor, factor)
                self._fit_mode = False
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: ANN001, N802
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        if self._fit_mode:
            self.zoom_to_fit()
