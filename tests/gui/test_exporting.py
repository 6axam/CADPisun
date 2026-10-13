from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from handwriting_plotter.gui.backend import GuiBackend
from handwriting_plotter.gui.document import ProjectSnapshot, TextObject
from handwriting_plotter.gui.exporting import export_artifact


@pytest.fixture(scope="module")
def result():
    snapshot = ProjectSnapshot(
        project_id="export-test",
        objects=(TextObject(object_id="text", name="Text", text="SVG GCODE"),),
    )
    return GuiBackend().build(snapshot)


@pytest.mark.parametrize("artifact", ["page-0001.svg", "page-0001.preview.svg", "page-0001.gcode", "report.json"])
def test_export_copies_exact_accepted_bytes_atomically(tmp_path, result, artifact) -> None:
    target = tmp_path / artifact
    export_artifact(result, artifact, target)
    assert target.read_bytes() == result.files[artifact]
    assert not list(tmp_path.glob("*.tmp"))


def test_export_rejects_internal_artifacts(tmp_path, result) -> None:
    with pytest.raises(ValueError, match="ARTIFACT_NOT_EXPORTABLE"):
        export_artifact(result, "page-0001.motion.json", tmp_path / "motion.json")


def test_export_actions_require_current_revision(qtbot) -> None:
    from handwriting_plotter.gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert all(not action.isEnabled() for action in window.export_actions)
    window.generate_page()
    qtbot.waitUntil(lambda: window._generation_worker is None, timeout=10_000)
    assert all(action.isEnabled() for action in window.export_actions)
    item = window.controller.snapshot.objects[0]
    window.controller.update_text_object(item.object_id, text="Changed")
    assert all(not action.isEnabled() for action in window.export_actions)
    machine_labels = [action.text() for action in window.machine_menu.actions()]
    assert not any("send" in label.lower() for label in machine_labels)
