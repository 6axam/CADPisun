from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings

from handwriting_plotter.gui.document import ProjectSnapshot, TextObject
from handwriting_plotter.gui.main_window import MainWindow
from handwriting_plotter.gui.theme import COLORS
from handwriting_plotter.version import __version__


def test_main_window_has_engineering_workspace(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle().endswith("— Handwriting Plotter")
    assert window.centralWidget().objectName() == "page-canvas"
    assert window.project_dock.isVisible()
    assert window.properties_dock.isVisible()
    assert window.output_dock.isVisible()
    assert [action.text().replace("&", "") for action in window.menuBar().actions()] == [
        "File", "Edit", "View", "Language", "Tools", "Machine", "Help",
    ]
    assert window.version_label.text() == f"Version {__version__}"
    assert window.statusBar().childrenRect().contains(window.version_label.geometry())


def test_docks_are_actually_toggleable(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    action = window.project_dock.toggleViewAction()
    action.trigger()
    assert not window.project_dock.isVisible()
    action.trigger()
    assert window.project_dock.isVisible()


def test_status_bar_shows_canvas_fps_and_cursor_coordinates(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.canvas.fps_changed.emit(59.94)
    window.canvas.cursor_position_changed.emit(window.canvas.page_rect_mm.center())
    window.show()

    assert window.telemetry_label.isVisible()
    assert "FPS: 59.9" in window.telemetry_label.text()
    assert "X: 105.00 mm" in window.telemetry_label.text()
    assert "Y: 148.50 mm" in window.telemetry_label.text()


def test_status_messages_use_distinct_operation_colors(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    for severity, color in (
        ("info", COLORS["muted"]),
        ("success", COLORS["success"]),
        ("warning", COLORS["warning"]),
        ("error", COLORS["danger"]),
    ):
        window._show_status(severity, severity)
        assert window.statusBar().property("messageSeverity") == severity
        assert color in window.statusBar().styleSheet()
        assert window.statusBar().currentMessage() == severity


def test_language_menu_switches_to_ukrainian_and_persists(qtbot, tmp_path) -> None:
    settings_path = str(tmp_path / "language.ini")
    window = MainWindow(QSettings(settings_path, QSettings.Format.IniFormat))
    qtbot.addWidget(window)

    window.ukrainian_language_action.trigger()

    assert window.language == "uk"
    assert [action.text().replace("&", "") for action in window.menuBar().actions()] == [
        "Файл", "Редагування", "Вигляд", "Мова", "Інструменти", "Верстат", "Довідка",
    ]
    assert window.project_dock.windowTitle() == "Об’єкти проєкту"
    assert window.properties._labels["properties.name"].text() == "Назва"
    assert window.version_label.text() == f"Версія {__version__}"

    reopened = MainWindow(QSettings(settings_path, QSettings.Format.IniFormat))
    qtbot.addWidget(reopened)
    assert reopened.language == "uk"
    assert reopened.ukrainian_language_action.isChecked()


def test_canvas_selection_is_mirrored_in_tree_and_batch_delete_is_undoable(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    snapshot = ProjectSnapshot(
        project_id="selection-project",
        objects=(
            TextObject(object_id="first", name="First"),
            TextObject(object_id="second", name="Second", frame_x_mm=80),
        ),
    )
    window.controller.reset(snapshot)

    window.canvas._publish_selection({"first", "second"})

    assert window._selected_object_ids == {"first", "second"}
    assert {
        item.data(0, 257)
        for item in window.project_tree.selectedItems()
        if item.data(0, 256) == "text"
    } == {"first", "second"}

    window.remove_selected_object()
    assert window.controller.snapshot.objects == ()
    window.controller.undo_stack.undo()
    assert {item.object_id for item in window.controller.snapshot.objects} == {"first", "second"}


def test_canvas_move_signal_updates_text_and_frame_coordinates(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    item = window.controller.snapshot.objects[0]

    window.canvas.objects_moved.emit((item.object_id,), 7.0, 9.0)

    moved = window.controller.snapshot.objects[0]
    assert (moved.x_mm, moved.y_mm) == (item.x_mm + 7, item.y_mm + 9)
    assert (moved.frame_x_mm, moved.frame_y_mm) == (item.frame_x_mm + 7, item.frame_y_mm + 9)
    window.controller.reset(window.controller.snapshot)


def test_grid_object_can_be_created_selected_and_edited(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    window.add_grid_object()

    grid = window.controller.snapshot.objects[-1]
    window.controller.reset(window.controller.snapshot)
    assert grid.kind == "grid"
    assert window._selected_kind == "grid"
    assert window.properties.stack.currentWidget() is window.properties.grid_widget
    assert grid.object_id in window.canvas._grid_items
    window.properties.cell_height_field.setValue(12)
    assert window.controller.snapshot.objects[-1].cell_height_mm == 12
    window.controller.reset(window.controller.snapshot)
