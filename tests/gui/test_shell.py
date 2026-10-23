from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox

from handwriting_plotter.gui.document import ProjectSnapshot, TextObject
from handwriting_plotter.gui.main_window import MainWindow
from handwriting_plotter.gui.theme import COLORS
from handwriting_plotter.version import __version__


def isolated_window(tmp_path, name: str) -> MainWindow:
    settings = QSettings(str(tmp_path / f"{name}.ini"), QSettings.Format.IniFormat)
    return MainWindow(settings, user_data_root=tmp_path / f"{name}-data")


def test_main_window_has_engineering_workspace(qtbot, tmp_path) -> None:
    window = isolated_window(tmp_path, "workspace")
    qtbot.addWidget(window)
    window.show()
    assert window.windowTitle().endswith("— Handwriting Plotter")
    assert window.centralWidget().objectName() == "workspace-stack"
    assert window.workspace_stack.currentWidget() is window.canvas
    assert window.canvas.objectName() == "page-canvas"
    assert window.project_dock.isVisible()
    assert window.properties_dock.isVisible()
    assert window.output_dock.isVisible()
    assert [action.text().replace("&", "") for action in window.menuBar().actions()] == [
        "File", "Edit", "View", "Language", "Tools", "Machine", "Help",
    ]
    assert window.version_label.text() == f"Version {__version__}"
    assert window.statusBar().childrenRect().contains(window.version_label.geometry())


def test_docks_are_actually_toggleable(qtbot, tmp_path) -> None:
    window = isolated_window(tmp_path, "toggle-docks")
    qtbot.addWidget(window)
    window.show()
    action = window.project_dock.toggleViewAction()
    action.trigger()
    assert not window.project_dock.isVisible()
    action.trigger()
    assert window.project_dock.isVisible()


