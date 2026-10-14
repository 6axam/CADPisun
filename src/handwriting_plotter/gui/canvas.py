"""Physical A4 canvas for backend-produced SVG artifacts."""

from __future__ import annotations

import json
import math
import time
from collections import deque
from typing import Any, ClassVar

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from .document import GridObject, TextObject
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


class GridPageItem(QGraphicsItem):
    """Paint a configurable layout grid without adding it to production artifacts."""

    _STYLES: ClassVar[dict[str, Qt.PenStyle]] = {
        "solid": Qt.PenStyle.SolidLine,
        "dashed": Qt.PenStyle.DashLine,
        "dash_dot": Qt.PenStyle.DashDotLine,
    }

    def __init__(self, grid: GridObject) -> None:
        super().__init__()
        self.grid = grid
        self._rect = QRectF(grid.x_mm, grid.y_mm, grid.width_mm, grid.height_mm)

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(self._rect)

    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: ANN001
        color = QColor(self.grid.color)
        color.setAlpha(175)
        pen = QPen(color, 0.0, self._STYLES[self.grid.line_style])
        pen.setCosmetic(True)
        painter.setPen(pen)
        right = self._rect.right()
        bottom = self._rect.bottom()
        x = self._rect.left()
        while x <= right + 1e-9:
            painter.drawLine(QPointF(x, self._rect.top()), QPointF(x, bottom))
            x += self.grid.cell_width_mm
        y = self._rect.top()
        while y <= bottom + 1e-9:
            painter.drawLine(QPointF(self._rect.left(), y), QPointF(right, y))
            y += self.grid.cell_height_mm


