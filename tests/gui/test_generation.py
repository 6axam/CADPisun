from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog

from handwriting_plotter.gui.backend import GuiBackend
from handwriting_plotter.gui.document import GridObject, ProjectSnapshot, TextObject
from handwriting_plotter.gui.document import TEXT_COLOR_GROUPS
from handwriting_plotter.geometry.bounds import curve_bounds
from handwriting_plotter.geometry.curves import Cubic, Line, Point2, Quadratic
from handwriting_plotter.gui.theme import COLORS


def composition_project() -> ProjectSnapshot:
    return ProjectSnapshot(
        project_id="composition-test",
        objects=(
            TextObject(
                object_id="first", name="First", text="Alpha", x_mm=20, y_mm=25,
                frame_x_mm=15, frame_y_mm=20, frame_width_mm=70, frame_height_mm=35, seed=7,
            ),
            TextObject(
                object_id="second", name="Second", text="Beta", x_mm=100, y_mm=90,
                frame_x_mm=95, frame_y_mm=85, frame_width_mm=70, frame_height_mm=35, seed=9,
            ),
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


def test_generation_progress_reports_running_success_and_failure(qtbot, tmp_path) -> None:
    from handwriting_plotter.gui.main_window import MainWindow

    window = MainWindow(QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show()

    window._start_generation_progress()
    assert window.generation_progress.isVisible()
    assert window.generation_progress.minimum() == 0
    assert window.generation_progress.maximum() == 0
    assert window.generation_progress.property("state") == "running"

    window._finish_generation_progress("success")
    assert window.generation_progress.value() == 100
    assert window.generation_progress.format() == "Generation complete"
    assert COLORS["success"] in window.generation_progress.styleSheet()

    window._finish_generation_progress("error")
    assert window.generation_progress.value() == 0
    assert window.generation_progress.format() == "Generation failed"
    assert COLORS["danger"] in window.generation_progress.styleSheet()


def test_text_frame_geometry_changes_generated_artifacts() -> None:
    first = composition_project()
    moved_frames = first.model_copy(update={
        "objects": tuple(
            item.model_copy(update={"frame_width_mm": item.frame_width_mm - 5.0})
            for item in first.objects
        )
    })
    baseline = GuiBackend().build(first)
    changed = GuiBackend().build(ProjectSnapshot.model_validate(moved_frames.model_dump(), strict=True))
    assert changed.document_id != baseline.document_id
    assert changed.files != baseline.files


def _segment_from_json(data):
    point = lambda value: Point2(value["x"], value["y"])
    if data["kind"] == "line":
        return Line(point(data["p0"]), point(data["p1"]))
    if data["kind"] == "quadratic":
        return Quadratic(point(data["p0"]), point(data["c1"]), point(data["p1"]))
    return Cubic(point(data["p0"]), point(data["c1"]), point(data["c2"]), point(data["p1"]))


def _draw_bounds(result):
    plan = json.loads(result.files["page-0001.plan.json"])
    parts = [
        curve_bounds(_segment_from_json(segment))
        for operation in plan["operations"] if operation["op"] == "draw"
        for segment in operation["segments"]
    ]
    if not parts:
        return None
    bounds = parts[0]
    for part in parts[1:]:
        bounds = bounds.union(part)
    return bounds


def test_generation_keeps_ink_inside_object_working_area() -> None:
    item = TextObject(
        object_id="bounded", name="Bounded", text="Alpha Beta",
        x_mm=30, y_mm=40,
        frame_x_mm=25, frame_y_mm=35, frame_width_mm=80, frame_height_mm=35,
    )
    result = GuiBackend().build(ProjectSnapshot(project_id="bounded-project", objects=(item,)))
    bounds = _draw_bounds(result)

    assert result.report["complete"] is True
    assert result.report["overflow_object_ids"] == []
    assert bounds is not None
    assert bounds.min_x >= item.frame_x_mm
    assert bounds.max_x <= item.frame_x_mm + item.frame_width_mm
    assert bounds.min_y >= item.frame_y_mm
    assert bounds.max_y <= item.frame_y_mm + item.frame_height_mm


def test_overflowing_object_is_omitted_and_reported() -> None:
    item = TextObject(
        object_id="overflow", name="Overflow", text="Alpha " * 40,
        x_mm=20, y_mm=20,
        frame_x_mm=20, frame_y_mm=20, frame_width_mm=15, frame_height_mm=8,
    )
    result = GuiBackend().build(ProjectSnapshot(project_id="overflow-project", objects=(item,)))

    assert result.report["complete"] is False
    assert result.report["overflow_object_ids"] == ["overflow"]
    assert "OBJECT_FRAME_OVERFLOW:overflow" in result.report["diagnostics"]
    assert _draw_bounds(result) is None


def test_character_spacing_and_rotation_change_geometry_deterministically() -> None:
    base = TextObject(
        object_id="transform", name="Transform", text="Alpha",
        x_mm=60, y_mm=80,
        frame_x_mm=40, frame_y_mm=50, frame_width_mm=100, frame_height_mm=100,
        realism=0,
    )
    plain = GuiBackend().build(ProjectSnapshot(project_id="transform-project", objects=(base,)))
    spaced_item = base.model_copy(update={"character_spacing_mm": 1.5})
    spaced = GuiBackend().build(ProjectSnapshot(project_id="transform-project", objects=(spaced_item,)))
    rotated_item = spaced_item.model_copy(update={"rotation_deg": 90.0})
    rotated = GuiBackend().build(ProjectSnapshot(project_id="transform-project", objects=(rotated_item,)))

    assert _draw_bounds(spaced).max_x > _draw_bounds(plain).max_x
    assert _draw_bounds(rotated) != _draw_bounds(spaced)
    assert rotated.files == GuiBackend().build(
        ProjectSnapshot(project_id="transform-project", objects=(rotated_item,))
    ).files


def test_color_group_colors_production_and_diagnostic_svg() -> None:
    item = TextObject(
        object_id="colored", name="Colored", text="Alpha",
        frame_x_mm=15, frame_y_mm=15, frame_width_mm=80, frame_height_mm=40,
        color_group=6,
    )
    result = GuiBackend().build(ProjectSnapshot(project_id="colored-project", objects=(item,)))
    expected = TEXT_COLOR_GROUPS[6].encode("ascii")

    assert expected in result.files["page-0001.svg"]
    assert expected in result.files["page-0001.preview.svg"]


def test_production_svg_exports_to_high_resolution_png(tmp_path) -> None:
    from handwriting_plotter.gui.exporting import export_page_png

    result = GuiBackend().build(composition_project())
    target = tmp_path / "page.png"

    export_page_png(result, target, width_px=420)

    image = QImage(str(target))
    assert not image.isNull()
    assert image.width() == 420
    assert image.height() == 594


def test_layout_grid_is_strictly_excluded_from_all_generated_artifacts() -> None:
    baseline_project = composition_project()
    with_grid = baseline_project.model_copy(update={
        "objects": baseline_project.objects + (
            GridObject(
                object_id="layout-grid",
                name="Blue grid",
                cell_width_mm=7,
                cell_height_mm=9,
                line_style="dashed",
                color="#2277AA",
            ),
        ),
    })

    baseline = GuiBackend().build(baseline_project)
    changed = GuiBackend().build(ProjectSnapshot.model_validate(with_grid.model_dump(), strict=True))

    assert changed.document_id == baseline.document_id
    assert changed.files == baseline.files


def test_reference_artwork_is_strictly_excluded_from_generated_artifacts(tmp_path) -> None:
    from handwriting_plotter.gui.artwork import import_artwork

    path = tmp_path / "reference.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
        '<circle cx="10" cy="10" r="9"/></svg>',
        encoding="utf-8",
    )
    baseline_project = composition_project()
    artwork = import_artwork(path)
    with_artwork = ProjectSnapshot(
        project_id=baseline_project.project_id,
        name=baseline_project.name,
        page=baseline_project.page,
        objects=baseline_project.objects + (artwork,),
    )

    baseline = GuiBackend().build(baseline_project)
    changed = GuiBackend().build(with_artwork)

    assert changed.document_id == baseline.document_id
    assert changed.files == baseline.files


def test_grid_edits_preserve_current_generated_result(qtbot) -> None:
    from handwriting_plotter.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.controller.reset(composition_project())
    window.generate_page()
    qtbot.waitUntil(lambda: window._generation_worker is None, timeout=10_000)
    generated = window.generated_result

    try:
        window.add_grid_object()
        grid = window.controller.snapshot.objects[-1]
        window._update_grid_object(grid.object_id, {"cell_width_mm": 8.0, "color": "#445566"})

        assert window.generated_result is generated
        assert window.generated_revision == window.controller.revision
        assert all(action.isEnabled() for action in window.export_actions)
    finally:
        window.controller.reset(window.controller.snapshot)


def test_generation_affecting_edits_mark_preview_stale_until_undone(qtbot) -> None:
    from handwriting_plotter.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.controller.reset(composition_project())
    window.generate_page()
    qtbot.waitUntil(lambda: window._generation_worker is None, timeout=10_000)
    item = window.controller.snapshot.objects[0]
    assert not window.canvas.preview_is_stale

    changes = (
        lambda: window.controller.update_text_object(item.object_id, text="Changed text"),
        lambda: window.controller.update_text_object(item.object_id, x_height_mm=4.25),
        lambda: window.controller.update_text_object(item.object_id, style_revision="9.9.9"),
        lambda: window.controller.update_page(margin_left_mm=16.0),
    )
    for change in changes:
        change()
        assert window.canvas.preview_is_stale
        assert window.canvas.has_artifact
        assert window.canvas._stale_banner_item.isVisible()
        assert all(not action.isEnabled() for action in window.export_actions)

        window.controller.undo_stack.undo()
        assert not window.canvas.preview_is_stale
        assert not window.canvas._stale_banner_item.isVisible()
        assert all(action.isEnabled() for action in window.export_actions)

    window.controller.reset(window.controller.snapshot)


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
    from handwriting_plotter.gui.main_window import ROLE_KIND, MainWindow

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
