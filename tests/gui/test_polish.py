from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox

from handwriting_plotter.gui.document import default_project, save_project
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


def test_dirty_new_can_be_cancelled_without_losing_project(qtbot, tmp_path, monkeypatch) -> None:
    window = MainWindow(temporary_settings(tmp_path))
    qtbot.addWidget(window)
    original_project_id = window.controller.snapshot.project_id
    window.controller.add_text_object()
    original_snapshot = window.controller.snapshot
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel)

    window.new_project()

    assert window.controller.snapshot == original_snapshot
    assert window.controller.snapshot.project_id == original_project_id
    assert window.controller.dirty


def test_dirty_open_can_be_cancelled_without_losing_project(qtbot, tmp_path, monkeypatch) -> None:
    window = MainWindow(temporary_settings(tmp_path))
    qtbot.addWidget(window)
    window.controller.add_text_object()
    original_snapshot = window.controller.snapshot
    incoming = default_project().model_copy(update={"name": "Incoming"})
    project_path = tmp_path / "incoming.hplot.json"
    save_project(project_path, incoming)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(project_path), "Plotter Project (*.hplot.json)"),
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Cancel)

    window.open_project()

    assert window.controller.snapshot == original_snapshot
    assert window.controller.dirty


def test_dirty_new_can_be_discarded(qtbot, tmp_path, monkeypatch) -> None:
    window = MainWindow(temporary_settings(tmp_path))
    qtbot.addWidget(window)
    previous_project_id = window.controller.snapshot.project_id
    window.controller.add_text_object()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Discard)

    window.new_project()

    assert window.controller.snapshot.project_id != previous_project_id
    assert not window.controller.dirty


def test_core_shortcuts_are_registered(qtbot, tmp_path) -> None:
    window = MainWindow(temporary_settings(tmp_path))
    qtbot.addWidget(window)
    assert window.new_action.shortcut().toString()
    assert window.open_action.shortcut().toString()
    assert window.save_action.shortcut().toString()
    assert window.undo_action.shortcut().toString()
    assert window.generate_action.shortcut().toString() == "Ctrl+Return"