class PageCanvas(QGraphicsView):
    """A zoomable scene whose coordinates are physical millimetres."""

    selection_changed = Signal(object)
    objects_moved = Signal(object, float, float)
    cursor_position_changed = Signal(object)
    fps_changed = Signal(float)

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
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setBackgroundBrush(QColor(COLORS["window"]))
        self._paint_timestamps: deque[float] = deque()
        self._fps_timer = QTimer(self)
        self._fps_timer.setInterval(500)
        self._fps_timer.timeout.connect(self._publish_fps)
        self._fps_timer.start()
        self._fit_mode = True
        self._production_item: SvgPageItem | None = None
        self._preview_item: SvgPageItem | None = None
        self._marker_items: list[QGraphicsItem] = []
        self._object_frames: dict[str, QGraphicsRectItem] = {}
        self._object_models: dict[str, object] = {}
        self._grid_items: dict[str, GridPageItem] = {}
        self._selected_object_ids: set[str] = set()
        self._selection_origin: QPointF | None = None
        self._selection_current: QPointF | None = None
        self._selection_additive = False
        self._selection_initial_ids: set[str] = set()
        self._pressed_object_id: str | None = None
        self._move_initial_rects: dict[str, QRectF] = {}
        self._move_delta = QPointF()
        self._selection_item = QGraphicsRectItem()
        self._selection_item.setBrush(Qt.BrushStyle.NoBrush)
        self._selection_item.setZValue(20)
        self._selection_item.hide()
        self.scene().addItem(self._selection_item)
        self._show_travel = False
        self._show_markers = False
        self._preview_is_stale = False
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

    @property
    def preview_is_stale(self) -> bool:
        return self._preview_is_stale

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
        self._stale_banner_item = QGraphicsRectItem(12.0, 8.0, 186.0, 13.0)
        self._stale_banner_item.setBrush(QColor(245, 158, 11, 225))
        self._stale_banner_item.setPen(QPen(Qt.PenStyle.NoPen))
        self._stale_banner_item.setZValue(30)
        self._stale_banner_item.hide()
        self.scene().addItem(self._stale_banner_item)
        self._stale_banner_text = QGraphicsSimpleTextItem("PREVIEW OUT OF DATE · GENERATE PAGE")
        font = QFont()
        font.setPointSizeF(4.5)
        font.setBold(True)
        self._stale_banner_text.setFont(font)
        self._stale_banner_text.setBrush(QColor("#201600"))
        self._stale_banner_text.setPos(17.0, 9.1)
        self._stale_banner_text.setZValue(31)
        self._stale_banner_text.hide()
        self.scene().addItem(self._stale_banner_text)

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
        self.set_preview_stale(False)

    def set_preview_stale(self, stale: bool, label: str | None = None) -> None:
        self._preview_is_stale = bool(stale and self.has_artifact)
        if label is not None:
            self._stale_banner_text.setText(label)
        opacity = 0.38 if self._preview_is_stale else 1.0
        for item in (self._production_item, self._preview_item):
            if item is not None:
                item.setOpacity(opacity)
        self._stale_banner_item.setVisible(self._preview_is_stale)
        self._stale_banner_text.setVisible(self._preview_is_stale)

    def set_object_frames(self, objects, selected_ids=()) -> None:  # noqa: ANN001
        for item in self._object_frames.values():
            if item.scene() is self.scene():
                self.scene().removeItem(item)
        self._object_frames.clear()
        self._object_models.clear()
        for item in self._grid_items.values():
            if item.scene() is self.scene():
                self.scene().removeItem(item)
        self._grid_items.clear()
        self._selected_object_ids = set(selected_ids)
        ordered_objects = sorted(objects, key=lambda obj: 0 if isinstance(obj, GridObject) else 1)
        for obj in ordered_objects:
            if not obj.visible:
                continue
            if isinstance(obj, GridObject):
                grid_item = GridPageItem(obj)
                grid_item.setZValue(4)
                self.scene().addItem(grid_item)
                self._grid_items[obj.object_id] = grid_item
            bounds = self._object_rect(obj)
            frame = QGraphicsRectItem(bounds)
            frame.setData(OBJECT_ID_ROLE, obj.object_id)
            frame.setBrush(Qt.BrushStyle.NoBrush)
            frame.setZValue(8)
            self.scene().addItem(frame)
            self._object_frames[obj.object_id] = frame
            self._object_models[obj.object_id] = obj
        self._sync_object_frame_styles()

    @staticmethod
    def _object_rect(obj: object) -> QRectF:
        if isinstance(obj, TextObject):
            return QRectF(obj.frame_x_mm, obj.frame_y_mm, obj.frame_width_mm, obj.frame_height_mm)
        if isinstance(obj, GridObject):
            return QRectF(obj.x_mm, obj.y_mm, obj.width_mm, obj.height_mm)
        raise TypeError(type(obj).__name__)

    def set_selected_objects(self, object_ids) -> None:  # noqa: ANN001
        self._selected_object_ids = set(object_ids)
        self._sync_object_frame_styles()

    def _sync_object_frame_styles(self) -> None:
        for object_id, frame in self._object_frames.items():
            selected = object_id in self._selected_object_ids
            is_grid = isinstance(self._object_models[object_id], GridObject)
            color = QColor(COLORS["accent"] if selected else COLORS["muted"])
            color.setAlpha(255 if selected else (0 if is_grid else 105))
            pen = QPen(
                color,
                0.45 if selected else 0.25,
                Qt.PenStyle.SolidLine if selected else Qt.PenStyle.DashLine,
            )
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

    def _constrain_move_delta(self, object_ids: set[str], dx: float, dy: float) -> QPointF:
        models = [self._object_models[object_id] for object_id in object_ids]
        rects = [self._object_rect(model) for model in models]
        minimum_dx = max(-rect.left() for rect in rects)
        maximum_dx = min(self.PAGE_WIDTH_MM - rect.right() for rect in rects)
        minimum_dy = max(-rect.top() for rect in rects)
        maximum_dy = min(self.PAGE_HEIGHT_MM - rect.bottom() for rect in rects)
        for model in models:
            if isinstance(model, TextObject):
                minimum_dx = max(minimum_dx, -model.x_mm)
                maximum_dx = min(maximum_dx, self.PAGE_WIDTH_MM - model.x_mm - 0.01)
                minimum_dy = max(minimum_dy, -model.y_mm)
                maximum_dy = min(maximum_dy, self.PAGE_HEIGHT_MM - model.y_mm - 0.01)
        return QPointF(max(minimum_dx, min(maximum_dx, dx)), max(minimum_dy, min(maximum_dy, dy)))

    @staticmethod
    def _axis_lines(start: float, extent: float, cell: float) -> tuple[float, ...]:
        return tuple(start + index * cell for index in range(math.floor(extent / cell) + 1))

    def _snap_move_delta(self, object_ids: set[str], delta: QPointF) -> QPointF:
        grids = [
            model for object_id, model in self._object_models.items()
            if object_id not in object_ids and isinstance(model, GridObject) and model.snap_enabled
        ]
        moving = [self._object_rect(self._object_models[object_id]).translated(delta) for object_id in object_ids]
        x_adjustments: list[float] = []
        y_adjustments: list[float] = []
        for grid in grids:
            x_lines = self._axis_lines(grid.x_mm, grid.width_mm, grid.cell_width_mm)
            y_lines = self._axis_lines(grid.y_mm, grid.height_mm, grid.cell_height_mm)
            for rect in moving:
                for anchor in (rect.left(), rect.center().x(), rect.right()):
                    x_adjustments.extend(line - anchor for line in x_lines if abs(line - anchor) <= 1.5)
                for anchor in (rect.top(), rect.center().y(), rect.bottom()):
                    y_adjustments.extend(line - anchor for line in y_lines if abs(line - anchor) <= 1.5)
        x_adjust = min(x_adjustments, key=abs) if x_adjustments else 0.0
        y_adjust = min(y_adjustments, key=abs) if y_adjustments else 0.0
        return QPointF(delta.x() + x_adjust, delta.y() + y_adjust)

    def _preview_move(self, end: QPointF) -> None:
        if self._selection_origin is None or not self._move_initial_rects:
            return
        raw_delta = end - self._selection_origin
        constrained = self._constrain_move_delta(
            set(self._move_initial_rects), raw_delta.x(), raw_delta.y()
        )
        snapped = self._snap_move_delta(set(self._move_initial_rects), constrained)
        self._move_delta = self._constrain_move_delta(
            set(self._move_initial_rects), snapped.x(), snapped.y()
        )
        for object_id, initial in self._move_initial_rects.items():
            self._object_frames[object_id].setRect(initial.translated(self._move_delta))

    def _reset_pointer_operation(self) -> None:
        self._selection_item.hide()
        self._selection_origin = None
        self._selection_current = None
        self._selection_initial_ids.clear()
        self._pressed_object_id = None
        self._move_initial_rects.clear()
        self._move_delta = QPointF()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.dragMode() == QGraphicsView.DragMode.NoDrag:
            point = self.mapToScene(event.position().toPoint())
            self._selection_origin = point
            self._selection_current = point
            self._selection_additive = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self._selection_initial_ids = set(self._selected_object_ids)
            self._pressed_object_id = self._object_at(point)
            if self._pressed_object_id is not None:
                selected = set(self._selected_object_ids)
                if self._pressed_object_id not in selected:
                    selected = selected | {self._pressed_object_id} if self._selection_additive else {self._pressed_object_id}
                    self._publish_selection(selected)
                self._move_initial_rects = {
                    object_id: QRectF(self._object_frames[object_id].rect())
                    for object_id in selected
                    if object_id in self._object_frames
                }
            self._selection_item.setRect(QRectF(point, point))
            self._selection_item.hide()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        scene_point = self.mapToScene(event.position().toPoint())
        self.cursor_position_changed.emit(
            QPointF(scene_point) if self._page_rect.contains(scene_point) else None
        )
        if self._selection_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._selection_current = scene_point
            rect = QRectF(self._selection_origin, self._selection_current).normalized()
            if rect.width() >= 0.5 or rect.height() >= 0.5:
                if self._move_initial_rects:
                    self._preview_move(self._selection_current)
                    event.accept()
                    return
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

    def leaveEvent(self, event) -> None:  # noqa: ANN001, N802
        self.cursor_position_changed.emit(None)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._selection_origin is not None:
            end = self.mapToScene(event.position().toPoint())
            rect = QRectF(self._selection_origin, end).normalized()
            dragged = rect.width() >= 0.5 or rect.height() >= 0.5
            if dragged and self._move_initial_rects:
                self._preview_move(end)
                moved_ids = tuple(sorted(self._move_initial_rects))
                dx, dy = self._move_delta.x(), self._move_delta.y()
                self._reset_pointer_operation()
                if abs(dx) > 1e-9 or abs(dy) > 1e-9:
                    self.objects_moved.emit(moved_ids, dx, dy)
                event.accept()
                return
            if dragged:
                selected = self._objects_in_selection(
                    rect,
                    crossing=end.x() < self._selection_origin.x(),
                )
                if self._selection_additive:
                    selected |= self._selection_initial_ids
            elif self._pressed_object_id is not None:
                selected = set(self._selection_initial_ids) if self._selection_additive else set()
                if self._selection_additive and self._pressed_object_id in selected:
                    selected.remove(self._pressed_object_id)
                else:
                    selected.add(self._pressed_object_id)
            else:
                selected = set(self._selection_initial_ids) if self._selection_additive else set()
            self._reset_pointer_operation()
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

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        super().paintEvent(event)
        now = time.monotonic()
        self._paint_timestamps.append(now)
        self._prune_paint_timestamps(now)

    def _prune_paint_timestamps(self, now: float) -> None:
        while self._paint_timestamps and now - self._paint_timestamps[0] > 1.0:
            self._paint_timestamps.popleft()

    def _publish_fps(self) -> None:
        now = time.monotonic()
        self._prune_paint_timestamps(now)
        if len(self._paint_timestamps) < 2:
            fps = 0.0
        else:
            elapsed = self._paint_timestamps[-1] - self._paint_timestamps[0]
            fps = (len(self._paint_timestamps) - 1) / elapsed if elapsed > 0 else 0.0
        self.fps_changed.emit(fps)
