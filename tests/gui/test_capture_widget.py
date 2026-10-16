from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from handwriting_plotter.capture.models import CaptureProvenance
from handwriting_plotter.gui.capture_widget import HandwritingCaptureWidget


def _mouse_event(
    event_type: QEvent.Type,
    position: QPointF,
    *,
    button: Qt.MouseButton,
    buttons: Qt.MouseButton,
    source: Qt.MouseEventSource = Qt.MouseEventSource.MouseEventNotSynthesized,
) -> QMouseEvent:
    return QMouseEvent(
        event_type,
        position,
        position,
        position,
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
        source,
    )


def _draw_mouse_stroke(widget: HandwritingCaptureWidget, points: tuple[QPointF, ...]) -> None:
    QApplication.sendEvent(widget, _mouse_event(
        QEvent.Type.MouseButtonPress, points[0], button=Qt.MouseButton.LeftButton,
        buttons=Qt.MouseButton.LeftButton,
    ))
    for point in points[1:-1]:
        QApplication.sendEvent(widget, _mouse_event(
            QEvent.Type.MouseMove, point, button=Qt.MouseButton.NoButton,
            buttons=Qt.MouseButton.LeftButton,
        ))
    QApplication.sendEvent(widget, _mouse_event(
        QEvent.Type.MouseButtonRelease, points[-1], button=Qt.MouseButton.LeftButton,
        buttons=Qt.MouseButton.NoButton,
    ))


def test_mouse_capture_preserves_two_directed_strokes(qtbot) -> None:
    widget = HandwritingCaptureWidget()
    widget.resize(640, 480)
    qtbot.addWidget(widget)
    widget.show()

    _draw_mouse_stroke(widget, (QPointF(20, 300), QPointF(30, 250), QPointF(40, 200)))
    _draw_mouse_stroke(widget, (QPointF(60, 200), QPointF(70, 260)))

    assert len(widget.strokes) == 2
    assert [point.event for point in widget.strokes[0].points] == ["down", "move", "up"]
    assert [point.event for point in widget.strokes[1].points] == ["down", "up"]
    assert all(point.pointer_type == "mouse" for stroke in widget.strokes for point in stroke.points)
    assert all(point.pressure is None for stroke in widget.strokes for point in stroke.points)
    elapsed = [point.elapsed_s for stroke in widget.strokes for point in stroke.points]
    assert elapsed == sorted(elapsed)

    sample = widget.build_sample(
        sample_id="sample-two-strokes",
        label="ї",
        classification="glyph",
        provenance=CaptureProvenance(
            source="synthetic_fixture",
            captured_at_utc="2026-10-14T10:00:00Z",
            timing_source="monotonic",
            application_version="test",
        ),
    )
    assert sample.strokes == widget.strokes
    assert sample.coordinate_reference.width == 640
    assert sample.coordinate_reference.height == 480


def test_capture_coordinates_remain_in_locked_frame_after_resize(qtbot) -> None:
    widget = HandwritingCaptureWidget()
    widget.resize(400, 300)
    qtbot.addWidget(widget)
    widget.show()

    QApplication.sendEvent(widget, _mouse_event(
        QEvent.Type.MouseButtonPress, QPointF(200, 150), button=Qt.MouseButton.LeftButton,
        buttons=Qt.MouseButton.LeftButton,
    ))
    widget.resize(800, 600)
    QApplication.sendEvent(widget, _mouse_event(
        QEvent.Type.MouseMove, QPointF(400, 300), button=Qt.MouseButton.NoButton,
        buttons=Qt.MouseButton.LeftButton,
    ))
    QApplication.sendEvent(widget, _mouse_event(
        QEvent.Type.MouseButtonRelease, QPointF(600, 450), button=Qt.MouseButton.LeftButton,
        buttons=Qt.MouseButton.NoButton,
    ))

    points = widget.strokes[0].points
    assert [(point.x, point.y) for point in points] == pytest.approx([
        (200, 150), (200, 150), (300, 225),
    ])
    assert widget.coordinate_reference.width == 400
    assert widget.coordinate_reference.height == 300


def test_synthesized_mouse_events_after_tablet_are_ignored(qtbot) -> None:
    widget = HandwritingCaptureWidget()
    widget.resize(320, 240)
    qtbot.addWidget(widget)
    widget.show()
    widget._suppress_synthesized_mouse_until_ns = time.monotonic_ns() + 1_000_000_000

    for event_type, button, buttons in (
        (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
    ):
        event = _mouse_event(
            event_type, QPointF(40, 40), button=button, buttons=buttons,
            source=Qt.MouseEventSource.MouseEventSynthesizedByQt,
        )
        QApplication.sendEvent(widget, event)
        assert event.isAccepted()

    assert widget.strokes == ()
    assert not widget.has_active_stroke


def test_undo_redo_and_interruption_preserve_whole_strokes(qtbot) -> None:
    widget = HandwritingCaptureWidget()
    widget.resize(320, 240)
    qtbot.addWidget(widget)
    _draw_mouse_stroke(widget, (QPointF(10, 10), QPointF(20, 20)))
    original = widget.strokes[0]

    assert widget.undo_stroke()
    assert widget.strokes == ()
    assert widget.redo_stroke()
    assert widget.strokes == (original,)

    widget._begin_pointer("pen", QPointF(30, 30), pressure=0.25)
    widget._move_pointer(QPointF(40, 40), pressure=0.5)
    widget.cancel_active_stroke()

    assert widget.strokes[-1].termination == "cancelled"
    assert widget.strokes[-1].points[-1].event == "cancel"
    assert widget.strokes[-1].points[-1].pressure == 0.5
    assert "pen" in widget.device_capabilities.pointer_types
    assert widget.device_capabilities.pressure
