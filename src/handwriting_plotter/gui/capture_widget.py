"""Responsive Qt pointer capture translated into the strict raw model."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable

from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QEventPoint,
    QInputDevice,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QPointingDevice,
    QTabletEvent,
)
from PySide6.QtWidgets import QWidget

from handwriting_plotter.capture.models import (
    CapturePoint,
    CaptureProvenance,
    CaptureSample,
    CaptureStroke,
    CoordinateReference,
    DeviceCapabilities,
    PointerType,
    WritingGuides,
)

from .theme import COLORS

_SYNTHETIC_MOUSE_GUARD_NS = 250_000_000
_POINTER_ORDER: tuple[PointerType, ...] = ("mouse", "pen", "eraser", "touch", "unknown")


class HandwritingCaptureWidget(QWidget):
    """Collect unprocessed directed strokes in a fixed logical-pixel frame."""

    strokes_changed = Signal(int, int)
    stroke_finished = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("handwriting-capture-canvas")
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 240)
        self._strokes: list[CaptureStroke] = []
        self._redo: list[CaptureStroke] = []
        self._active_points: list[CapturePoint] = []
        self._active_pointer_type: PointerType | None = None
        self._active_touch_id: int | None = None
        self._active_pressure: float | None = None
        self._coordinate_reference: CoordinateReference | None = None
        self._clock_origin_ns = time.monotonic_ns()
        self._suppress_synthesized_mouse_until_ns = 0
        self._observed_pointer_types: set[PointerType] = set()
        self._pressure_observed = False
        self._device_name: str | None = None
        self._system_id: str | None = None

    @property
    def strokes(self) -> tuple[CaptureStroke, ...]:
        return tuple(self._strokes)

    @property
    def has_active_stroke(self) -> bool:
        return bool(self._active_points)

    @property
    def coordinate_reference(self) -> CoordinateReference:
        if self._coordinate_reference is None:
            self._coordinate_reference = self._current_reference()
        return self._coordinate_reference

    @property
    def writing_guides(self) -> WritingGuides:
        height = self.coordinate_reference.height
        return WritingGuides(
            ascender_y=height * 0.18,
            x_height_y=height * 0.35,
            baseline_y=height * 0.70,
            descender_y=height * 0.85,
        )

    @property
    def device_capabilities(self) -> DeviceCapabilities:
        pointers = tuple(item for item in _POINTER_ORDER if item in self._observed_pointer_types)
        return DeviceCapabilities(
            pointer_types=pointers or ("mouse",),
            pressure=self._pressure_observed,
            device_name=self._device_name,
            system_id=self._system_id,
        )

    def build_sample(
        self,
        *,
        sample_id: str,
        label: str,
        classification: str,
        provenance: CaptureProvenance,
    ) -> CaptureSample:
        if self.has_active_stroke:
            raise ValueError("CAPTURE_STROKE_ACTIVE")
        return CaptureSample(
            sample_id=sample_id,
            label=label,
            classification=classification,
            coordinate_reference=self.coordinate_reference,
            guides=self.writing_guides,
            provenance=provenance,
            strokes=self.strokes,
        )

    def clear(self) -> None:
        self._strokes.clear()
        self._redo.clear()
        self._active_points.clear()
        self._active_pointer_type = None
        self._active_touch_id = None
        self._active_pressure = None
        self._coordinate_reference = None
        self._clock_origin_ns = time.monotonic_ns()
        self._observed_pointer_types.clear()
        self._pressure_observed = False
        self._device_name = None
        self._system_id = None
        self._publish_change()

    def undo_stroke(self) -> bool:
        if self.has_active_stroke or not self._strokes:
            return False
        self._redo.append(self._strokes.pop())
        self._publish_change()
        return True

    def redo_stroke(self) -> bool:
        if self.has_active_stroke or not self._redo:
            return False
        self._strokes.append(self._redo.pop())
        self._publish_change()
        return True

    def cancel_active_stroke(self) -> bool:
        return self._finish_pointer("cancel", "cancelled")

    def interrupt_active_stroke(self) -> bool:
        return self._finish_pointer("move", "interrupted")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._ignore_synthesized_mouse(event):
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._begin_pointer("mouse", event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._ignore_synthesized_mouse(event):
            event.accept()
            return
        if self._active_pointer_type == "mouse":
            self._move_pointer(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._ignore_synthesized_mouse(event):
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._active_pointer_type == "mouse":
            self._end_pointer(event.position())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def tabletEvent(self, event: QTabletEvent) -> None:  # noqa: N802
        pointer_type = self._tablet_pointer_type(event)
        pressure = self._event_pressure(event)
        self._observe_device(event, pointer_type, pressure is not None)
        self._suppress_synthesized_mouse_until_ns = time.monotonic_ns() + _SYNTHETIC_MOUSE_GUARD_NS
        if event.type() == QEvent.Type.TabletPress:
            self._begin_pointer(pointer_type, event.position(), pressure=pressure)
        elif event.type() == QEvent.Type.TabletMove and self._active_pointer_type == pointer_type:
            self._move_pointer(event.position(), pressure=pressure)
        elif event.type() == QEvent.Type.TabletRelease and self._active_pointer_type == pointer_type:
            self._end_pointer(event.position(), pressure=pressure)
        event.accept()

    def event(self, event: QEvent) -> bool:
        if event.type() in {
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
            QEvent.Type.TouchCancel,
        }:
            self._handle_touch_event(event)
            event.accept()
            return True
        return super().event(event)

    def focusOutEvent(self, event) -> None:  # noqa: ANN001, N802
        self.interrupt_active_stroke()
        super().focusOutEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(COLORS["paper"]))
        self._paint_guides(painter)
        stroke_pen = QPen(QColor("#20242a"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin)
        painter.setPen(stroke_pen)
        for points in (*[stroke.points for stroke in self._strokes], tuple(self._active_points)):
            self._paint_points(painter, points)

    def _paint_guides(self, painter: QPainter) -> None:
        reference = self.coordinate_reference
        guides = self.writing_guides
        for y, color, style in (
            (guides.ascender_y, "#d6d9de", Qt.PenStyle.DashLine),
            (guides.x_height_y, "#aeb7c4", Qt.PenStyle.DashLine),
            (guides.baseline_y, "#687589", Qt.PenStyle.SolidLine),
            (guides.descender_y, "#d6d9de", Qt.PenStyle.DashLine),
        ):
            painter.setPen(QPen(QColor(color), 1.0, style))
            display_y = y * self.height() / reference.height
            painter.drawLine(QPointF(0, display_y), QPointF(self.width(), display_y))

    def _paint_points(self, painter: QPainter, points: Iterable[CapturePoint]) -> None:
        converted = [self._from_capture(point.x, point.y) for point in points]
        for first, second in zip(converted, converted[1:], strict=False):
            painter.drawLine(first, second)
        if len(converted) == 1:
            painter.drawPoint(converted[0])

    def _begin_pointer(
        self,
        pointer_type: PointerType,
        position: QPointF,
        *,
        pressure: float | None = None,
    ) -> bool:
        if self.has_active_stroke:
            return False
        if self._coordinate_reference is None:
            self._coordinate_reference = self._current_reference()
        self._active_pointer_type = pointer_type
        self._active_pressure = pressure
        self._observed_pointer_types.add(pointer_type)
        self._pressure_observed |= pressure is not None
        self._redo.clear()
        self._active_points = [self._point("down", position, pointer_type, pressure)]
        self.update()
        return True

    def _move_pointer(self, position: QPointF, *, pressure: float | None = None) -> bool:
        if not self.has_active_stroke or self._active_pointer_type is None:
            return False
        self._active_pressure = pressure
        self._pressure_observed |= pressure is not None
        self._active_points.append(self._point("move", position, self._active_pointer_type, pressure))
        self.update()
        return True

    def _end_pointer(self, position: QPointF, *, pressure: float | None = None) -> bool:
        if not self.has_active_stroke or self._active_pointer_type is None:
            return False
        self._active_pressure = pressure
        self._pressure_observed |= pressure is not None
        self._active_points.append(self._point("up", position, self._active_pointer_type, pressure))
        return self._commit_active("completed")

    def _finish_pointer(self, event_type: str, termination: str) -> bool:
        if not self.has_active_stroke or self._active_pointer_type is None:
            return False
        last = self._active_points[-1]
        self._active_points.append(CapturePoint(
            point_id=self._new_id("point"),
            event=event_type,
            x=last.x,
            y=last.y,
            elapsed_s=self._elapsed_s(),
            pressure=self._active_pressure,
            pointer_type=self._active_pointer_type,
        ))
        return self._commit_active(termination)

    def _commit_active(self, termination: str) -> bool:
        stroke = CaptureStroke(
            stroke_id=self._new_id("stroke"),
            points=tuple(self._active_points),
            termination=termination,
        )
        self._strokes.append(stroke)
        self._active_points = []
        self._active_pointer_type = None
        self._active_touch_id = None
        self._active_pressure = None
        self.stroke_finished.emit(stroke)
        self._publish_change()
        return True

    def _point(
        self,
        event_type: str,
        position: QPointF,
        pointer_type: PointerType,
        pressure: float | None,
    ) -> CapturePoint:
        captured = self._to_capture(position)
        return CapturePoint(
            point_id=self._new_id("point"),
            event=event_type,
            x=captured.x(),
            y=captured.y(),
            elapsed_s=self._elapsed_s(),
            pressure=pressure,
            pointer_type=pointer_type,
        )

    def _to_capture(self, position: QPointF) -> QPointF:
        reference = self.coordinate_reference
        width = max(1, self.width())
        height = max(1, self.height())
        x = max(0.0, min(reference.width, position.x() * reference.width / width))
        y = max(0.0, min(reference.height, position.y() * reference.height / height))
        return QPointF(x, y)

    def _from_capture(self, x: float, y: float) -> QPointF:
        reference = self.coordinate_reference
        return QPointF(x * self.width() / reference.width, y * self.height() / reference.height)

    def _current_reference(self) -> CoordinateReference:
        return CoordinateReference(
            width=float(max(1, self.width())),
            height=float(max(1, self.height())),
            device_pixel_ratio=float(self.devicePixelRatioF()),
        )

    def _elapsed_s(self) -> float:
        return (time.monotonic_ns() - self._clock_origin_ns) / 1_000_000_000

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"

    def _publish_change(self) -> None:
        point_count = sum(len(stroke.points) for stroke in self._strokes) + len(self._active_points)
        self.strokes_changed.emit(len(self._strokes), point_count)
        self.update()

    def _ignore_synthesized_mouse(self, event: QMouseEvent) -> bool:
        return (
            event.source() != Qt.MouseEventSource.MouseEventNotSynthesized
            and time.monotonic_ns() <= self._suppress_synthesized_mouse_until_ns
        )

    @staticmethod
    def _tablet_pointer_type(event: QTabletEvent) -> PointerType:
        pointer = event.pointerType()
        if pointer == QPointingDevice.PointerType.Pen:
            return "pen"
        if pointer == QPointingDevice.PointerType.Eraser:
            return "eraser"
        return "unknown"

    @staticmethod
    def _has_pressure_capability(event) -> bool:  # noqa: ANN001
        device = event.pointingDevice()
        return bool(device.capabilities() & QInputDevice.Capability.Pressure)

    def _event_pressure(self, event) -> float | None:  # noqa: ANN001
        if not self._has_pressure_capability(event):
            return None
        return max(0.0, min(1.0, float(event.pressure())))

    def _observe_device(self, event, pointer_type: PointerType, pressure: bool) -> None:  # noqa: ANN001
        self._observed_pointer_types.add(pointer_type)
        self._pressure_observed |= pressure
        device = event.pointingDevice()
        name = device.name()
        self._device_name = name or self._device_name
        system_id = device.systemId()
        self._system_id = str(system_id) if system_id is not None else self._system_id

    def _handle_touch_event(self, event) -> None:  # noqa: ANN001
        self._suppress_synthesized_mouse_until_ns = time.monotonic_ns() + _SYNTHETIC_MOUSE_GUARD_NS
        points = event.points()
        pressure_supported = self._has_pressure_capability(event)
        if event.type() == QEvent.Type.TouchBegin and not self.has_active_stroke:
            pressed = next((point for point in points if point.state() & QEventPoint.State.Pressed), None)
            if pressed is not None:
                self._active_touch_id = pressed.id()
                pressure = float(pressed.pressure()) if pressure_supported else None
                self._observe_device(event, "touch", pressure_supported)
                self._begin_pointer("touch", pressed.position(), pressure=pressure)
            return
        point = next((item for item in points if item.id() == self._active_touch_id), None)
        if event.type() == QEvent.Type.TouchCancel:
            self.cancel_active_stroke()
        elif point is not None and event.type() == QEvent.Type.TouchEnd:
            pressure = float(point.pressure()) if pressure_supported else None
            self._end_pointer(point.position(), pressure=pressure)
        elif point is not None and event.type() == QEvent.Type.TouchUpdate:
            pressure = float(point.pressure()) if pressure_supported else None
            self._move_pointer(point.position(), pressure=pressure)

