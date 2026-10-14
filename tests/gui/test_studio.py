from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, QSettings

from handwriting_plotter.gui.main_window import MainWindow
from handwriting_plotter.gui.studio import HandwritingStudio


def _draw_sample(studio: HandwritingStudio, offset: float = 0.0) -> None:
    canvas = studio.capture_canvas
    canvas.resize(640, 480)
    assert canvas._begin_pointer("mouse", QPointF(100 + offset, 320))
    assert canvas._move_pointer(QPointF(130 + offset, 210 - offset))
    assert canvas._end_pointer(QPointF(170 + offset, 320))
    assert canvas._begin_pointer("mouse", QPointF(190 + offset, 320))
    assert canvas._end_pointer(QPointF(210 + offset, 220 + offset))


def test_workspace_switch_preserves_document_state(qtbot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, user_data_root=tmp_path / "user-data")
    qtbot.addWidget(window)
    window.show()
    object_id = window.controller.snapshot.objects[0].object_id
    window.controller.update_text_object(object_id, text="Документ залишається")
    snapshot = window.controller.snapshot

    window.studio_workspace_action.trigger()

    assert window.workspace_stack.currentWidget() is window.studio
    assert not window.project_dock.isVisible()
    assert not window.properties_dock.isVisible()
    assert window.controller.snapshot == snapshot

    window.document_workspace_action.trigger()

    assert window.workspace_stack.currentWidget() is window.canvas
    assert window.controller.snapshot == snapshot
    assert window.project_dock.isVisible()
    window.controller.reset(snapshot)


def test_studio_saves_reopens_and_recovers_raw_sample(qtbot, tmp_path: Path) -> None:
    studio = HandwritingStudio(tmp_path)
    studio.resize(1100, 700)
    qtbot.addWidget(studio)
    studio.show()
    studio.label_edit.setText("ї")
    studio.style_name.setText("Мій тестовий почерк")
    studio.context_combo.setCurrentText("initial")
    studio.advance_spin.setValue(840.0)
    _draw_sample(studio)

    record = studio.save_sample()

    assert record is not None
    assert record.path.is_file()
    assert len(studio.records) == 1
    assert record.session.samples[0].label == "ї"
    assert len(record.session.samples[0].strokes) == 2
    assert record.session.extensions["cadpisun.studio"]["context_tag"] == "initial"
    assert studio.hash_value.text() == record.sha256
    assert "saved" in studio.diagnostics.toPlainText().lower()

    studio.clear_button.click()
    assert studio.capture_canvas.strokes == ()
    assert studio.open_latest_for_label("ї")
    assert studio.capture_canvas.strokes == record.session.samples[0].strokes

    reopened = HandwritingStudio(tmp_path)
    qtbot.addWidget(reopened)
    assert len(reopened.records) == 1
    assert reopened.open_latest_for_label("ї")
    assert reopened.style_name.text() == "Мій тестовий почерк"
    assert reopened.context_combo.currentText() == "initial"
    assert reopened.advance_spin.value() == 840.0
    assert reopened.capture_canvas.strokes == record.session.samples[0].strokes


def test_studio_actions_and_ukrainian_labels_are_functional(qtbot, tmp_path: Path) -> None:
    studio = HandwritingStudio(tmp_path)
    studio.resize(1000, 650)
    qtbot.addWidget(studio)
    studio.show()
    _draw_sample(studio)
    original = studio.capture_canvas.strokes

    studio.undo_button.click()
    assert len(studio.capture_canvas.strokes) == 1
    studio.redo_button.click()
    assert studio.capture_canvas.strokes == original
    studio.points_check.setChecked(True)
    studio.directions_check.setChecked(True)
    assert studio.capture_canvas._show_points
    assert studio.capture_canvas._show_directions
    studio.zoom_in_button.click()
    assert studio.capture_canvas.zoom_factor > 1.0
    studio.zoom_reset_button.click()
    assert studio.capture_canvas.zoom_factor == 1.0

    studio.search.setText("ґ")
    visible = [
        studio.glyph_list.item(index).data(256)
        for index in range(studio.glyph_list.count())
        if not studio.glyph_list.item(index).isHidden()
    ]
    assert visible == ["ґ"]

    studio.queue_preset.setCurrentIndex(studio.queue_preset.findData("en"))
    assert studio.queue_state.tokens[0] == "a"
    assert studio.queue_state.tokens[-1] == "z"

    studio.set_language("uk")
    assert studio.save_button.text() == "Зберегти зразок"
    assert studio.collection_title.text() == "Колекція знаків"
    assert "Оригінальні точки" in studio.diagnostics.toPlainText()


