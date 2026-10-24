from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QFileDialog

import cv2
import numpy as np

from handwriting_plotter.gui.photo_import import PhotoImportWorkspace
from handwriting_plotter.gui.studio import HandwritingStudio


def _write_photo(path: Path, width: int = 180, height: int = 120) -> bytes:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#f7f0dc"))
    for x in range(15, width - 15):
        image.setPixelColor(x, height // 2, QColor("#23395d"))
    assert image.save(str(path), "PNG")
    return path.read_bytes()


def _write_perspective_page(path: Path) -> bytes:
    image = np.full((520, 760, 3), 32, dtype=np.uint8)
    page = np.array(((100, 55), (665, 82), (700, 470), (72, 448)), dtype=np.int32)
    cv2.fillConvexPoly(image, page, (244, 242, 226))
    for y in range(125, 430, 45):
        cv2.line(image, (105, y), (660, y + 12), (205, 175, 115), 2)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    path.write_bytes(encoded.tobytes())
    return path.read_bytes()


def _write_ruled_page(path: Path) -> bytes:
    image = np.full((360, 520, 3), 245, dtype=np.uint8)
    for y in range(30, 350, 30):
        cv2.line(image, (10, y), (510, y), (190, 155, 100), 1)
    for x in range(40, 440, 65):
        cv2.line(image, (x, 92), (x + 35, 98), (35, 35, 35), 2)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    path.write_bytes(encoded.tobytes())
    return path.read_bytes()


def test_import_persists_exact_source_and_populates_comparison(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "зошит.png"
    original = _write_photo(source)
    workspace = PhotoImportWorkspace(tmp_path / "store")
    qtbot.addWidget(workspace)
    workspace.resize(1000, 700)
    workspace.show()

    record = workspace.import_path(source)

    assert record is not None
    assert record.photo.original_sha256 == sha256(original).hexdigest()
    assert workspace.repository.original_path(record.photo.original_sha256).read_bytes() == original
    assert record.path.is_file()
    assert workspace.original_view.has_image
    assert workspace.corrected_view.has_image
    assert workspace.original_view.scene().itemsBoundingRect().size().toSize() == QImage.fromData(original).size()
    diagnostics = workspace.diagnostics.toPlainText()
    assert "180 × 120 px" in diagnostics
    assert record.photo.original_sha256 in diagnostics
    assert "png · image/png" in diagnostics
    assert "not applied" in diagnostics


def test_preview_controls_do_not_mutate_immutable_source(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "sample.png"
    original = _write_photo(source, width=160, height=90)
    workspace = PhotoImportWorkspace(tmp_path / "store")
    qtbot.addWidget(workspace)
    assert workspace.import_path(source) is not None

    workspace.actual_size_button.click()
    workspace.zoom_in_button.click()
    assert workspace.original_view.zoom_factor == pytest.approx(1.25)
    assert workspace.corrected_view.zoom_factor == pytest.approx(1.25)

    workspace.rotate_right_button.click()
    assert workspace.display_rotation == 90
    assert workspace.original_view.scene().itemsBoundingRect().size().toSize().width() == 160
    corrected_size = workspace.corrected_view.scene().itemsBoundingRect().size().toSize()
    assert (corrected_size.width(), corrected_size.height()) == (90, 160)

    workspace.reset_button.click()
    assert workspace.display_rotation == 0
    assert workspace.repository.original_path(sha256(original).hexdigest()).read_bytes() == original
    assert workspace.current_record is not None
    assert workspace.current_record.photo.transforms == ()


def test_failed_import_keeps_last_verified_photo_visible(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "valid.png"
    _write_photo(source)
    invalid = tmp_path / "invalid.png"
    invalid.write_text("not an image", encoding="utf-8")
    workspace = PhotoImportWorkspace(tmp_path / "store")
    qtbot.addWidget(workspace)
    record = workspace.import_path(source)
    assert record is not None

    assert workspace.import_path(invalid) is None

    assert workspace.current_record == record
    assert workspace.original_view.has_image
    assert "Import failed" in workspace.status_label.text()
    assert not workspace.repository.manifest_path(sha256(invalid.read_bytes()).hexdigest()).exists()


def test_latest_verified_photo_is_restored(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "restored.png"
    original = _write_photo(source, width=210, height=140)
    first = PhotoImportWorkspace(tmp_path / "store")
    qtbot.addWidget(first)
    record = first.import_path(source)
    assert record is not None

    reopened = PhotoImportWorkspace(tmp_path / "store")
    qtbot.addWidget(reopened)

    assert reopened.current_record == record
    assert reopened.original_view.has_image
    assert reopened.repository.read_original(record.photo) == original
    assert "Restored verified photo" in reopened.status_label.text()


def test_file_picker_and_ukrainian_ui(qtbot, tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "picked.png"
    _write_photo(source)
    workspace = PhotoImportWorkspace(tmp_path / "store", language="uk")
    qtbot.addWidget(workspace)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(source), "Images"),
    )

    workspace.choose_button.click()

    assert workspace.current_record is not None
    assert "Імпортовано" in workspace.status_label.text()
    assert workspace.original_group.title() == "Оригінал"
    assert "перспектив" in workspace.correction_notice.text().lower()


def test_photo_import_is_a_separate_studio_workflow(qtbot, tmp_path: Path) -> None:
    studio = HandwritingStudio(tmp_path, language="en")
    qtbot.addWidget(studio)

    assert studio.workflow_tabs.count() == 2
    assert studio.workflow_tabs.widget(1) is studio.photo_import
    assert studio.workflow_tabs.tabText(1) == "Import from photo"
    assert studio.workflow_tabs.widget(0).isAncestorOf(studio.capture_canvas)
    assert not studio.capture_canvas.isAncestorOf(studio.photo_import)


def test_automatic_page_proposal_correction_and_restore(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "perspective.png"
    original = _write_perspective_page(source)
    root = tmp_path / "store"
    workspace = PhotoImportWorkspace(root)
    qtbot.addWidget(workspace)
    assert workspace.import_path(source) is not None

    workspace.detect_page_button.click()

    assert len(workspace.original_view._corner_handles) == 4
    assert workspace.apply_correction_button.isEnabled()
    assert "proposal ready" in workspace.status_label.text().lower()
    workspace.deskew_check.setChecked(True)
    workspace.deskew_spin.setValue(0.5)
    workspace.apply_correction_button.click()

    assert workspace.current_record is not None
    assert len(workspace.current_record.photo.transforms) == 1
    transform = workspace.current_record.photo.transforms[0]
    assert transform.parameters["proposal_method"] == "opencv-contour-quad/1"
    assert transform.parameters["deskew_degrees"] == 0.5
    assert workspace.repository.read_original(workspace.current_record.photo) == original
    assert not workspace._corrected_pixmap.isNull()
    assert "Correction saved" in workspace.status_label.text()

    workspace.analyze_paper_button.click()
    assert workspace.current_record.photo.ruling.status == "proposed"
    assert workspace.current_record.photo.ruling.frame_id == transform.output_frame_id

    reopened = PhotoImportWorkspace(root)
    qtbot.addWidget(reopened)
    assert reopened.current_record is not None
    assert len(reopened.current_record.photo.transforms) == 1
    assert not reopened._corrected_pixmap.isNull()
    assert "perspective correction applied" in reopened.correction_notice.text().lower()


def test_no_page_diagnostic_leads_to_manual_corner_fallback(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "blank.png"
    _write_photo(source, width=320, height=240)
    workspace = PhotoImportWorkspace(tmp_path / "store")
    qtbot.addWidget(workspace)
    assert workspace.import_path(source) is not None

    workspace.detect_page_button.click()

    assert "No reliable planar page boundary" in workspace.status_label.text()
    assert not workspace.apply_correction_button.isEnabled()
    workspace.manual_corners_button.click()
    assert len(workspace.original_view._corner_handles) == 4
    assert workspace.apply_correction_button.isEnabled()

    workspace.apply_correction_button.click()

    assert workspace.current_record is not None
    assert len(workspace.current_record.photo.transforms) == 1
    assert workspace.current_record.photo.transforms[0].parameters["proposal_method"] == "manual-four-corner/1"


def test_paper_analysis_and_manual_override_are_persisted(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "ruled.png"
    _write_ruled_page(source)
    root = tmp_path / "store"
    workspace = PhotoImportWorkspace(root)
    qtbot.addWidget(workspace)
    assert workspace.import_path(source) is not None

    workspace.analyze_paper_button.click()

    assert workspace.current_record is not None
    assert workspace.current_record.photo.ruling.classification == "ruled"
    assert workspace.current_record.photo.ruling.status == "proposed"
    assert "Paper proposal: Ruled" in workspace.status_label.text()
    assert "Ruled · proposed" in workspace.diagnostics.toPlainText()

    workspace.detect_geometry_button.click()

    assert workspace.current_record.photo.ruling.ruling_pitch_px == pytest.approx(30.0, abs=1.0)
    assert "Ruling geometry proposal saved" in workspace.status_label.text()
    workspace.show_ruling_overlay_check.setChecked(True)
    assert len(workspace.original_view._ruling_overlay) >= 10
    workspace.pitch_y_spin.setValue(31.5)
    workspace.apply_geometry_button.click()
    assert workspace.current_record.photo.ruling.status == "overridden"
    assert workspace.current_record.photo.ruling.ruling_pitch_px == 31.5
    assert "manual override" in workspace.diagnostics.toPlainText()
    geometry_reopened = PhotoImportWorkspace(root)
    qtbot.addWidget(geometry_reopened)
    assert geometry_reopened.current_record is not None
    assert geometry_reopened.current_record.photo.ruling.ruling_pitch_px == 31.5

    workspace.paper_classification_combo.setCurrentIndex(
        workspace.paper_classification_combo.findData("squared")
    )
    workspace.override_ruling_button.click()

    assert workspace.current_record.photo.ruling.classification == "squared"
    assert workspace.current_record.photo.ruling.status == "overridden"
    assert "Paper classification saved: Squared" in workspace.status_label.text()
    reopened = PhotoImportWorkspace(root)
    qtbot.addWidget(reopened)
    assert reopened.current_record is not None
    assert reopened.current_record.photo.ruling.classification == "squared"
    assert reopened.current_record.photo.ruling.status == "overridden"


def test_physical_scale_is_explicit_persisted_and_invalidated_by_geometry_edit(
    qtbot, tmp_path: Path
) -> None:
    source = tmp_path / "ruled.png"
    _write_ruled_page(source)
    root = tmp_path / "store"
    workspace = PhotoImportWorkspace(root)
    qtbot.addWidget(workspace)
    assert workspace.import_path(source) is not None

    workspace.analyze_paper_button.click()
    workspace.detect_geometry_button.click()
    assert workspace.current_record is not None
    assert workspace.current_record.photo.calibration is None
    assert workspace.apply_scale_button.isEnabled()

    workspace.scale_reference_spin.setValue(4.0)
    workspace.apply_scale_button.click()
    calibration = workspace.current_record.photo.calibration
    assert calibration is not None
    assert calibration.source == "user_entered"
    assert calibration.reference_pitch_mm == 4.0
    assert calibration.mm_per_px_x is None
    assert calibration.mm_per_px_y == pytest.approx(4.0 / 30.0, abs=0.01)
    assert "Physical scale saved" in workspace.status_label.text()

    reopened = PhotoImportWorkspace(root)
    qtbot.addWidget(reopened)
    assert reopened.current_record is not None
    assert reopened.current_record.photo.calibration == calibration
    assert "user-entered reference" in reopened.scale_summary_label.text()

    workspace.pitch_y_spin.setValue(31.0)
    workspace.apply_geometry_button.click()
    assert workspace.current_record.photo.calibration is None
    assert "Physical scale unknown" in workspace.scale_summary_label.text()

    workspace.apply_5mm_preset_button.click()
    preset = workspace.current_record.photo.calibration
    assert preset is not None
    assert preset.source == "notebook_cell_preset"
    assert preset.reference_pitch_mm == 5.0
    assert preset.mm_per_px_y == pytest.approx(5.0 / 31.0)


def test_ink_mask_review_and_raw_override_are_persisted(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "ruled.png"
    _write_ruled_page(source)
    root = tmp_path / "store"
    workspace = PhotoImportWorkspace(root)
    qtbot.addWidget(workspace)
    assert workspace.import_path(source) is not None
    workspace.analyze_paper_button.click()
    workspace.detect_geometry_button.click()

    workspace.separate_ink_button.click()
    assert workspace.current_record is not None
    mask = workspace.current_record.photo.ink_mask
    assert mask is not None
    assert mask.selected_variant == "cleaned"
    assert "masks saved" in workspace.status_label.text()
    assert workspace.use_raw_mask_button.isEnabled()

    workspace.use_raw_mask_button.click()
    assert workspace.current_record.photo.ink_mask is not None
    assert workspace.current_record.photo.ink_mask.selected_variant == "raw"
    assert workspace.current_record.photo.ink_mask.status == "overridden"
    reopened = PhotoImportWorkspace(root)
    qtbot.addWidget(reopened)
    assert reopened.current_record is not None
    assert reopened.current_record.photo.ink_mask == workspace.current_record.photo.ink_mask

    workspace.pitch_y_spin.setValue(31.0)
    workspace.apply_geometry_button.click()
    assert workspace.current_record.photo.ink_mask is None
