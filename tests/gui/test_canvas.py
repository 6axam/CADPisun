from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent

from handwriting_plotter.application.service import (
    GenerationRequest,
    HandwritingPlotterService,
)
from handwriting_plotter.gui.canvas import PageCanvas
from handwriting_plotter.gui.document import GridObject, TEXT_COLOR_GROUPS, TextObject


@pytest.fixture(scope="module")
def artifacts() -> dict[str, bytes]:
    return HandwritingPlotterService().build("Test 123", GenerationRequest()).files


def test_canvas_uses_physical_a4_scene(qtbot) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    page = canvas.page_rect_mm
    assert page.width() == 210.0
    assert page.height() == 297.0


def test_canvas_renders_backend_svg_and_independent_diagnostics(qtbot, artifacts) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    canvas.set_artifacts(
        artifacts["page-0001.svg"],
        artifacts["page-0001.preview.svg"],
        artifacts["page-0001.plan.json"],
    )
    assert canvas.has_artifact
    assert canvas._production_item.isVisible()
    assert not canvas._preview_item.isVisible()
    assert all(not item.isVisible() for item in canvas._marker_items)

    canvas.set_show_travel(True)
    canvas.set_show_markers(True)
    assert not canvas._production_item.isVisible()
    assert canvas._preview_item.isVisible()
    assert all(item.isVisible() for item in canvas._marker_items)


def test_zoom_to_fit_is_stable(qtbot) -> None:
    canvas = PageCanvas()
    canvas.resize(700, 700)
    qtbot.addWidget(canvas)
    canvas.show()
    canvas.zoom_to_fit()
    assert 0.25 <= canvas.zoom_factor <= 20.0
    first = canvas.zoom_factor
    canvas.resize(500, 500)
    qtbot.wait(1)
    assert canvas.zoom_factor != first


def test_text_object_frame_is_drawn_and_highlighted_on_selection(qtbot) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    item = TextObject(
        object_id="frame",
        name="Frame",
        frame_x_mm=21,
        frame_y_mm=32,
        frame_width_mm=74,
        frame_height_mm=45,
    )

    canvas.set_object_frames((item,), {item.object_id})

    frame = canvas._object_frames[item.object_id]
    assert frame.rect().getRect() == (21.0, 32.0, 74.0, 45.0)
    assert frame.pen().style() == Qt.PenStyle.SolidLine
    canvas.set_selected_objects(set())
    assert frame.pen().style() == Qt.PenStyle.DashLine


def test_selected_text_frame_uses_color_group_and_has_eight_resize_handles(qtbot) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    item = TextObject(
        object_id="colored-frame", name="Colored", color_group=6,
        frame_x_mm=20, frame_y_mm=30, frame_width_mm=80, frame_height_mm=40,
    )

    canvas.set_object_frames((item,), {item.object_id})

    assert canvas._object_frames[item.object_id].pen().color().name().upper() == TEXT_COLOR_GROUPS[6]
    assert set(canvas._resize_handles) == {"nw", "n", "ne", "e", "se", "s", "sw", "w"}
    assert canvas._resize_handles["se"].rect().center() == QPointF(100, 70)


def test_side_resize_changes_one_axis_and_corner_resize_preserves_ratio(qtbot) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    item = TextObject(
        object_id="resize", name="Resize",
        frame_x_mm=20, frame_y_mm=30, frame_width_mm=80, frame_height_mm=40,
    )
    canvas.set_object_frames((item,), {item.object_id})
    canvas._resize_object_id = item.object_id
    canvas._resize_initial_rect = QRectF(20, 30, 80, 40)
    canvas._active_resize_handle = "e"

    canvas._preview_resize(QPointF(120, 42))
    side = canvas._object_frames[item.object_id].rect()
    assert side.getRect() == (20.0, 30.0, 100.0, 40.0)

    canvas._resize_initial_rect = QRectF(20, 30, 80, 40)
    canvas._active_resize_handle = "se"
    canvas._preview_resize(QPointF(140, 80))
    corner = canvas._object_frames[item.object_id].rect()
    assert corner.width() / corner.height() == pytest.approx(2.0)
    assert corner.topLeft() == QPointF(20, 30)


