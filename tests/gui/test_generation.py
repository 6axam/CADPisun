from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

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
