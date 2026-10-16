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
    QWheelEvent,
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
from handwriting_plotter.geometry.curves import Stroke
from handwriting_plotter.geometry.flatten import FlattenLimits, flatten_segment

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
        self._writing_guides: WritingGuides | None = None
        self._show_points = False
        self._show_directions = False
        self._processed_strokes: tuple[Stroke, ...] = ()
        self._show_raw = True
        self._show_processed = True
        self._zoom_factor = 1.0
        self._pan = QPointF()
        self._pan_origin: QPointF | None = None
        self._pan_initial = QPointF()

    @property
    def strokes(self) -> tuple[CaptureStroke, ...]:
        return tuple(self._strokes)

    @property
    def processed_strokes(self) -> tuple[Stroke, ...]:
        return self._processed_strokes

    @property
    def has_active_stroke(self) -> bool:
        return bool(self._active_points)

    @property
    def can_undo(self) -> bool:
        return not self.has_active_stroke and bool(self._strokes)

    @property
    def can_redo(self) -> bool:
        return not self.has_active_stroke and bool(self._redo)

    @property
    def coordinate_reference(self) -> CoordinateReference:
        if self._coordinate_reference is None:
            self._coordinate_reference = self._current_reference()
        return self._coordinate_reference

    @property
    def writing_guides(self) -> WritingGuides:
        if self._writing_guides is not None:
            return self._writing_guides
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

    @property
    def zoom_factor(self) -> float:
        return self._zoom_factor

    def set_writing_guides(self, guides: WritingGuides) -> None:
        height = self.coordinate_reference.height
        if not all(0 <= value <= height for value in (
            guides.ascender_y, guides.x_height_y, guides.baseline_y, guides.descender_y,
        )):
            raise ValueError("writing guides are outside capture canvas")
        self._writing_guides = guides
        self.update()

    def set_show_points(self, enabled: bool) -> None:
        self._show_points = bool(enabled)
        self.update()

    def set_show_directions(self, enabled: bool) -> None:
        self._show_directions = bool(enabled)
        self.update()

    def set_processed_strokes(self, strokes: tuple[Stroke, ...]) -> None:
        self._processed_strokes = tuple(strokes)
        self.update()

    def clear_processed(self) -> None:
        self._processed_strokes = ()
        self.update()

    def set_show_raw(self, enabled: bool) -> None:
        self._show_raw = bool(enabled)
        self.update()

    def set_show_processed(self, enabled: bool) -> None:
        self._show_processed = bool(enabled)
        self.update()

    def set_zoom_factor(self, value: float) -> None:
        value = max(0.25, min(8.0, float(value)))
        center = QPointF(self.width() / 2, self.height() / 2)
        reference = self.coordinate_reference
        old_scale_x = self.width() / reference.width * self._zoom_factor
        old_scale_y = self.height() / reference.height * self._zoom_factor
        capture_x = (center.x() - self._pan.x()) / old_scale_x
        capture_y = (center.y() - self._pan.y()) / old_scale_y
        self._zoom_factor = value
        new_scale_x = self.width() / reference.width * value
        new_scale_y = self.height() / reference.height * value
        self._pan = QPointF(center.x() - capture_x * new_scale_x, center.y() - capture_y * new_scale_y)
        self.update()

    def reset_view(self) -> None:
        self._zoom_factor = 1.0
        self._pan = QPointF()
        self.update()

    def load_sample(self, sample: CaptureSample, device: DeviceCapabilities | None = None) -> None:
        if self.has_active_stroke:
            raise ValueError("CAPTURE_STROKE_ACTIVE")
        self._strokes = list(sample.strokes)
        self._redo.clear()
        self._coordinate_reference = sample.coordinate_reference
        self._writing_guides = sample.guides
        self._observed_pointer_types = {
            point.pointer_type for stroke in sample.strokes for point in stroke.points
        }
        self._pressure_observed = any(
            point.pressure is not None for stroke in sample.strokes for point in stroke.points
        )
        if device is not None:
            self._device_name = device.device_name
            self._system_id = device.system_id
        self.reset_view()
        self._publish_change()

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
        self._writing_guides = None
        self.reset_view()
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
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_origin = event.position()
            self._pan_initial = QPointF(self._pan)
            event.accept()
            return
        if self._ignore_synthesized_mouse(event):
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._begin_pointer("mouse", event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pan_origin is not None and event.buttons() & Qt.MouseButton.MiddleButton:
            self._pan = self._pan_initial + event.position() - self._pan_origin
            self.update()
            event.accept()
            return
        if self._ignore_synthesized_mouse(event):
            event.accept()
            return
        if self._active_pointer_type == "mouse":
            self._move_pointer(event.position())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_origin is not None:
            self._pan_origin = None
            event.accept()
            return
        if self._ignore_synthesized_mouse(event):
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._active_pointer_type == "mouse":
            self._end_pointer(event.position())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
            self.set_zoom_factor(self._zoom_factor * factor)
            event.accept()
            return
        super().wheelEvent(event)

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
        if self._show_raw:
            raw_color = "#858b94" if self._processed_strokes and self._show_processed else "#20242a"
            stroke_pen = QPen(QColor(raw_color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                              Qt.PenJoinStyle.RoundJoin)
            painter.setPen(stroke_pen)
            for points in (*[stroke.points for stroke in self._strokes], tuple(self._active_points)):
                self._paint_points(painter, points)
        if self._show_processed and self._processed_strokes:
            painter.setPen(QPen(
                QColor(COLORS["accent"]), 2.4, Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
            ))
            for stroke in self._processed_strokes:
                for segment in stroke.segments:
                    lines, _ = flatten_segment(
                        segment, 0.05, FlattenLimits(max_chord_length=2.0, max_segments=100_000)
                    )
                    for line in lines:
                        painter.drawLine(
                            self._from_capture(line.p0.x, line.p0.y),
                            self._from_capture(line.p1.x, line.p1.y),
                        )

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
            painter.drawLine(self._from_capture(0, y), self._from_capture(reference.width, y))

    def _paint_points(self, painter: QPainter, points: Iterable[CapturePoint]) -> None:
        converted = [self._from_capture(point.x, point.y) for point in points]
        for first, second in zip(converted, converted[1:], strict=False):
            painter.drawLine(first, second)
        if len(converted) == 1:
            painter.drawPoint(converted[0])
        if self._show_points:
            painter.save()
            painter.setPen(QPen(QColor(COLORS["accent"]), 1.0))
            for point in converted:
                painter.drawEllipse(point, 2.2, 2.2)
            painter.restore()
        if self._show_directions and len(converted) >= 2:
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS["success"]))
            painter.drawEllipse(converted[0], 3.2, 3.2)
            painter.setBrush(QColor(COLORS["danger"]))
            painter.drawEllipse(converted[-1], 3.2, 3.2)
            painter.restore()

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
        x = max(0.0, min(
            reference.width,
            (position.x() - self._pan.x()) * reference.width / (width * self._zoom_factor),
        ))
        y = max(0.0, min(
            reference.height,
            (position.y() - self._pan.y()) * reference.height / (height * self._zoom_factor),
        ))
        return QPointF(x, y)

    def _from_capture(self, x: float, y: float) -> QPointF:
        reference = self.coordinate_reference
        return QPointF(
            x * self.width() / reference.width * self._zoom_factor + self._pan.x(),
            y * self.height() / reference.height * self._zoom_factor + self._pan.y(),
        )

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
        self._processed_strokes = ()
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