def test_dragging_side_handle_emits_resized_physical_rectangle(qtbot) -> None:
    canvas = PageCanvas()
    canvas.resize(700, 700)
    qtbot.addWidget(canvas)
    canvas.show()
    canvas.zoom_to_fit()
    item = TextObject(
        object_id="resize-event", name="Resize event",
        frame_x_mm=20, frame_y_mm=30, frame_width_mm=80, frame_height_mm=40,
    )
    canvas.set_object_frames((item,), {item.object_id})
    emitted: list[tuple[str, float, float, float, float]] = []
    canvas.object_resized.connect(lambda *values: emitted.append(values))
    start = canvas.mapFromScene(QPointF(100, 50))
    end = canvas.mapFromScene(QPointF(120, 50))

    qtbot.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(canvas.viewport(), pos=end)
    qtbot.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)

    assert emitted
    object_id, x, y, width, height = emitted[-1]
    assert object_id == item.object_id
    assert (x, y, height) == pytest.approx((20, 30, 40), abs=0.5)
    assert width == pytest.approx(100, abs=0.5)


def test_hovered_frame_is_wider_and_dashed(qtbot) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    item = TextObject(object_id="hover", name="Hover", frame_x_mm=20, frame_y_mm=30)
    canvas.set_object_frames((item,), {item.object_id})

    canvas._hovered_object_id = item.object_id
    canvas._sync_object_frame_styles()

    pen = canvas._object_frames[item.object_id].pen()
    assert pen.style() == Qt.PenStyle.DashLine
    assert pen.widthF() == pytest.approx(1.0)


def test_overflow_marker_is_centered_red_circle_with_white_cross(qtbot) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    item = TextObject(
        object_id="overflow", name="Overflow", display_diameter_mm=6,
        frame_x_mm=20, frame_y_mm=30, frame_width_mm=80, frame_height_mm=40,
    )
    canvas.set_object_frames((item,), {item.object_id})

    canvas.set_object_overflows((item.object_id,))

    assert len(canvas._overflow_items) == 3
    circle = canvas._overflow_items[0]
    assert circle.rect().center() == QPointF(60, 50)
    assert circle.rect().width() == 6
    assert circle.brush().color().name().upper() == "#DC2626"
    assert all(line.pen().color().name().upper() == "#FFFFFF" for line in canvas._overflow_items[1:])


def test_selection_direction_controls_crossing_semantics(qtbot) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    first = TextObject(object_id="first", name="First", frame_x_mm=20, frame_y_mm=20, frame_width_mm=20, frame_height_mm=20)
    second = TextObject(object_id="second", name="Second", frame_x_mm=50, frame_y_mm=20, frame_width_mm=20, frame_height_mm=20)
    canvas.set_object_frames((first, second))
    selection = QRectF(15, 15, 45, 30)

    assert canvas._objects_in_selection(selection, crossing=False) == {"first"}
    assert canvas._objects_in_selection(selection, crossing=True) == {"first", "second"}


def test_object_move_preview_keeps_all_selected_frames_on_page(qtbot) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    first = TextObject(object_id="first", name="First", x_mm=10, y_mm=10, frame_x_mm=10, frame_y_mm=10)
    second = TextObject(
        object_id="second", name="Second", x_mm=145, y_mm=250,
        frame_x_mm=145, frame_y_mm=250, frame_width_mm=60, frame_height_mm=30,
    )
    canvas.set_object_frames((first, second), {"first", "second"})
    canvas._selection_origin = QPointF(20, 20)
    canvas._move_initial_rects = {
        object_id: QRectF(frame.rect()) for object_id, frame in canvas._object_frames.items()
    }

    canvas._preview_move(QPointF(100, 100))

    assert canvas._move_delta == QPointF(5, 17)
    assert canvas._object_frames["second"].rect().right() == 210
    assert canvas._object_frames["second"].rect().bottom() == 297


