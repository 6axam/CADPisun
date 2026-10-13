from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

from handwriting_plotter.gui.main_window import MainWindow


def temporary_settings(tmp_path) -> QSettings:
    return QSettings(str(tmp_path / "desktop.ini"), QSettings.Format.IniFormat)


def test_window_layout_and_canvas_preferences_survive_restart(qtbot, tmp_path) -> None:
    settings = temporary_settings(tmp_path)
    first = MainWindow(settings)
    qtbot.addWidget(first)
    first.show()
    first.project_dock.hide()
    first.travel_action.setChecked(True)
    first.resize(1111, 777)
    first.close()
    assert settings.contains("main/geometry")
    assert settings.contains("main/state")

    second = MainWindow(temporary_settings(tmp_path))
    qtbot.addWidget(second)
    second.show()
    assert not second.project_dock.isVisible()
    assert second.travel_action.isChecked()


def test_dirty_close_can_be_cancelled(qtbot, tmp_path, monkeypatch) -> None:
    window = MainWindow(temporary_settings(tmp_path))
    qtbot.addWidget(window)
    window.show()
    window.controller.add_text_object()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel)
    assert not window.close()
    assert window.isVisible()
    window.controller.reset(window.controller.snapshot)
    assert window.close()


def test_core_shortcuts_are_registered(qtbot, tmp_path) -> None:
    window = MainWindow(temporary_settings(tmp_path))
    qtbot.addWidget(window)
    assert window.new_action.shortcut().toString()
    assert window.open_action.shortcut().toString()
    assert window.save_action.shortcut().toString()
    assert window.undo_action.shortcut().toString()
    assert window.generate_action.shortcut().toString() == "Ctrl+Return"