def test_custom_queue_captures_five_tokens_and_resumes_progress(qtbot, tmp_path: Path) -> None:
    studio = HandwritingStudio(tmp_path)
    studio.resize(1100, 700)
    qtbot.addWidget(studio)
    studio.show()
    studio.custom_queue.setText("а м и н о")
    studio.apply_queue_button.click()
    studio.required_variants.setValue(1)

    for expected in ("а", "м", "и", "н", "о"):
        assert studio.label_edit.text() == expected
        _draw_sample(studio)
        assert studio.save_and_next() is not None

    assert [record.session.samples[0].label for record in studio.records] == ["а", "м", "и", "н", "о"]
    assert studio.coverage_progress.value() == 5
    assert "Missing: 0" in studio.coverage_summary.text()
    assert studio.queue_state.current_index == 4

    resumed = HandwritingStudio(tmp_path)
    qtbot.addWidget(resumed)
    assert resumed.queue_state.tokens == ("а", "м", "и", "н", "о")
    assert resumed.queue_state.current_index == 4
    assert resumed.label_edit.text() == "о"
    assert resumed.coverage_progress.value() == 5

    assert resumed.open_latest_for_label("о")
    digest = resumed.hash_value.text()
    assert resumed.reject_current_sample()
    assert digest in resumed.queue_state.rejected_capture_hashes
    assert resumed.coverage_progress.value() == 4


def test_three_variants_can_be_browsed_preferred_reopened_and_removed(qtbot, tmp_path: Path) -> None:
    studio = HandwritingStudio(tmp_path)
    studio.resize(1200, 760)
    qtbot.addWidget(studio)
    studio.show()
    studio.label_edit.setText("м")

    hashes = []
    for offset in (0.0, 12.0, 24.0):
        _draw_sample(studio, offset)
        record = studio.save_sample()
        assert record is not None
        hashes.append(record.sha256)
        studio.capture_canvas.clear()

    assert studio.variant_list.count() == 3
    studio.variant_list.setCurrentRow(1)
    selected_id = studio.variant_list.currentItem().data(256)
    studio.preferred_button.click()
    preferred = next(item for item in studio.draft_catalog.variants if item.variant_id == selected_id)
    assert preferred.preferred
    assert sum(item.preferred for item in studio.draft_catalog.visible_variants("м")) == 1

    studio.variant_list.itemDoubleClicked.emit(studio.variant_list.currentItem())
    assert studio.hash_value.text() == preferred.capture_sha256
    assert studio.capture_canvas.strokes

    studio.variant_list.setCurrentRow(0)
    deleted_id = studio.variant_list.currentItem().data(256)
    studio.delete_variant_button.click()
    assert studio.variant_list.count() == 2
    deleted = next(item for item in studio.draft_catalog.variants if item.variant_id == deleted_id)
    assert deleted.deleted
    assert deleted.history[-1].action == "deleted"
    assert all(studio.repository.path_for(digest).is_file() for digest in hashes)

    reopened = HandwritingStudio(tmp_path)
    qtbot.addWidget(reopened)
    reopened.label_edit.setText("м")
    assert reopened.variant_list.count() == 2
    assert next(item for item in reopened.draft_catalog.variants if item.variant_id == selected_id).preferred

