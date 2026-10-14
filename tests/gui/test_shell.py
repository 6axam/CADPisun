from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings

from handwriting_plotter.gui.main_window import MainWindow


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


def test_docks_are_actually_toggleable(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    action = window.project_dock.toggleViewAction()
    action.trigger()
    assert not window.project_dock.isVisible()
    action.trigger()
    assert window.project_dock.isVisible()


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

    reopened = MainWindow(QSettings(settings_path, QSettings.Format.IniFormat))
    qtbot.addWidget(reopened)
    assert reopened.language == "uk"
    assert reopened.ukrainian_language_action.isChecked()
