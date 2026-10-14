"""Integrated Handwriting Studio for recording and reopening raw samples."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

import regex
from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from handwriting_plotter.capture.models import CaptureProvenance, CaptureSession, WritingGuides
from handwriting_plotter.capture.repository import CaptureRecord, CaptureRepository
from handwriting_plotter.version import __version__

from .capture_widget import HandwritingCaptureWidget
from .i18n import Language, tr

UKRAINIAN_QUEUE = tuple("абвгґдеєжзиіїйклмнопрстуфхцчшщьюя")
ROLE_TOKEN = int(Qt.ItemDataRole.UserRole)


def handwriting_data_root() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if not base:
        raise RuntimeError("APPLICATION_DATA_LOCATION_UNAVAILABLE")
    return Path(base) / "handwriting-studio"


class HandwritingStudio(QWidget):
    """One functional local-first workspace around immutable raw captures."""

    def __init__(
        self,
        root: Path,
        *,
        language: Language = "en",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("handwriting-studio")
        self.root = root
        self.language = language
        self.repository = CaptureRepository(root)
        self._records: list[CaptureRecord] = []
        self._load_errors: list[str] = []
        self._build_ui()
        self._connect()
        self._reload_records()
        self.set_language(language)
        self._refresh_diagnostics()

    @property
    def records(self) -> tuple[CaptureRecord, ...]:
        return tuple(self._records)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        vertical = QSplitter(Qt.Orientation.Vertical)
        upper = QSplitter(Qt.Orientation.Horizontal)
        vertical.addWidget(upper)

        self.collection_panel = QFrame()
        collection_layout = QVBoxLayout(self.collection_panel)
        self.collection_title = QLabel()
        self.collection_title.setObjectName("studio-collection-title")
        self.style_name = QLineEdit("Personal handwriting")
        self.style_name.setObjectName("studio-style-name")
        self.search = QLineEdit()
        self.search.setObjectName("studio-search")
        self.glyph_list = QListWidget()
        self.glyph_list.setObjectName("studio-glyph-collection")
        collection_layout.addWidget(self.collection_title)
        collection_layout.addWidget(self.style_name)
        collection_layout.addWidget(self.search)
        collection_layout.addWidget(self.glyph_list, 1)
        upper.addWidget(self.collection_panel)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(6, 0, 6, 0)
        self.capture_canvas = HandwritingCaptureWidget()
        center_layout.addWidget(self.capture_canvas, 1)
        primary_controls = QHBoxLayout()
        self.undo_button = QPushButton()
        self.redo_button = QPushButton()
        self.remove_stroke_button = QPushButton()
        self.clear_button = QPushButton()
        self.save_button = QPushButton()
        for button in (
            self.undo_button, self.redo_button, self.remove_stroke_button,
            self.clear_button, self.save_button,
        ):
            primary_controls.addWidget(button)
        center_layout.addLayout(primary_controls)
        view_controls = QHBoxLayout()
        self.points_check = QCheckBox()
        self.directions_check = QCheckBox()
        self.zoom_out_button = QPushButton("−")
        self.zoom_reset_button = QPushButton("1:1")
        self.zoom_in_button = QPushButton("+")
        for widget in (
            self.points_check, self.directions_check, self.zoom_out_button,
            self.zoom_reset_button, self.zoom_in_button,
        ):
            view_controls.addWidget(widget)
        view_controls.addStretch(1)
        center_layout.addLayout(view_controls)
        upper.addWidget(center)

        self.properties_group = QGroupBox()
        form = QFormLayout(self.properties_group)
        self.label_edit = QLineEdit("а")
        self.label_edit.setObjectName("studio-unicode-label")
        self.variant_edit = QLineEdit()
        self.variant_edit.setObjectName("studio-variant-id")
        self.context_combo = QComboBox()
        self.context_combo.addItems(("isolated", "initial", "medial", "final"))
        self.advance_spin = QDoubleSpinBox()
        self.advance_spin.setRange(1.0, 10000.0)
        self.advance_spin.setDecimals(1)
        self.advance_spin.setValue(900.0)
        self.baseline_spin = QDoubleSpinBox()
        self.baseline_spin.setRange(1.0, 10000.0)
        self.x_height_spin = QDoubleSpinBox()
        self.x_height_spin.setRange(0.0, 9999.0)
        self.source_value = QLabel("online_capture")
        self.stroke_count_value = QLabel("0")
        self.point_count_value = QLabel("0")
        self.pressure_value = QLabel("—")
        self.review_value = QLabel("draft")
        self.hash_value = QLabel("—")
        self.hash_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._property_rows = (
            ("studio.label", self.label_edit),
            ("studio.variant", self.variant_edit),
            ("studio.context", self.context_combo),
            ("studio.advance", self.advance_spin),
            ("studio.baseline", self.baseline_spin),
            ("studio.x_height", self.x_height_spin),
            ("studio.source", self.source_value),
            ("studio.strokes", self.stroke_count_value),
            ("studio.points", self.point_count_value),
            ("studio.pressure", self.pressure_value),
            ("studio.review", self.review_value),
            ("studio.raw_hash", self.hash_value),
        )
        self._property_labels: dict[str, QLabel] = {}
        for key, widget in self._property_rows:
            label = QLabel()
            self._property_labels[key] = label
            form.addRow(label, widget)
        upper.addWidget(self.properties_group)
        upper.setStretchFactor(0, 1)
        upper.setStretchFactor(1, 4)
        upper.setStretchFactor(2, 1)

        diagnostics_panel = QWidget()
        diagnostics_layout = QVBoxLayout(diagnostics_panel)
        diagnostics_layout.setContentsMargins(6, 0, 6, 6)
        self.diagnostics_title = QLabel()
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setObjectName("studio-diagnostics")
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumBlockCount(300)
        diagnostics_layout.addWidget(self.diagnostics_title)
        diagnostics_layout.addWidget(self.diagnostics)
        vertical.addWidget(diagnostics_panel)
        vertical.setStretchFactor(0, 5)
        vertical.setStretchFactor(1, 1)
        root_layout.addWidget(vertical)

    def _connect(self) -> None:
        self.search.textChanged.connect(self._filter_collection)
        self.glyph_list.currentItemChanged.connect(self._select_glyph)
        self.glyph_list.itemDoubleClicked.connect(lambda item: self.open_latest_for_label(item.data(ROLE_TOKEN)))
        self.label_edit.textChanged.connect(self._label_changed)
        self.capture_canvas.strokes_changed.connect(self._capture_changed)
        self.undo_button.clicked.connect(self.capture_canvas.undo_stroke)
        self.redo_button.clicked.connect(self.capture_canvas.redo_stroke)
        self.remove_stroke_button.clicked.connect(self.capture_canvas.undo_stroke)
        self.clear_button.clicked.connect(self._clear_sample)
        self.save_button.clicked.connect(self.save_sample)
        self.points_check.toggled.connect(self.capture_canvas.set_show_points)
        self.directions_check.toggled.connect(self.capture_canvas.set_show_directions)
        self.zoom_out_button.clicked.connect(
            lambda: self.capture_canvas.set_zoom_factor(self.capture_canvas.zoom_factor / 1.25)
        )
        self.zoom_reset_button.clicked.connect(self.capture_canvas.reset_view)
        self.zoom_in_button.clicked.connect(
            lambda: self.capture_canvas.set_zoom_factor(self.capture_canvas.zoom_factor * 1.25)
        )
        self.baseline_spin.valueChanged.connect(self._apply_guide_controls)
        self.x_height_spin.valueChanged.connect(self._apply_guide_controls)

    def set_language(self, language: Language) -> None:
        self.language = language
        self.collection_title.setText(tr(language, "studio.collection"))
        self.style_name.setPlaceholderText(tr(language, "studio.style_name"))
        self.search.setPlaceholderText(tr(language, "studio.search"))
        self.properties_group.setTitle(tr(language, "studio.properties"))
        self.diagnostics_title.setText(tr(language, "studio.diagnostics"))
        for key, label in self._property_labels.items():
            label.setText(tr(language, key))
        self.undo_button.setText(tr(language, "studio.undo"))
        self.redo_button.setText(tr(language, "studio.redo"))
        self.remove_stroke_button.setText(tr(language, "studio.remove_stroke"))
        self.clear_button.setText(tr(language, "studio.clear"))
        self.save_button.setText(tr(language, "studio.save"))
        self.points_check.setText(tr(language, "studio.points_toggle"))
        self.directions_check.setText(tr(language, "studio.directions_toggle"))
        self._refresh_collection()
        self._refresh_diagnostics()

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        self._sync_guide_controls()

    def save_sample(self) -> CaptureRecord | None:
        try:
            label = unicodedata.normalize("NFC", self.label_edit.text().strip())
            classification = "glyph" if len(regex.findall(r"\X", label)) == 1 else "sequence"
            now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            sample = self.capture_canvas.build_sample(
                sample_id=f"sample-{uuid.uuid4().hex}",
                label=label,
                classification=classification,
                provenance=CaptureProvenance(
                    source="online_capture",
                    captured_at_utc=now,
                    timing_source="monotonic",
                    application_version=__version__,
                ),
            )
            session = CaptureSession(
                session_id=f"session-{uuid.uuid4().hex}",
                created_at_utc=now,
                device=self.capture_canvas.device_capabilities,
                samples=(sample,),
                extensions={
                    "cadpisun.studio": {
                        "style_name": self.style_name.text().strip() or "Personal handwriting",
                        "variant_id": self.variant_edit.text().strip() or self._suggest_variant_id(label),
                        "context_tag": self.context_combo.currentText(),
                        "advance_gu": self.advance_spin.value(),
                        "review_status": "draft",
                    },
                },
            )
            record = self.repository.store(session)
        except Exception as exc:
            self.diagnostics.setPlainText(f"{tr(self.language, 'studio.invalid')}\n{exc}")
            return None
        self._records.append(record)
        self.hash_value.setText(record.sha256)
        self._refresh_collection()
        self._refresh_diagnostics(tr(self.language, "studio.saved").format(hash=record.sha256[:12]))
        return record

    def open_latest_for_label(self, label: str) -> bool:
        candidates = [record for record in self._records if record.session.samples[0].label == label]
        if not candidates:
            self._refresh_diagnostics(tr(self.language, "studio.no_sample").format(label=label))
            return False
        record = max(candidates, key=lambda item: item.session.created_at_utc)
        self.open_record(record)
        return True

    def open_record(self, record: CaptureRecord) -> None:
        sample = record.session.samples[0]
        self.capture_canvas.load_sample(sample, record.session.device)
        self.label_edit.setText(sample.label)
        metadata = record.session.extensions.get("cadpisun.studio", {})
        if isinstance(metadata, dict):
            self.style_name.setText(str(metadata.get("style_name", self.style_name.text())))
            self.variant_edit.setText(str(metadata.get("variant_id", self._suggest_variant_id(sample.label))))
            context = str(metadata.get("context_tag", "isolated"))
            index = self.context_combo.findText(context)
            if index >= 0:
                self.context_combo.setCurrentIndex(index)
            advance = metadata.get("advance_gu")
            if isinstance(advance, (int, float)) and not isinstance(advance, bool):
                self.advance_spin.setValue(float(advance))
        self.hash_value.setText(record.sha256)
        self._sync_guide_controls()
        self._refresh_diagnostics(tr(self.language, "studio.opened").format(hash=record.sha256[:12]))

    def _reload_records(self) -> None:
        try:
            self._records = list(self.repository.list_records())
        except Exception as exc:
            self._records = []
            self._load_errors.append(str(exc))
        self._refresh_collection()

    def _refresh_collection(self) -> None:
        selected = self.label_edit.text().strip()
        counts: dict[str, int] = {}
        for record in self._records:
            label = record.session.samples[0].label
            counts[label] = counts.get(label, 0) + 1
        tokens = list(UKRAINIAN_QUEUE)
        for label in sorted(counts):
            if label not in tokens:
                tokens.append(label)
        self.glyph_list.blockSignals(True)
        self.glyph_list.clear()
        for token in tokens:
            count = counts.get(token, 0)
            marker = "✓" if count else "○"
            item = QListWidgetItem(f"{marker}  {token}   · {count}")
            item.setData(ROLE_TOKEN, token)
            self.glyph_list.addItem(item)
            if token == selected:
                self.glyph_list.setCurrentItem(item)
        self.glyph_list.blockSignals(False)
        self._filter_collection(self.search.text())

    def _filter_collection(self, query: str) -> None:
        normalized = query.casefold().strip()
        for index in range(self.glyph_list.count()):
            item = self.glyph_list.item(index)
            item.setHidden(normalized not in str(item.data(ROLE_TOKEN)).casefold())

    def _select_glyph(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is not None:
            self.label_edit.setText(str(current.data(ROLE_TOKEN)))

    def _label_changed(self, label: str) -> None:
        if not self.variant_edit.hasFocus():
            self.variant_edit.setText(self._suggest_variant_id(label.strip()))
        self._refresh_diagnostics()

    def _capture_changed(self, strokes: int, points: int) -> None:
        self.stroke_count_value.setText(str(strokes))
        self.point_count_value.setText(str(points))
        self.pressure_value.setText(
            tr(self.language, "studio.available")
            if self.capture_canvas.device_capabilities.pressure
            else tr(self.language, "studio.unavailable")
        )
        self.undo_button.setEnabled(bool(strokes))
        self.remove_stroke_button.setEnabled(bool(strokes))
        self.redo_button.setEnabled(self.capture_canvas.can_redo)
        self._refresh_diagnostics()

    def _clear_sample(self) -> None:
        self.capture_canvas.clear()
        self.hash_value.setText("—")
        self.review_value.setText("draft")
        self._sync_guide_controls()

    def _sync_guide_controls(self) -> None:
        guides = self.capture_canvas.writing_guides
        for spin, value in ((self.baseline_spin, guides.baseline_y), (self.x_height_spin, guides.x_height_y)):
            spin.blockSignals(True)
            spin.setMaximum(self.capture_canvas.coordinate_reference.height)
            spin.setValue(value)
            spin.blockSignals(False)

    def _apply_guide_controls(self) -> None:
        current = self.capture_canvas.writing_guides
        baseline = self.baseline_spin.value()
        x_height = self.x_height_spin.value()
        try:
            self.capture_canvas.set_writing_guides(WritingGuides(
                ascender_y=min(current.ascender_y, x_height),
                x_height_y=x_height,
                baseline_y=baseline,
                descender_y=max(current.descender_y, baseline),
            ))
        except ValueError as exc:
            self._refresh_diagnostics(str(exc))

    def _refresh_diagnostics(self, headline: str | None = None) -> None:
        messages: list[str] = []
        if headline:
            messages.append(headline)
        messages.extend(self._load_errors)
        label = unicodedata.normalize("NFC", self.label_edit.text().strip())
        if not label:
            messages.append(tr(self.language, "studio.missing_label"))
        if not self.capture_canvas.strokes:
            messages.append(tr(self.language, "studio.missing_strokes"))
        if label and self.capture_canvas.strokes:
            messages.append(tr(self.language, "studio.valid_raw"))
        messages.append(tr(self.language, "studio.raw_notice"))
        self.diagnostics.setPlainText("\n".join(messages))
        self.save_button.setEnabled(bool(label and self.capture_canvas.strokes))

    def _suggest_variant_id(self, label: str) -> str:
        if not label:
            return ""
        code = "-".join(f"u-{ord(char):04x}" for char in label)
        count = sum(record.session.samples[0].label == label for record in self._records) + 1
        return f"{code}-v{count}"

