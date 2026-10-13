from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

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
        "File", "Edit", "View", "Tools", "Machine", "Help",
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