def test_issue_nine_splits_responsive_tool_docks_and_exposes_them_in_view(qtbot, tmp_path) -> None:
    window = isolated_window(tmp_path, "issue-nine-tools")
    qtbot.addWidget(window)
    window.show()

    docks = (window.project_tools_dock, window.editing_tools_dock, window.view_tools_dock)
    assert all(dock.isVisible() for dock in docks)
    assert window.dockWidgetArea(window.project_tools_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    assert window.dockWidgetArea(window.editing_tools_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    assert window.dockWidgetArea(window.view_tools_dock) == Qt.DockWidgetArea.TopDockWidgetArea
    assert all(dock.toggleViewAction() in window.view_menu.actions() for dock in docks)
    assert [dock.windowTitle() for dock in docks] == ["Project", "Editing", "View"]
    assert all(button.width() == button.height() for button in window.tool_buttons)
    assert all(button.text() and button.text() != button.accessibleName() for button in window.tool_buttons)

    window.editing_tools_dock.setFloating(True)
    window.editing_tools_dock.resize(70, 320)
    qtbot.wait(1)
    assert window.editing_tools_panel.column_count == 1
    window.editing_tools_dock.resize(260, 100)
    qtbot.wait(1)
    assert window.editing_tools_panel.column_count > 1


def test_issue_nine_modes_switch_to_real_preview_and_execution_workspaces(qtbot, tmp_path) -> None:
    window = isolated_window(tmp_path, "issue-seven-modes")
    qtbot.addWidget(window)
    window.show()

    assert window.modes_dock.isVisible()
    assert window.dockWidgetArea(window.modes_dock) == Qt.DockWidgetArea.TopDockWidgetArea
    assert window.modes_dock.toggleViewAction() in window.view_menu.actions()
    assert window.object_mode_action.isChecked()
    assert window.object_mode_action.isEnabled()
    assert window.preview_mode_action.isEnabled()
    assert window.execution_mode_action.isEnabled()
    assert window.preview_mode_action.property("implementationStatus") == "implemented"
    assert window.execution_mode_action.property("implementationStatus") == "implemented"
    assert window.preview_mode_action.data() == "preview"
    assert window.execution_mode_action.data() == "execution"

    window.generate_page()
    qtbot.waitUntil(lambda: window._generation_worker is None, timeout=10_000)
    window.preview_mode_action.trigger()
    assert window.workspace_stack.currentWidget() is window.preview_workspace
    assert window.preview_workspace.has_artifact
    assert "G21" in window.preview_workspace.gcode.toPlainText()
    assert window.preview_workspace.timeline.maximum() > 0

    window.execution_mode_action.trigger()
    assert window.workspace_stack.currentWidget() is window.execution_workspace
    assert "SIMULATION ONLY" in window.execution_workspace.state_label.text()
    before = window.execution_workspace.timeline.value()
    window.execution_workspace.play_button.click()
    qtbot.waitUntil(lambda: window.execution_workspace.timeline.value() > before, timeout=2_000)
    window.execution_workspace.play_button.click()

    window.object_mode_action.trigger()
    assert window.workspace_stack.currentWidget() is window.canvas


def test_properties_scroll_and_output_dock_use_non_overlapping_corner(qtbot, tmp_path) -> None:
    window = isolated_window(tmp_path, "issue-nine-docking")
    qtbot.addWidget(window)
    window.resize(900, 620)
    window.show()
    item = window.controller.snapshot.objects[0]
    window._on_canvas_selection_changed((item.object_id,))
    qtbot.wait(1)

    assert window.properties_scroll.widget() is window.properties
    assert window.properties_scroll.widgetResizable()
    assert window.properties_scroll.verticalScrollBar().maximum() > 0
    assert window.corner(Qt.Corner.BottomRightCorner) == Qt.DockWidgetArea.RightDockWidgetArea

    window.output_dock.setFloating(True)
    window.output_dock.setFloating(False)
    assert not window.output_dock.isFloating()
    assert window.dockWidgetArea(window.output_dock) == Qt.DockWidgetArea.BottomDockWidgetArea


def test_status_bar_shows_canvas_fps_and_cursor_coordinates(qtbot, tmp_path) -> None:
    window = isolated_window(tmp_path, "status-telemetry")
    qtbot.addWidget(window)

    window.canvas.fps_changed.emit(59.94)
    window.canvas.cursor_position_changed.emit(window.canvas.page_rect_mm.center())
    window.show()

    assert window.telemetry_label.isVisible()
    assert "FPS: 59.9" in window.telemetry_label.text()
    assert "X: 105.00 mm" in window.telemetry_label.text()
    assert "Y: 148.50 mm" in window.telemetry_label.text()


def test_status_messages_use_distinct_operation_colors(qtbot, tmp_path) -> None:
    window = isolated_window(tmp_path, "status-colors")
    qtbot.addWidget(window)

    for severity, color in (
        ("info", COLORS["muted"]),
        ("success", COLORS["success"]),
        ("warning", COLORS["warning"]),
        ("error", COLORS["danger"]),
    ):
        window._show_status(severity, severity)
        assert window.statusBar().property("messageSeverity") == severity
        assert window.operation_status_label.property("severity") == severity
        assert color in window.operation_status_label.styleSheet()
        assert window.operation_status_label.text() == severity
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
    assert window.project_tools_dock.windowTitle() == "Проєкт"
    assert window.editing_tools_dock.windowTitle() == "Редагування"
    assert window.view_tools_dock.windowTitle() == "Вигляд"
    assert window.modes_dock.windowTitle() == "Режими"
    assert window.object_mode_action.text() == "Об’єкт"
    assert window.properties._labels["properties.name"].text() == "Назва"
    assert window.version_label.text() == f"Версія {__version__}"

    reopened = MainWindow(QSettings(settings_path, QSettings.Format.IniFormat))
    qtbot.addWidget(reopened)
    assert reopened.language == "uk"
    assert reopened.ukrainian_language_action.isChecked()


def test_controls_dialog_lists_current_shortcuts_and_canvas_gestures(qtbot, tmp_path) -> None:
    from handwriting_plotter.gui.dialogs import ControlsDialog

    window = isolated_window(tmp_path, "controls")
    qtbot.addWidget(window)
    dialog = ControlsDialog(window._shortcut_bindings(), language="en", parent=window)
    qtbot.addWidget(dialog)

    labels = [dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())]
    shortcuts = [dialog.table.item(row, 1).text() for row in range(dialog.table.rowCount())]
    assert "Generate Page" in labels
    assert any("Ctrl" in value and ("Enter" in value or "Return" in value) for value in shortcuts)
    gestures = dialog.findChild(QLabel, "controls-gestures")
    assert "Ctrl+click" in gestures.text()
    assert "Space+drag" in gestures.text()
    assert window.controls_action in window.help_menu.actions()


def test_program_settings_remaps_shortcut_changes_language_and_persists(
    qtbot, tmp_path, monkeypatch
) -> None:
    from handwriting_plotter.gui.dialogs import ProgramSettingsDialog

    settings_path = str(tmp_path / "program-settings.ini")
    window = MainWindow(QSettings(settings_path, QSettings.Format.IniFormat))
    qtbot.addWidget(window)

    def configure(dialog):
        dialog.shortcut_edits["generate"].setKeySequence(QKeySequence("Ctrl+G"))
        dialog.language_combo.setCurrentIndex(dialog.language_combo.findData("uk"))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ProgramSettingsDialog, "exec", configure)
    window._show_program_settings()

    assert window.generate_action.shortcut() == QKeySequence("Ctrl+G")
    assert window.language == "uk"
    reopened = MainWindow(QSettings(settings_path, QSettings.Format.IniFormat))
    qtbot.addWidget(reopened)
    assert reopened.generate_action.shortcut() == QKeySequence("Ctrl+G")
    assert reopened.language == "uk"


def test_about_reports_build_project_format_and_hardware_status(qtbot, tmp_path, monkeypatch) -> None:
    window = isolated_window(tmp_path, "about")
    qtbot.addWidget(window)
    captured = {}
    monkeypatch.setattr(
        QMessageBox,
        "about",
        lambda _parent, title, body: captured.update(title=title, body=body),
    )

    window._about()

    assert "Handwriting Plotter" in captured["title"]
    assert "hp-desktop-project/1.5" in captured["body"]
    assert "simulation only" in captured["body"]
    assert "github.com/6axam/CADPisun" in captured["body"]


def test_canvas_selection_is_mirrored_in_tree_and_batch_delete_is_undoable(qtbot, tmp_path) -> None:
    window = isolated_window(tmp_path, "selection")
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


def test_canvas_move_signal_updates_text_and_frame_coordinates(qtbot, tmp_path) -> None:
    window = isolated_window(tmp_path, "move")
    qtbot.addWidget(window)
    item = window.controller.snapshot.objects[0]

    window.canvas.objects_moved.emit((item.object_id,), 7.0, 9.0)

    moved = window.controller.snapshot.objects[0]
    assert (moved.x_mm, moved.y_mm) == (item.x_mm + 7, item.y_mm + 9)
    assert (moved.frame_x_mm, moved.frame_y_mm) == (item.frame_x_mm + 7, item.frame_y_mm + 9)
    window.controller.reset(window.controller.snapshot)


def test_grid_object_can_be_created_selected_and_edited(qtbot, tmp_path) -> None:
    window = isolated_window(tmp_path, "grid")
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
