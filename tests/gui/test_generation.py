from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from handwriting_plotter.gui.backend import GuiBackend
from handwriting_plotter.gui.document import ProjectSnapshot, TextObject


def composition_project() -> ProjectSnapshot:
    return ProjectSnapshot(
        project_id="composition-test",
        objects=(
            TextObject(object_id="first", name="First", text="Alpha", x_mm=20, y_mm=25, seed=7),
            TextObject(object_id="second", name="Second", text="Beta", x_mm=100, y_mm=90, seed=9),
        ),
    )


def test_composition_builds_one_authoritative_plan_for_positioned_objects() -> None:
    result = GuiBackend().build(composition_project())
    assert result.page_count == 1
    assert result.report["source_coverage_count"] == 9
    assert result.report["machine"]["simulation_only"] is True
    assert {"page-0001.svg", "page-0001.preview.svg", "page-0001.plan.json", "page-0001.gcode"} <= result.files.keys()
    plan = json.loads(result.files["page-0001.plan.json"])
    targets = [item["target"] for item in plan["operations"] if item["op"] == "travel_to"]
    assert any(point["x"] < 50 and point["y"] < 50 for point in targets)
    assert any(point["x"] > 90 and point["y"] > 80 for point in targets)
    stroke_ids = [stroke for item in plan["operations"] if item["op"] == "draw" for stroke in item["stroke_ids"]]
    assert any(stroke.startswith("first/") for stroke in stroke_ids)
    assert any(stroke.startswith("second/") for stroke in stroke_ids)


def test_missing_glyph_fails_before_replacing_gui_result(qtbot) -> None:
    from handwriting_plotter.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.generate_page()
    qtbot.waitUntil(lambda: window._generation_worker is None, timeout=10_000)
    accepted = window.generated_result
    assert accepted is not None
    assert window.canvas.has_artifact
    item = window.controller.snapshot.objects[0]
    window.controller.update_text_object(item.object_id, text="🙂")
    window.generate_page()
    qtbot.waitUntil(lambda: window._generation_worker is None, timeout=10_000)
    assert window.generated_result is accepted
    assert window.canvas.has_artifact
    assert "missing" in window.diagnostics.toPlainText().lower()
    window.controller.reset(window.controller.snapshot)


def test_stale_generation_result_is_discarded(qtbot) -> None:
    from handwriting_plotter.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    result = GuiBackend().build(composition_project())
    current = window.controller.revision
    window._generation_succeeded(current - 1, result)
    assert window.generated_result is None
    assert not window.canvas.has_artifact
    assert "Discarded stale result" in window.console.toPlainText()


def test_open_restores_saved_generation_without_running_backend(qtbot, tmp_path, monkeypatch) -> None:
    from handwriting_plotter.gui.main_window import MainWindow

    snapshot = composition_project()
    result = GuiBackend().build(snapshot)
    path = tmp_path / "calculated.hplot.json"
    first = MainWindow()
    qtbot.addWidget(first)
    first.controller.reset(snapshot)
    first._display_generation_result(first.controller.revision, result)
    first._write_project(path)

    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    monkeypatch.setattr(window.backend, "build", lambda _: pytest.fail("backend must not run while opening"))

    window.open_project()

    assert window.generated_result is not None
    assert window.generated_result.files == result.files
    assert window.generated_revision == window.controller.revision
    assert window.canvas.has_artifact
    assert all(action.isEnabled() for action in window.export_actions)
    assert "Restored generated page" in window.console.toPlainText()


def test_visibility_toggle_clears_and_regenerates_the_rendered_page(qtbot) -> None:
    from handwriting_plotter.gui.main_window import MainWindow, ROLE_KIND

    window = MainWindow()
    qtbot.addWidget(window)
    window.generate_page()
    qtbot.waitUntil(lambda: window._generation_worker is None, timeout=10_000)
    assert window.canvas.has_artifact

    def text_node():
        root = window.project_tree.invisibleRootItem()
        document = root.child(0).child(0)
        return next(
            document.child(index)
            for index in range(document.childCount())
            if document.child(index).data(0, ROLE_KIND) == "text"
        )

    text_node().setCheckState(0, Qt.CheckState.Unchecked)
    qtbot.waitUntil(lambda: window.controller.snapshot.objects[0].visible is False)
    qtbot.wait(150)
    assert not window.canvas.has_artifact
    assert window.generated_result is None
    assert "hidden" in window.console.toPlainText().lower()

    text_node().setCheckState(0, Qt.CheckState.Checked)
    qtbot.waitUntil(
        lambda: window._generation_worker is None and window.canvas.has_artifact,
        timeout=10_000,
    )
    assert window.generated_revision == window.controller.revision
    window.controller.reset(window.controller.snapshot)
