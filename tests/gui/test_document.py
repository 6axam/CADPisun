from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from shiboken6 import isValid

from handwriting_plotter.gui import document as document_module
from handwriting_plotter.gui.document import (
    DocumentController,
    GridObject,
    ProjectSnapshot,
    TextObject,
    load_project,
    load_project_file,
    save_project,
)


def sample_project() -> ProjectSnapshot:
    return ProjectSnapshot(
        project_id="project-test",
        name="Український зошит",
        objects=(TextObject(object_id="text-1", name="Рядок", text="Привіт, світе!"),),
    )


def test_project_round_trip_is_portable_and_canonical(tmp_path) -> None:
    path = tmp_path / "portable.hplot.json"
    snapshot = sample_project()
    save_project(path, snapshot)
    assert load_project(path) == snapshot
    raw = path.read_text(encoding="utf-8")
    assert "Привіт" in raw
    assert str(tmp_path) not in raw
    assert list(json.loads(raw)) == sorted(json.loads(raw))
    assert not list(tmp_path.glob("*.tmp"))


def test_project_save_skips_unsupported_directory_fsync_on_windows(tmp_path, monkeypatch) -> None:
    def windows_open(*args, **kwargs):  # noqa: ANN002, ANN003
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(document_module.os, "name", "nt")
    monkeypatch.setattr(document_module.os, "open", windows_open)

    document_module._sync_directory(tmp_path)


def test_project_rejects_unknown_schema(tmp_path) -> None:
    path = tmp_path / "future.hplot.json"
    data = sample_project().model_dump(mode="json")
    data["schema_version"] = "99.0"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="UNSUPPORTED_PROJECT_SCHEMA"):
        load_project(path)


@pytest.mark.parametrize("schema_version", ["1.0", "1.1", "1.2"])
def test_legacy_project_is_loaded_with_text_frames(tmp_path, schema_version) -> None:
    path = tmp_path / "legacy.hplot.json"
    data = sample_project().model_dump(mode="json")
    data["schema_version"] = schema_version
    data["objects"][0]["x_mm"] = 42.0
    data["objects"][0]["y_mm"] = 53.0
    data["objects"][0].pop("kind")
    for key in ("frame_x_mm", "frame_y_mm", "frame_width_mm", "frame_height_mm"):
        data["objects"][0].pop(key)
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_project(path)

    assert loaded.schema_version == "1.4"
    assert loaded.project_id == sample_project().project_id
    assert loaded.objects[0].frame_x_mm == 42.0
    assert loaded.objects[0].frame_y_mm == 53.0
    assert loaded.objects[0].frame_width_mm == 60.0
    assert loaded.objects[0].frame_height_mm == 30.0
    assert loaded.objects[0].kind == "text"


def test_schema_13_project_gets_new_text_layout_defaults(tmp_path) -> None:
    data = sample_project().model_dump(mode="json")
    data["schema_version"] = "1.3"
    for key in ("character_spacing_mm", "rotation_deg", "display_diameter_mm", "color_group"):
        data["objects"][0].pop(key, None)
    path = tmp_path / "schema-13.hplot.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_project(path)

    assert loaded.schema_version == "1.4"
    item = loaded.objects[0]
    assert item.character_spacing_mm == 0
    assert item.rotation_deg == 0
    assert item.display_diameter_mm == 3
    assert item.color_group == 0


def test_grid_object_round_trips_with_validated_geometry(tmp_path) -> None:
    path = tmp_path / "grid.hplot.json"
    grid = GridObject(
        object_id="grid-1",
        name="Notebook grid",
        x_mm=10,
        y_mm=12,
        width_mm=180,
        height_mm=260,
        cell_width_mm=7,
        cell_height_mm=9,
        line_style="dash_dot",
        color="#336699",
    )
    snapshot = ProjectSnapshot(project_id="grid-project", objects=(grid,))

    save_project(path, snapshot)

    assert load_project(path) == snapshot
    with pytest.raises(ValueError, match="grid exceeds page width"):
        GridObject(object_id="outside", x_mm=100, width_mm=120)


