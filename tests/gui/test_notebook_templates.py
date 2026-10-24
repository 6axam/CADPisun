from __future__ import annotations

import json

import pytest

from handwriting_plotter.gui.backend import GuiBackend, generation_source_hash
from handwriting_plotter.gui.document import (
    DocumentController,
    ProjectSnapshot,
    TextObject,
    load_project,
    save_project,
)
from handwriting_plotter.gui.notebook_templates import (
    NotebookPageTemplate,
    background_lines,
    notebook_background_svg,
)


def test_squared_a4_background_uses_mm_margins_pitch_offset_and_major_lines() -> None:
    template = NotebookPageTemplate(
        kind="squared",
        margin_left_mm=10,
        margin_right_mm=10,
        margin_top_mm=12,
        margin_bottom_mm=12,
        pitch_x_mm=5,
        pitch_y_mm=6,
        offset_x_mm=2,
        offset_y_mm=1,
        major_every=2,
        line_color="#AABBCC",
        major_line_color="#112233",
    )

    lines = background_lines(template)
    vertical = [line for line in lines if line.x1_mm == line.x2_mm]
    horizontal = [line for line in lines if line.y1_mm == line.y2_mm]
    svg = notebook_background_svg(template).decode("utf-8")

    assert (vertical[0].x1_mm, vertical[1].x1_mm) == (12.0, 17.0)
    assert (horizontal[0].y1_mm, horizontal[1].y1_mm) == (13.0, 19.0)
    assert all(line.y1_mm == 12 and line.y2_mm == 285 for line in vertical)
    assert all(line.x1_mm == 10 and line.x2_mm == 200 for line in horizontal)
    assert any(line.major and line.color == "#112233" for line in lines)
    assert 'width="210mm" height="297mm" viewBox="0 0 210 297"' in svg
    assert 'stroke="#AABBCC"' in svg
    assert 'stroke="#112233"' in svg


def test_ruled_landscape_background_has_a4_size_and_no_vertical_lines() -> None:
    template = NotebookPageTemplate(
        kind="ruled", orientation="landscape", margin_left_mm=20, margin_right_mm=20,
        margin_top_mm=10, margin_bottom_mm=10, pitch_y_mm=8,
    )

    lines = background_lines(template)
    svg = notebook_background_svg(template).decode("utf-8")

    assert lines
    assert all(line.y1_mm == line.y2_mm for line in lines)
    assert all((line.x1_mm, line.x2_mm) == (20.0, 277.0) for line in lines)
    assert 'width="297mm" height="210mm" viewBox="0 0 297 210"' in svg


def test_blank_template_exports_physical_white_a4_without_rules() -> None:
    svg = notebook_background_svg(NotebookPageTemplate(kind="blank")).decode("utf-8")

    assert "<rect" in svg
    assert "<line" not in svg
    assert 'width="210mm" height="297mm"' in svg


def test_template_round_trips_and_old_schema_migrates_without_template(tmp_path) -> None:
    template = NotebookPageTemplate(kind="ruled", offset_y_mm=2.5, line_width_mm=0.2)
    snapshot = ProjectSnapshot(project_id="template-project", notebook_template=template)
    path = tmp_path / "template.hplot.json"
    save_project(path, snapshot)

    assert load_project(path) == snapshot
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == "1.6"
    assert persisted["notebook_template"]["offset_y_mm"] == 2.5

    old_path = tmp_path / "old-1.5.hplot.json"
    old_path.write_text(json.dumps({
        "format": "hp-desktop-project", "schema_version": "1.5", "project_id": "old", "name": "Old",
        "page": {"width_mm": 210, "height_mm": 297, "margin_left_mm": 15, "margin_right_mm": 15,
                 "margin_top_mm": 15, "margin_bottom_mm": 15, "paragraph_gap_mm": 4, "pen_width_mm": 0.35},
        "objects": [], "display": {"show_travel": False, "show_markers": False},
    }), encoding="utf-8")
    migrated = load_project(old_path)
    assert migrated.schema_version == "1.6"
    assert migrated.notebook_template is None


def test_template_changes_page_orientation_is_undoable_and_generation_remains_pen_only(qtbot) -> None:
    original = ProjectSnapshot(
        project_id="pen-only-template",
        objects=(TextObject(object_id="text", name="Text", text="Alpha"),),
    )
    controller = DocumentController(original)
    before_hash = generation_source_hash(original)
    template = NotebookPageTemplate(kind="squared", orientation="landscape")

    controller.set_notebook_template(template)

    assert controller.snapshot.page.width_mm == 297
    assert controller.snapshot.page.height_mm == 210
    assert controller.snapshot.notebook_template == template
    assert generation_source_hash(controller.snapshot) != before_hash  # orientation changes the actual page
    controller.undo_stack.undo()
    assert controller.snapshot == original

    # A visual-paper definition is not serialised into production SVG or G-code.
    result = GuiBackend().build(original)
    background = notebook_background_svg(template)
    assert b"#9CC9E8" in background
    assert b"#9CC9E8" not in result.files["page-0001.svg"]
    assert b"#9CC9E8" not in result.files["page-0001.preview.svg"]
    assert b"#9CC9E8" not in result.files["page-0001.gcode"]


def test_template_rejects_margins_that_consume_a4() -> None:
    with pytest.raises(ValueError, match="horizontal margins"):
        NotebookPageTemplate(margin_left_mm=110, margin_right_mm=110)


def test_canvas_previews_template_and_main_window_exports_background(qtbot, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QFileDialog

    from handwriting_plotter.gui.main_window import MainWindow

    window = MainWindow(user_data_root=tmp_path / "user-data")
    qtbot.addWidget(window)
    template = NotebookPageTemplate(kind="ruled", orientation="landscape", pitch_y_mm=9)
    window.controller.set_notebook_template(template)

    assert window.canvas.page_rect_mm.width() == 297
    assert window.canvas.page_rect_mm.height() == 210
    assert window.canvas._notebook_item is not None
    assert window.export_background_action.isEnabled()
    destination = tmp_path / "background.svg"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(destination), "SVG (*.svg)"))

    window.export_notebook_background()

    assert destination.read_bytes() == notebook_background_svg(template)
    assert not window.export_svg_action.isEnabled()  # machine exports still require a generation
    window.controller.reset(window.controller.snapshot)
