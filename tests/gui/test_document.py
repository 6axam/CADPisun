from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from handwriting_plotter.gui.document import (
    DocumentController,
    ProjectSnapshot,
    TextObject,
    load_project,
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


def test_project_rejects_unknown_schema(tmp_path) -> None:
    path = tmp_path / "future.hplot.json"
    data = sample_project().model_dump(mode="json")
    data["schema_version"] = "99.0"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="UNSUPPORTED_PROJECT_SCHEMA"):
        load_project(path)


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