def test_generated_result_round_trips_with_verified_artifacts(tmp_path) -> None:
    from handwriting_plotter.gui.backend import GuiBackend

    path = tmp_path / "calculated.hplot.json"
    snapshot = ProjectSnapshot(
        project_id="calculated-project",
        objects=(TextObject(object_id="text-1", name="Text", text="Alpha"),),
    )
    result = GuiBackend().build(snapshot)

    save_project(path, snapshot, result)
    loaded = load_project_file(path)

    assert loaded.snapshot == snapshot
    assert loaded.cache_warning is None
    assert loaded.generation_result is not None
    assert loaded.generation_result.document_id == result.document_id
    assert loaded.generation_result.report == result.report
    assert loaded.generation_result.files == result.files


def test_invalid_generated_cache_is_ignored_without_losing_project(tmp_path) -> None:
    from handwriting_plotter.gui.backend import GuiBackend

    path = tmp_path / "tampered.hplot.json"
    snapshot = ProjectSnapshot(
        project_id="tampered-project",
        objects=(TextObject(object_id="text-1", name="Text", text="Alpha"),),
    )
    save_project(path, snapshot, GuiBackend().build(snapshot))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["generation_cache"]["source_sha256"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_project_file(path)

    assert loaded.snapshot == snapshot
    assert loaded.generation_result is None
    assert loaded.cache_warning == "GENERATION_CACHE_SOURCE_MISMATCH"


def test_controller_tracks_revision_dirty_and_undo(qtbot) -> None:
    controller = DocumentController(sample_project())
    initial_revision = controller.revision
    controller.update_text_object("text-1", text="Нове значення")
    assert controller.dirty
    assert controller.revision == initial_revision + 1
    assert controller.snapshot.objects[0].text == "Нове значення"
    controller.undo_stack.undo()
    assert controller.snapshot == sample_project()
    assert not controller.dirty
    controller.undo_stack.redo()
    assert controller.snapshot.objects[0].text == "Нове значення"


def test_consecutive_text_typing_merges_into_one_undo_command(qtbot) -> None:
    controller = DocumentController(sample_project())
    original_text = controller.snapshot.objects[0].text

    for value in (original_text + " ", original_text + " w", original_text + " wo", original_text + " word"):
        controller.update_text_object(
            "text-1",
            undo_merge_key="text-content:text-1",
            text=value,
        )

    assert controller.snapshot.objects[0].text == original_text + " word"
    assert controller.undo_stack.count() == 1
    controller.undo_stack.undo()
    assert controller.snapshot.objects[0].text == original_text


def test_properties_typing_uses_merged_text_undo_path(qtbot) -> None:
    from handwriting_plotter.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    item = window.controller.snapshot.objects[0]
    original_text = item.text
    window._selected_kind = "text"
    window._selected_value = item.object_id
    window._selected_object_ids = {item.object_id}
    window._show_selected_properties()

    qtbot.keyClicks(window.properties.text_field, "abc")

    assert window.controller.undo_stack.count() == 1
    assert window.controller.snapshot.objects[0].text != original_text
    window.controller.undo_stack.undo()
    assert window.controller.snapshot.objects[0].text == original_text


def test_controller_moves_multiple_text_objects_in_one_undo_step(qtbot) -> None:
    snapshot = ProjectSnapshot(
        project_id="move-project",
        objects=(
            TextObject(object_id="first", name="First", x_mm=10, y_mm=20, frame_x_mm=5, frame_y_mm=6),
            TextObject(object_id="second", name="Second", x_mm=30, y_mm=40, frame_x_mm=25, frame_y_mm=26),
        ),
    )
    controller = DocumentController(snapshot)

    controller.move_text_objects({"first", "second"}, 3.5, 4.5)

    assert controller.undo_stack.count() == 1
    assert [(item.x_mm, item.y_mm) for item in controller.snapshot.objects] == [(13.5, 24.5), (33.5, 44.5)]
    assert [(item.frame_x_mm, item.frame_y_mm) for item in controller.snapshot.objects] == [(8.5, 10.5), (28.5, 30.5)]
    controller.undo_stack.undo()
    assert controller.snapshot == snapshot


@pytest.mark.parametrize("seed", [-1, 2**64])
def test_text_object_rejects_seed_outside_unsigned_64_bit(seed) -> None:
    with pytest.raises(ValueError, match="seed"):
        TextObject(object_id="seed-test", name="Seed", seed=seed)


def test_text_object_frame_is_bounded_to_a4_and_independent_of_text_origin() -> None:
    item = TextObject(
        object_id="frame-test",
        name="Frame",
        x_mm=90,
        y_mm=100,
        frame_x_mm=20,
        frame_y_mm=30,
        frame_width_mm=70,
        frame_height_mm=40,
    )
    assert (item.frame_x_mm, item.frame_y_mm, item.frame_width_mm, item.frame_height_mm) == (20, 30, 70, 40)
    with pytest.raises(ValueError, match="frame exceeds page width"):
        TextObject.model_validate(
            item.model_copy(update={"frame_x_mm": 180, "frame_width_mm": 40}).model_dump(),
            strict=True,
        )


def test_main_window_object_actions_update_real_model(qtbot) -> None:
    from handwriting_plotter.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    original = len(window.controller.snapshot.objects)
    window.add_text_object()
    assert len(window.controller.snapshot.objects) == original + 1
    assert window.controller.dirty
    window.remove_selected_object()
    assert len(window.controller.snapshot.objects) == original


def test_tree_visibility_change_does_not_destroy_signal_sender(qtbot) -> None:
    from handwriting_plotter.gui.main_window import ROLE_KIND, MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    root = window.project_tree.invisibleRootItem()
    document = root.child(0).child(0)
    node = next(
        document.child(index)
        for index in range(document.childCount())
        if document.child(index).data(0, ROLE_KIND) == "text"
    )
    revision = window.controller.revision

    node.setCheckState(0, Qt.CheckState.Unchecked)

    assert isValid(node)
    qtbot.waitUntil(lambda: window.controller.revision == revision + 1)
    assert window.controller.snapshot.objects[0].visible is False
    window.controller.reset(window.controller.snapshot)


def test_style_catalog_and_property_selection_match_valid_revision(qtbot) -> None:
    from handwriting_plotter.gui.properties import PropertiesPanel
    from handwriting_plotter.gui.styles import discover_styles

    styles = discover_styles()
    assert styles and all(item.valid for item in styles)
    panel = PropertiesPanel(styles)
    qtbot.addWidget(panel)
    item = TextObject(
        object_id="pilot",
        name="Pilot",
        style_id="ua-school-v1-pilot",
        style_revision="0.2.0",
    )
    panel.show_text_object(item)
    assert panel.style_field.currentData().split("\0") == ["ua-school-v1-pilot", "0.2.0"]


def test_seed_property_preserves_full_unsigned_64_bit_precision(qtbot) -> None:
    from handwriting_plotter.gui.properties import PropertiesPanel
    from handwriting_plotter.gui.styles import discover_styles

    panel = PropertiesPanel(discover_styles())
    qtbot.addWidget(panel)
    seed = 2**64 - 1
    item = TextObject(object_id="seed", name="Seed", seed=seed)
    emitted: list[dict] = []
    panel.text_object_changed.connect(lambda _object_id, changes: emitted.append(changes))

    panel.show_text_object(item)
    panel.realism_field.setValue(0.5)

    assert emitted[-1]["seed"] == seed


def test_text_properties_group_pairs_and_edit_independent_frame(qtbot) -> None:
    from handwriting_plotter.gui.properties import PropertiesPanel
    from handwriting_plotter.gui.styles import discover_styles

    panel = PropertiesPanel(discover_styles())
    qtbot.addWidget(panel)
    item = TextObject(
        object_id="frame-properties",
        name="Frame",
        x_mm=25,
        y_mm=36,
        frame_x_mm=20,
        frame_y_mm=30,
        frame_width_mm=70,
        frame_height_mm=40,
    )
    emitted: list[dict] = []
    panel.text_object_changed.connect(lambda _object_id, changes: emitted.append(changes))

    panel.show_text_object(item)
    frame_layout = panel._groups["properties.group.frame"].layout()
    x_position = frame_layout.getItemPosition(frame_layout.indexOf(panel.frame_x_field))
    y_position = frame_layout.getItemPosition(frame_layout.indexOf(panel.frame_y_field))
    assert panel.x_field.value() == 5
    assert panel.y_field.value() == 6
    panel.x_field.setValue(7)
    panel.y_field.setValue(8)
    panel.frame_width_field.setValue(65)

    assert x_position[0] == y_position[0]
    assert x_position[1] != y_position[1]
    assert emitted[-1]["frame_width_mm"] == 65
    assert emitted[-1]["x_mm"] == 27
    assert emitted[-1]["y_mm"] == 38


def test_text_properties_expose_issue_five_controls_and_ukrainian_labels(qtbot) -> None:
    from handwriting_plotter.gui.properties import PropertiesPanel
    from handwriting_plotter.gui.styles import discover_styles

    panel = PropertiesPanel(discover_styles(), language="uk")
    qtbot.addWidget(panel)
    item = TextObject(
        object_id="issue-five",
        name="Issue five",
        x_mm=25,
        y_mm=35,
        frame_x_mm=20,
        frame_y_mm=30,
        character_spacing_mm=1.25,
        rotation_deg=15,
        display_diameter_mm=4,
        color_group=3,
    )
    emitted: list[dict] = []
    panel.text_object_changed.connect(lambda _object_id, changes: emitted.append(changes))

    panel.show_text_object(item)

    assert panel._groups["properties.group.position"].title() == "Початок тексту відносно його зони"
    assert panel._groups["properties.group.frame"].title() == "Робоче поле об’єкта"
    assert panel._labels["properties.text_start_x"].text() == "Початок X"
    assert panel._labels["properties.text_start_y"].text() == "Початок Y"
    assert panel._labels["properties.x_height"].text() == "Висота символів"
    assert len(panel.color_group_buttons) == 16
    assert panel.color_group_buttons[3].isChecked()
    assert panel.content_layout.getItemPosition(panel.content_layout.indexOf(panel.name_field))[0] == 1
    assert panel.content_layout.getItemPosition(panel.content_layout.indexOf(panel.text_field))[0] == 1

    panel.character_spacing_field.setValue(2.0)
    panel.rotation_field.setValue(-25)
    panel.display_diameter_field.setValue(5)
    panel.color_group_buttons[9].click()

    assert emitted[-1]["character_spacing_mm"] == 2.0
    assert emitted[-1]["rotation_deg"] == -25
    assert emitted[-1]["display_diameter_mm"] == 5
    assert emitted[-1]["color_group"] == 9


def test_grid_properties_edit_cells_line_style_color_and_snap(qtbot) -> None:
    from handwriting_plotter.gui.properties import PropertiesPanel
    from handwriting_plotter.gui.styles import discover_styles

    panel = PropertiesPanel(discover_styles(), language="uk")
    qtbot.addWidget(panel)
    grid = GridObject(object_id="grid-properties", line_style="solid", color="#112233")
    emitted: list[dict] = []
    panel.grid_object_changed.connect(lambda _object_id, changes: emitted.append(changes))

    panel.show_grid_object(grid)
    panel.cell_width_field.setValue(8)
    panel.grid_line_style_field.setCurrentIndex(panel.grid_line_style_field.findData("dash_dot"))
    panel.grid_color_field.setText("#AABBCC")
    panel.grid_color_field.editingFinished.emit()
    panel.grid_snap_field.setChecked(False)

    assert emitted[-1]["cell_width_mm"] == 8
    assert emitted[-1]["line_style"] == "dash_dot"
    assert emitted[-1]["color"] == "#AABBCC"
    assert emitted[-1]["snap_enabled"] is False
    assert panel.grid_line_style_field.currentText() == "Штрих-пунктирна"
