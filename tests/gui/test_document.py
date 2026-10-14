from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from shiboken6 import isValid

from handwriting_plotter.gui.document import (
    DocumentController,
    ProjectSnapshot,
    TextObject,
    load_project,
    load_project_file,
    save_project,
)
from handwriting_plotter.gui import document as document_module


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


def test_project_v1_0_is_loaded_and_migrated_in_memory(tmp_path) -> None:
    path = tmp_path / "legacy.hplot.json"
    data = sample_project().model_dump(mode="json")
    data["schema_version"] = "1.0"
    path.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_project(path)

    assert loaded.schema_version == "1.1"
    assert loaded.project_id == sample_project().project_id


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


@pytest.mark.parametrize("seed", [-1, 2**64])
def test_text_object_rejects_seed_outside_unsigned_64_bit(seed) -> None:
    with pytest.raises(ValueError, match="seed"):
        TextObject(object_id="seed-test", name="Seed", seed=seed)


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
    from handwriting_plotter.gui.main_window import MainWindow, ROLE_KIND

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