def test_dragging_selected_object_emits_physical_move(qtbot) -> None:
    canvas = PageCanvas()
    canvas.resize(700, 700)
    qtbot.addWidget(canvas)
    canvas.show()
    canvas.zoom_to_fit()
    item = TextObject(object_id="move", name="Move", x_mm=20, y_mm=20, frame_x_mm=20, frame_y_mm=20)
    canvas.set_object_frames((item,), {item.object_id})
    emitted: list[tuple[tuple[str, ...], float, float]] = []
    canvas.objects_moved.connect(lambda ids, dx, dy: emitted.append((ids, dx, dy)))
    start = canvas.mapFromScene(QPointF(25, 25))
    end = canvas.mapFromScene(QPointF(35, 40))

    qtbot.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(canvas.viewport(), pos=end)
    qtbot.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=end)

    assert emitted
    assert emitted[-1][0] == ("move",)
    assert emitted[-1][1] == pytest.approx(10, abs=0.5)
    assert emitted[-1][2] == pytest.approx(15, abs=0.5)


def test_ctrl_click_toggles_object_once_per_click(qtbot) -> None:
    canvas = PageCanvas()
    canvas.resize(700, 700)
    qtbot.addWidget(canvas)
    canvas.show()
    canvas.zoom_to_fit()
    first = TextObject(
        object_id="first", name="First", frame_x_mm=20, frame_y_mm=20,
        frame_width_mm=20, frame_height_mm=20,
    )
    second = TextObject(
        object_id="second", name="Second", frame_x_mm=50, frame_y_mm=20,
        frame_width_mm=20, frame_height_mm=20,
    )
    canvas.set_object_frames((first, second), {first.object_id})
    second_position = canvas.mapFromScene(QPointF(55, 25))

    qtbot.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier, pos=second_position,
    )
    assert canvas._selected_object_ids == {"first", "second"}

    qtbot.mouseClick(
        canvas.viewport(), Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier, pos=second_position,
    )
    assert canvas._selected_object_ids == {"first"}


def test_grid_is_rendered_and_snap_can_apply_to_one_axis(qtbot) -> None:
    canvas = PageCanvas()
    qtbot.addWidget(canvas)
    grid = GridObject(
        object_id="grid", x_mm=10, y_mm=10, width_mm=100, height_mm=100,
        cell_width_mm=10, cell_height_mm=10, line_style="dash_dot", color="#123456",
    )
    text = TextObject(
        object_id="text", name="Text", x_mm=21.2, y_mm=23,
        frame_x_mm=21.2, frame_y_mm=23, frame_width_mm=13, frame_height_mm=9,
    )
    canvas.set_object_frames((grid, text), {text.object_id})

    snapped = canvas._snap_move_delta({text.object_id}, QPointF())

    assert canvas._grid_items[grid.object_id].grid.line_style == "dash_dot"
    assert canvas._grid_items[grid.object_id].grid.color == "#123456"
    assert snapped.x() == pytest.approx(-1.2)
    assert snapped.y() == 0


def test_canvas_reports_cursor_coordinates_and_measured_paint_rate(qtbot) -> None:
    canvas = PageCanvas()
    canvas.resize(700, 700)
    qtbot.addWidget(canvas)
    canvas.show()
    canvas.zoom_to_fit()
    positions: list[QPointF | None] = []
    rates: list[float] = []
    canvas.cursor_position_changed.connect(positions.append)
    canvas.fps_changed.connect(rates.append)

    viewport_position = QPointF(canvas.mapFromScene(QPointF(30, 40)))
    canvas.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove,
        viewport_position,
        viewport_position,
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    ))
    now = time.monotonic()
    canvas._paint_timestamps.clear()
    canvas._paint_timestamps.extend((now - 0.5, now))
    canvas._publish_fps()

    assert positions[-1].x() == pytest.approx(30, abs=0.5)
    assert positions[-1].y() == pytest.approx(40, abs=0.5)
    assert rates[-1] == pytest.approx(2.0, rel=0.1)
