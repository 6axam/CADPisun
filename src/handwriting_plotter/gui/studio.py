"""Integrated Handwriting Studio for recording and reopening raw samples."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

import regex
from PySide6.QtCore import QPointF, QSize, QStandardPaths, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
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
    QProgressBar,
    QPushButton,
    QSplitter,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from handwriting_plotter.capture.models import CaptureProvenance, CaptureSession, WritingGuides
from handwriting_plotter.capture.annotation import (
    AnnotationStore,
    GlyphAnnotation,
    StrokeRoleAssignment,
    annotation_to_glyph_variant,
    create_anchor_annotation,
    preview_join,
)
from handwriting_plotter.capture.drafts import DraftCatalog, DraftEvent, DraftStore, VariantDraft
from handwriting_plotter.capture.metrics import (
    GlyphMetricOverride,
    MetricProfileStore,
    NormalizedRecord,
    NormalizedRepository,
    StyleMetricProfile,
    normalize_processed_glyph,
)
from handwriting_plotter.capture.processing import (
    ProcessedRecord,
    ProcessedRepository,
    ProcessingParameters,
    process_sample,
)
from handwriting_plotter.capture.queue import CaptureQueueState, CaptureQueueStore
from handwriting_plotter.capture.repository import CaptureRecord, CaptureRepository
from handwriting_plotter.version import __version__

from .capture_widget import HandwritingCaptureWidget
from .i18n import Language, tr
from .normalization_preview import JoinPairPreview, NormalizationPreview

UKRAINIAN_QUEUE = tuple("абвгґдеєжзиіїйклмнопрстуфхцчшщьюя")
RUSSIAN_QUEUE = tuple("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
ENGLISH_QUEUE = tuple("abcdefghijklmnopqrstuvwxyz")
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
        self.processed_repository = ProcessedRepository(root)
        self.metric_store = MetricProfileStore(root)
        self.normalized_repository = NormalizedRepository(root)
        self.annotation_store = AnnotationStore(root)
        self.queue_store = CaptureQueueStore(root)
        self.draft_store = DraftStore(root)
        self._records: list[CaptureRecord] = []
        self._processed_record: ProcessedRecord | None = None
        self._processing_status = ""
        self._normalized_record: NormalizedRecord | None = None
        self._normalization_status = ""
        self._annotation: GlyphAnnotation | None = None
        self._annotation_roles: dict[str, str] = {}
        self._annotation_status = ""
        self._load_errors: list[str] = []
        try:
            self.queue_state = self.queue_store.load("default")
        except FileNotFoundError:
            self.queue_state = CaptureQueueState(
                queue_id="default", name="Ukrainian", tokens=UKRAINIAN_QUEUE
            )
        except Exception as exc:
            self._load_errors.append(str(exc))
            self.queue_state = CaptureQueueState(
                queue_id="default", name="Ukrainian", tokens=UKRAINIAN_QUEUE
            )
        try:
            self.draft_catalog = self.draft_store.load("personal")
        except FileNotFoundError:
            self.draft_catalog = DraftCatalog(style_id="personal", display_name="Personal handwriting")
        except Exception as exc:
            self._load_errors.append(str(exc))
            self.draft_catalog = DraftCatalog(style_id="personal", display_name="Personal handwriting")
        try:
            self.metric_profile: StyleMetricProfile | None = self.metric_store.load("personal")
        except FileNotFoundError:
            self.metric_profile = None
        except Exception as exc:
            self._load_errors.append(str(exc))
            self.metric_profile = None
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
        self.queue_preset = QComboBox()
        self.queue_preset.setObjectName("studio-queue-preset")
        for key in ("uk", "ru", "en", "custom"):
            self.queue_preset.addItem(key, key)
        self.custom_queue = QLineEdit()
        self.custom_queue.setObjectName("studio-custom-queue")
        self.apply_queue_button = QPushButton()
        queue_row = QHBoxLayout()
        queue_row.addWidget(self.custom_queue, 1)
        queue_row.addWidget(self.apply_queue_button)
        required_row = QHBoxLayout()
        self.required_variants_label = QLabel()
        self.required_variants = QSpinBox()
        self.required_variants.setRange(1, 99)
        self.required_variants.setValue(self.queue_state.required_variants)
        required_row.addWidget(self.required_variants_label)
        required_row.addWidget(self.required_variants)
        self.queue_context = QLabel()
        self.queue_context.setObjectName("studio-queue-context")
        navigation = QHBoxLayout()
        self.previous_button = QPushButton("←")
        self.next_button = QPushButton("→")
        self.skip_button = QPushButton()
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.skip_button)
        navigation.addWidget(self.next_button)
        self.coverage_progress = QProgressBar()
        self.coverage_progress.setObjectName("studio-coverage-progress")
        self.coverage_summary = QLabel()
        self.coverage_summary.setObjectName("studio-coverage-summary")
        self.glyph_list = QListWidget()
        self.glyph_list.setObjectName("studio-glyph-collection")
        collection_layout.addWidget(self.collection_title)
        collection_layout.addWidget(self.style_name)
        collection_layout.addWidget(self.search)
        collection_layout.addWidget(self.queue_preset)
        collection_layout.addLayout(queue_row)
        collection_layout.addLayout(required_row)
        collection_layout.addWidget(self.queue_context)
        collection_layout.addLayout(navigation)
        collection_layout.addWidget(self.coverage_progress)
        collection_layout.addWidget(self.coverage_summary)
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
        self.save_next_button = QPushButton()
        self.retry_button = QPushButton()
        self.open_existing_button = QPushButton()
        self.reject_button = QPushButton()
        for button in (
            self.undo_button, self.redo_button, self.remove_stroke_button,
            self.clear_button, self.retry_button, self.save_button, self.save_next_button,
            self.open_existing_button, self.reject_button,
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
        processing_controls = QHBoxLayout()
        self.tolerance_label = QLabel()
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setObjectName("studio-processing-tolerance")
        self.tolerance_spin.setRange(0.05, 100.0)
        self.tolerance_spin.setDecimals(2)
        self.tolerance_spin.setSingleStep(0.1)
        self.tolerance_spin.setValue(1.0)
        self.smoothing_label = QLabel()
        self.smoothing_spin = QSpinBox()
        self.smoothing_spin.setRange(0, 8)
        self.process_button = QPushButton()
        self.process_button.setObjectName("studio-process")
        self.undo_processing_button = QPushButton()
        self.undo_processing_button.setObjectName("studio-undo-processing")
        self.raw_check = QCheckBox()
        self.raw_check.setChecked(True)
        self.processed_check = QCheckBox()
        self.processed_check.setChecked(True)
        for widget in (
            self.tolerance_label, self.tolerance_spin, self.smoothing_label, self.smoothing_spin,
            self.process_button, self.undo_processing_button, self.raw_check, self.processed_check,
        ):
            processing_controls.addWidget(widget)
        processing_controls.addStretch(1)
        center_layout.addLayout(processing_controls)
        normalization_controls = QHBoxLayout()
        self.physical_size_label = QLabel()
        self.physical_size_spin = QDoubleSpinBox()
        self.physical_size_spin.setRange(2.5, 5.0)
        self.physical_size_spin.setDecimals(2)
        self.physical_size_spin.setValue(
            self.metric_profile.preview_x_height_mm if self.metric_profile is not None else 3.5
        )
        self.left_bearing_label = QLabel()
        self.left_bearing_spin = QDoubleSpinBox()
        self.left_bearing_spin.setRange(0.0, 2000.0)
        self.left_bearing_spin.setValue(50.0)
        self.right_bearing_label = QLabel()
        self.right_bearing_spin = QDoubleSpinBox()
        self.right_bearing_spin.setRange(0.0, 2000.0)
        self.right_bearing_spin.setValue(50.0)
        self.baseline_offset_label = QLabel()
        self.baseline_offset_spin = QDoubleSpinBox()
        self.baseline_offset_spin.setRange(-500.0, 500.0)
        self.baseline_offset_spin.setValue(0.0)
        self.set_metrics_button = QPushButton()
        self.normalize_button = QPushButton()
        self.normalize_button.setObjectName("studio-normalize")
        for widget in (
            self.physical_size_label, self.physical_size_spin,
            self.left_bearing_label, self.left_bearing_spin,
            self.right_bearing_label, self.right_bearing_spin,
            self.baseline_offset_label, self.baseline_offset_spin,
            self.set_metrics_button, self.normalize_button,
        ):
            normalization_controls.addWidget(widget)
        normalization_controls.addStretch(1)
        center_layout.addLayout(normalization_controls)
        upper.addWidget(center)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.properties_group = QGroupBox()
        form = QFormLayout(self.properties_group)
        self.label_edit = QLineEdit(self.queue_state.tokens[self.queue_state.current_index])
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
        self.processed_hash_value = QLabel("—")
        self.processed_hash_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.normalized_hash_value = QLabel("—")
        self.normalized_hash_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
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
            ("studio.processed_hash", self.processed_hash_value),
            ("studio.normalized_hash", self.normalized_hash_value),
        )
        self._property_labels: dict[str, QLabel] = {}
        for key, widget in self._property_rows:
            label = QLabel()
            self._property_labels[key] = label
            form.addRow(label, widget)
        right_layout.addWidget(self.properties_group)
        self.variants_title = QLabel()
        self.variant_list = QListWidget()
        self.variant_list.setObjectName("studio-variant-browser")
        self.variant_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.variant_list.setIconSize(QSize(120, 80))
        self.variant_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.variant_list.setMovement(QListWidget.Movement.Static)
        variant_actions = QHBoxLayout()
        self.preferred_button = QPushButton()
        self.delete_variant_button = QPushButton()
        variant_actions.addWidget(self.preferred_button)
        variant_actions.addWidget(self.delete_variant_button)
        right_layout.addWidget(self.variants_title)
        right_layout.addWidget(self.variant_list, 1)
        right_layout.addLayout(variant_actions)
        self.normalization_title = QLabel()
        self.normalization_preview = NormalizationPreview()
        right_layout.addWidget(self.normalization_title)
        right_layout.addWidget(self.normalization_preview)
        self.annotation_group = QGroupBox()
        annotation_form = QFormLayout(self.annotation_group)
        self.annotation_stroke_combo = QComboBox()
        role_row = QWidget()
        role_layout = QHBoxLayout(role_row)
        role_layout.setContentsMargins(0, 0, 0, 0)
        self.annotation_role_combo = QComboBox()
        self.annotation_role_combo.addItems(("body", "mark", "punctuation"))
        self.assign_role_button = QPushButton()
        role_layout.addWidget(self.annotation_role_combo)
        role_layout.addWidget(self.assign_role_button)
        self.annotation_mode_combo = QComboBox()
        self.annotation_mode_combo.addItems(("none", "single_body_deferred_marks"))
        self.annotation_body_combo = QComboBox()
        anchor_row = QWidget()
        anchor_layout = QHBoxLayout(anchor_row)
        anchor_layout.setContentsMargins(0, 0, 0, 0)
        self.annotation_entry_check = QCheckBox()
        self.annotation_exit_check = QCheckBox()
        anchor_layout.addWidget(self.annotation_entry_check)
        anchor_layout.addWidget(self.annotation_exit_check)
        no_join_row = QWidget()
        no_join_layout = QHBoxLayout(no_join_row)
        no_join_layout.setContentsMargins(0, 0, 0, 0)
        self.no_join_before_check = QCheckBox()
        self.no_join_after_check = QCheckBox()
        no_join_layout.addWidget(self.no_join_before_check)
        no_join_layout.addWidget(self.no_join_after_check)
        self.anchor_class_edit = QLineEdit("cursive")
        self.anchor_partners_edit = QLineEdit("cursive")
        limits_row = QWidget()
        limits_layout = QHBoxLayout(limits_row)
        limits_layout.setContentsMargins(0, 0, 0, 0)
        self.anchor_gap_spin = QDoubleSpinBox()
        self.anchor_gap_spin.setRange(1.0, 5000.0)
        self.anchor_gap_spin.setValue(500.0)
        self.anchor_vertical_spin = QDoubleSpinBox()
        self.anchor_vertical_spin.setRange(0.0, 5000.0)
        self.anchor_vertical_spin.setValue(200.0)
        self.anchor_angle_spin = QDoubleSpinBox()
        self.anchor_angle_spin.setRange(1.0, 180.0)
        self.anchor_angle_spin.setValue(60.0)
        limits_layout.addWidget(self.anchor_gap_spin)
        limits_layout.addWidget(self.anchor_vertical_spin)
        limits_layout.addWidget(self.anchor_angle_spin)
        self.annotation_tangent_value = QLabel("—")
        self.annotation_save_button = QPushButton()
        self.annotation_partner_combo = QComboBox()
        self.annotation_preview_button = QPushButton()
        pair_row = QWidget()
        pair_layout = QHBoxLayout(pair_row)
        pair_layout.setContentsMargins(0, 0, 0, 0)
        pair_layout.addWidget(self.annotation_partner_combo, 1)
        pair_layout.addWidget(self.annotation_preview_button)
        self.join_preview = JoinPairPreview()
        self._annotation_labels: dict[str, QLabel] = {}
        for key, widget in (
            ("studio.annotation_stroke", self.annotation_stroke_combo),
            ("studio.annotation_role", role_row),
            ("studio.annotation_mode", self.annotation_mode_combo),
            ("studio.annotation_body", self.annotation_body_combo),
            ("studio.annotation_anchors", anchor_row),
            ("studio.annotation_no_join", no_join_row),
            ("studio.annotation_class", self.anchor_class_edit),
            ("studio.annotation_partners", self.anchor_partners_edit),
            ("studio.annotation_limits", limits_row),
            ("studio.annotation_tangents", self.annotation_tangent_value),
            ("studio.annotation_pair", pair_row),
        ):
            label = QLabel()
            self._annotation_labels[key] = label
            annotation_form.addRow(label, widget)
        annotation_form.addRow(self.annotation_save_button)
        annotation_form.addRow(self.join_preview)
        right_layout.addWidget(self.annotation_group)
        upper.addWidget(right)
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
        self.queue_preset.currentIndexChanged.connect(self._apply_preset)
        self.apply_queue_button.clicked.connect(self._apply_custom_queue)
        self.required_variants.valueChanged.connect(self._required_variants_changed)
        self.previous_button.clicked.connect(lambda: self._move_queue(-1))
        self.next_button.clicked.connect(lambda: self._move_queue(1))
        self.skip_button.clicked.connect(self._skip_current)
        self.glyph_list.currentItemChanged.connect(self._select_glyph)
        self.glyph_list.itemDoubleClicked.connect(lambda item: self.open_latest_for_label(item.data(ROLE_TOKEN)))
        self.label_edit.textChanged.connect(self._label_changed)
        self.capture_canvas.strokes_changed.connect(self._capture_changed)
        self.undo_button.clicked.connect(self.capture_canvas.undo_stroke)
        self.redo_button.clicked.connect(self.capture_canvas.redo_stroke)
        self.remove_stroke_button.clicked.connect(self.capture_canvas.undo_stroke)
        self.clear_button.clicked.connect(self._clear_sample)
        self.retry_button.clicked.connect(self._retry_current)
        self.save_button.clicked.connect(self.save_sample)
        self.save_next_button.clicked.connect(self.save_and_next)
        self.open_existing_button.clicked.connect(self._open_current)
        self.reject_button.clicked.connect(self.reject_current_sample)
        self.variant_list.itemDoubleClicked.connect(self._open_variant_item)
        self.preferred_button.clicked.connect(self._set_selected_preferred)
        self.delete_variant_button.clicked.connect(self._delete_selected_variant)
        self.points_check.toggled.connect(self.capture_canvas.set_show_points)
        self.directions_check.toggled.connect(self.capture_canvas.set_show_directions)
        self.raw_check.toggled.connect(self.capture_canvas.set_show_raw)
        self.processed_check.toggled.connect(self.capture_canvas.set_show_processed)
        self.process_button.clicked.connect(self.process_current)
        self.undo_processing_button.clicked.connect(self.undo_processing)
        self.tolerance_spin.valueChanged.connect(self._processing_parameters_changed)
        self.smoothing_spin.valueChanged.connect(self._processing_parameters_changed)
        self.normalize_button.clicked.connect(self.normalize_current)
        self.set_metrics_button.clicked.connect(self.set_style_metrics_from_current)
        for spin in (
            self.physical_size_spin, self.left_bearing_spin,
            self.right_bearing_spin, self.baseline_offset_spin, self.advance_spin,
        ):
            spin.valueChanged.connect(self._normalization_parameters_changed)
        self.variant_edit.textChanged.connect(self._normalization_parameters_changed)
        self.context_combo.currentIndexChanged.connect(self._normalization_parameters_changed)
        self.annotation_stroke_combo.currentIndexChanged.connect(self._annotation_stroke_selected)
        self.assign_role_button.clicked.connect(self._assign_annotation_role)
        self.annotation_save_button.clicked.connect(self.save_annotation)
        self.annotation_preview_button.clicked.connect(self.preview_annotation_pair)
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
        self.variants_title.setText(tr(language, "studio.variants"))
        self.preferred_button.setText(tr(language, "studio.preferred"))
        self.delete_variant_button.setText(tr(language, "studio.delete_variant"))
        self.diagnostics_title.setText(tr(language, "studio.diagnostics"))
        for key, label in self._property_labels.items():
            label.setText(tr(language, key))
        self.undo_button.setText(tr(language, "studio.undo"))
        self.redo_button.setText(tr(language, "studio.redo"))
        self.remove_stroke_button.setText(tr(language, "studio.remove_stroke"))
        self.clear_button.setText(tr(language, "studio.clear"))
        self.save_button.setText(tr(language, "studio.save"))
        self.save_next_button.setText(tr(language, "studio.save_next"))
        self.retry_button.setText(tr(language, "studio.retry"))
        self.open_existing_button.setText(tr(language, "studio.open_existing"))
        self.reject_button.setText(tr(language, "studio.reject"))
        self.skip_button.setText(tr(language, "studio.skip"))
        self.apply_queue_button.setText(tr(language, "studio.apply_queue"))
        self.required_variants_label.setText(tr(language, "studio.required_variants"))
        self.custom_queue.setPlaceholderText(tr(language, "studio.custom_queue"))
        current_preset = self.queue_preset.currentData()
        self.queue_preset.blockSignals(True)
        for index, key in enumerate(("uk", "ru", "en", "custom")):
            self.queue_preset.setItemText(index, tr(language, f"studio.queue.{key}"))
        self.queue_preset.setCurrentIndex(max(0, self.queue_preset.findData(current_preset)))
        self.queue_preset.blockSignals(False)
        self.points_check.setText(tr(language, "studio.points_toggle"))
        self.directions_check.setText(tr(language, "studio.directions_toggle"))
        self.tolerance_label.setText(tr(language, "studio.tolerance"))
        self.smoothing_label.setText(tr(language, "studio.smoothing"))
        self.process_button.setText(tr(language, "studio.process"))
        self.undo_processing_button.setText(tr(language, "studio.undo_processing"))
        self.raw_check.setText(tr(language, "studio.raw_toggle"))
        self.processed_check.setText(tr(language, "studio.processed_toggle"))
        self.physical_size_label.setText(tr(language, "studio.physical_size"))
        self.left_bearing_label.setText(tr(language, "studio.left_bearing"))
        self.right_bearing_label.setText(tr(language, "studio.right_bearing"))
        self.baseline_offset_label.setText(tr(language, "studio.baseline_offset"))
        self.set_metrics_button.setText(tr(language, "studio.set_style_metrics"))
        self.normalize_button.setText(tr(language, "studio.normalize"))
        self.normalization_title.setText(tr(language, "studio.normalization_preview"))
        self.normalization_preview.set_empty_text(tr(language, "studio.no_normalized_glyph"))
        self.annotation_group.setTitle(tr(language, "studio.annotation_title"))
        for key, label in self._annotation_labels.items():
            label.setText(tr(language, key))
        self.assign_role_button.setText(tr(language, "studio.annotation_assign"))
        self.annotation_entry_check.setText(tr(language, "studio.annotation_entry"))
        self.annotation_exit_check.setText(tr(language, "studio.annotation_exit"))
        self.no_join_before_check.setText(tr(language, "studio.annotation_no_before"))
        self.no_join_after_check.setText(tr(language, "studio.annotation_no_after"))
        self.annotation_save_button.setText(tr(language, "studio.annotation_save"))
        self.annotation_preview_button.setText(tr(language, "studio.annotation_preview"))
        self.join_preview.set_empty_text(tr(language, "studio.annotation_no_preview"))
        self._refresh_collection()
        self._refresh_variants()
        self._refresh_queue_status()
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
        self._add_record_to_draft(record)
        self._clear_processing_state()
        self.hash_value.setText(record.sha256)
        self._refresh_collection()
        self._refresh_variants()
        self._refresh_diagnostics(tr(self.language, "studio.saved").format(hash=record.sha256[:12]))
        return record

    def process_current(self) -> ProcessedRecord | None:
        """Process the visible raw sample and persist a linked derivative."""
        digest = self.hash_value.text()
        if len(digest) != 64:
            raw_record = self.save_sample()
            if raw_record is None:
                return None
            digest = raw_record.sha256
        record = next((item for item in self._records if item.sha256 == digest), None)
        if record is None:
            self._processing_status = tr(self.language, "studio.processing_source_missing")
            self._refresh_diagnostics()
            return None
        try:
            parameters = ProcessingParameters(
                max_deviation_px=self.tolerance_spin.value(),
                smoothing_passes=self.smoothing_spin.value(),
            )
            processed = process_sample(record.session.samples[0], digest, parameters)
            processed_record = self.processed_repository.store(processed)
        except Exception as exc:
            self._processing_status = f"{tr(self.language, 'studio.processing_failed')}\n{exc}"
            self._refresh_diagnostics()
            return None
        self._processed_record = processed_record
        self._clear_normalization_state()
        self.capture_canvas.set_processed_strokes(processed.to_strokes())
        self.processed_hash_value.setText(processed_record.sha256)
        maximum = max(report.certified_max_deviation_px for report in processed.reports)
        self._processing_status = tr(self.language, "studio.processed").format(
            hash=processed_record.sha256[:12], error=maximum,
        )
        self._refresh_diagnostics()
        return processed_record

    def normalize_current(self) -> NormalizedRecord | None:
        processed_record = self._processed_record or self.process_current()
        if processed_record is None:
            return None
        raw_record = next(
            (item for item in self._records
             if item.sha256 == processed_record.processed.source_capture_sha256),
            None,
        )
        if raw_record is None:
            self._normalization_status = tr(self.language, "studio.normalization_source_missing")
            self._refresh_diagnostics()
            return None
        if self.metric_profile is None and self.set_style_metrics_from_current() is None:
            return None
        assert self.metric_profile is not None
        if abs(self.metric_profile.preview_x_height_mm - self.physical_size_spin.value()) > 1e-9:
            values = self.metric_profile.model_dump(mode="python")
            values.update({
                "revision": self.metric_profile.revision + 1,
                "preview_x_height_mm": self.physical_size_spin.value(),
            })
            try:
                self.metric_profile = StyleMetricProfile.model_validate(values, strict=True)
                self.metric_store.save(self.metric_profile)
            except Exception as exc:
                self._normalization_status = f"{tr(self.language, 'studio.normalization_failed')}\n{exc}"
                self._refresh_diagnostics()
                return None
        sample = raw_record.session.samples[0]
        variant_id = self.variant_edit.text().strip() or self._suggest_variant_id(sample.label)
        override = GlyphMetricOverride(
            variant_id=variant_id,
            advance_gu=self.advance_spin.value(),
            left_bearing_gu=self.left_bearing_spin.value(),
            minimum_right_bearing_gu=self.right_bearing_spin.value(),
            baseline_offset_gu=self.baseline_offset_spin.value(),
        )
        try:
            glyph = normalize_processed_glyph(
                processed_record.processed,
                processed_record.sha256,
                sample,
                self.metric_profile,
                variant_id=variant_id,
                label=sample.label,
                context_tag=self.context_combo.currentText(),
                override=override,
            )
            normalized_record = self.normalized_repository.store(glyph)
        except Exception as exc:
            self._normalization_status = f"{tr(self.language, 'studio.normalization_failed')}\n{exc}"
            self._refresh_diagnostics()
            return None
        self._normalized_record = normalized_record
        self.normalized_hash_value.setText(normalized_record.sha256)
        self.normalization_preview.set_glyph(glyph)
        self._load_annotation_for_normalized(normalized_record)
        advance_mm = glyph.advance_gu * glyph.preview_x_height_mm / 1000.0
        self._normalization_status = tr(self.language, "studio.normalized").format(
            hash=normalized_record.sha256[:12], advance=advance_mm,
        )
        self._refresh_diagnostics()
        return normalized_record

    def set_style_metrics_from_current(self) -> StyleMetricProfile | None:
        digest = self.hash_value.text()
        if len(digest) != 64:
            record = self.save_sample()
            if record is None:
                return None
        else:
            record = next((item for item in self._records if item.sha256 == digest), None)
            if record is None:
                self._normalization_status = tr(self.language, "studio.normalization_source_missing")
                self._refresh_diagnostics()
                return None
        sample = record.session.samples[0]
        revision = 1 if self.metric_profile is None else self.metric_profile.revision + 1
        previous = self.metric_profile
        try:
            profile = StyleMetricProfile.from_sample(
                "personal", sample, preview_x_height_mm=self.physical_size_spin.value()
            )
            values = profile.model_dump(mode="python")
            values.update({
                "revision": revision,
                "default_advance_gu": self.advance_spin.value(),
                "default_left_bearing_gu": self.left_bearing_spin.value(),
                "minimum_right_bearing_gu": self.right_bearing_spin.value(),
                "space_advance_gu": previous.space_advance_gu if previous else 900.0,
                "line_gap_gu": previous.line_gap_gu if previous else 500.0,
            })
            profile = StyleMetricProfile.model_validate(values, strict=True)
            self.metric_store.save(profile)
        except Exception as exc:
            self._normalization_status = f"{tr(self.language, 'studio.normalization_failed')}\n{exc}"
            self._refresh_diagnostics()
            return None
        self.metric_profile = profile
        self._clear_normalization_state()
        self._normalization_status = tr(self.language, "studio.style_metrics_saved").format(
            revision=profile.revision
        )
        self._refresh_diagnostics()
        return profile

    def undo_processing(self) -> bool:
        """Remove the derivative from the view while retaining immutable raw data."""
        if self._processed_record is None:
            return False
        self._clear_processing_state()
        self._processing_status = tr(self.language, "studio.processing_undone")
        self._refresh_diagnostics()
        return True

    def _restore_latest_processed(self, source_hash: str) -> None:
        self._clear_processing_state()
        try:
            records = self.processed_repository.list_for_source(source_hash)
        except Exception as exc:
            self._processing_status = f"{tr(self.language, 'studio.processing_failed')}\n{exc}"
            return
        if not records:
            return
        record = records[-1]
        self._processed_record = record
        parameters = record.processed.parameters
        for spin, value in (
            (self.tolerance_spin, parameters.max_deviation_px),
            (self.smoothing_spin, parameters.smoothing_passes),
        ):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.capture_canvas.set_processed_strokes(record.processed.to_strokes())
        self.processed_hash_value.setText(record.sha256)
        maximum = max(item.certified_max_deviation_px for item in record.processed.reports)
        self._processing_status = tr(self.language, "studio.processed_reopened").format(
            hash=record.sha256[:12], error=maximum,
        )
        self._restore_latest_normalized(record.sha256)

    def _restore_latest_normalized(self, processed_hash: str) -> None:
        self._clear_normalization_state()
        try:
            records = self.normalized_repository.list_for_processed(processed_hash)
        except Exception as exc:
            self._normalization_status = f"{tr(self.language, 'studio.normalization_failed')}\n{exc}"
            return
        if not records:
            return
        record = records[-1]
        self._normalized_record = record
        self.normalized_hash_value.setText(record.sha256)
        self.normalization_preview.set_glyph(record.glyph)
        self._load_annotation_for_normalized(record)
        self._normalization_status = tr(self.language, "studio.normalized_reopened").format(
            hash=record.sha256[:12]
        )

    def _clear_processing_state(self) -> None:
        self._processed_record = None
        self.capture_canvas.clear_processed()
        self.processed_hash_value.setText("—")
        self._processing_status = ""
        self._clear_normalization_state()

    def _clear_normalization_state(self) -> None:
        self._normalized_record = None
        self.normalized_hash_value.setText("—")
        self.normalization_preview.set_glyph(None)
        self._normalization_status = ""
        self._annotation = None
        self._annotation_roles = {}
        self.annotation_stroke_combo.clear()
        self.annotation_body_combo.clear()
        self.annotation_tangent_value.setText("—")
        self.join_preview.clear()
        self._annotation_status = ""

    def _processing_parameters_changed(self) -> None:
        if self._processed_record is None:
            return
        self._clear_processing_state()
        self._processing_status = tr(self.language, "studio.processing_parameters_changed")
        self._refresh_diagnostics()

    def _normalization_parameters_changed(self, *_args) -> None:
        if self._normalized_record is None:
            return
        self._clear_normalization_state()
        self._normalization_status = tr(self.language, "studio.normalization_parameters_changed")
        self._refresh_diagnostics()

    def _load_annotation_for_normalized(self, record: NormalizedRecord) -> None:
        glyph = record.glyph
        ids = tuple(item.id for item in glyph.strokes)
        self._annotation_roles = {
            stroke_id: ("body" if index == 0 else "mark")
            for index, stroke_id in enumerate(ids)
        }
        self.annotation_stroke_combo.blockSignals(True)
        self.annotation_body_combo.blockSignals(True)
        self.annotation_stroke_combo.clear()
        self.annotation_body_combo.clear()
        self.annotation_stroke_combo.addItems(ids)
        self.annotation_body_combo.addItems(ids)
        self.annotation_stroke_combo.blockSignals(False)
        self.annotation_body_combo.blockSignals(False)
        self._annotation_stroke_selected()
        try:
            annotation = self.annotation_store.load(record.sha256)
        except FileNotFoundError:
            annotation = None
        except Exception as exc:
            self._annotation_status = f"{tr(self.language, 'studio.annotation_invalid')}\n{exc}"
            annotation = None
        if annotation is not None:
            self._annotation = annotation
            self._annotation_roles = {item.stroke_id: item.role for item in annotation.stroke_roles}
            self.annotation_mode_combo.setCurrentText(annotation.join_mode)
            if annotation.body_stroke_id:
                self.annotation_body_combo.setCurrentText(annotation.body_stroke_id)
            self.annotation_entry_check.setChecked(annotation.entry is not None)
            self.annotation_exit_check.setChecked(annotation.exit is not None)
            self.no_join_before_check.setChecked(annotation.no_join_before)
            self.no_join_after_check.setChecked(annotation.no_join_after)
            anchor = annotation.entry or annotation.exit
            if anchor is not None:
                self.anchor_class_edit.setText(anchor.class_id)
                self.anchor_partners_edit.setText(", ".join(anchor.allowed_partner_classes))
                self.anchor_gap_spin.setValue(anchor.max_gap_gu)
                self.anchor_vertical_spin.setValue(anchor.max_vertical_delta_gu)
                self.anchor_angle_spin.setValue(anchor.max_angle_deg)
            self._annotation_status = tr(self.language, "studio.annotation_reopened").format(
                revision=annotation.revision
            )
            self._show_annotation_tangents(annotation)
            self._annotation_stroke_selected()
        self._refresh_annotation_partners()

    def _annotation_stroke_selected(self) -> None:
        stroke_id = self.annotation_stroke_combo.currentText()
        role = self._annotation_roles.get(stroke_id, "body")
        self.annotation_role_combo.setCurrentText(role)

    def _assign_annotation_role(self) -> None:
        stroke_id = self.annotation_stroke_combo.currentText()
        if not stroke_id:
            return
        self._annotation_roles[stroke_id] = self.annotation_role_combo.currentText()
        self._annotation_status = tr(self.language, "studio.annotation_role_set").format(
            stroke=stroke_id, role=self.annotation_role_combo.currentText()
        )
        self._refresh_diagnostics()

    def save_annotation(self) -> GlyphAnnotation | None:
        record = self._normalized_record
        if record is None:
            self._annotation_status = tr(self.language, "studio.annotation_requires_normalized")
            self._refresh_diagnostics()
            return None
        glyph = record.glyph
        ids = tuple(item.id for item in glyph.strokes)
        mode = self.annotation_mode_combo.currentText()
        body = self.annotation_body_combo.currentText() if mode == "single_body_deferred_marks" else None
        partners = tuple(
            value.strip() for value in self.anchor_partners_edit.text().split(",") if value.strip()
        )
        revision = 1 if self._annotation is None else self._annotation.revision + 1
        try:
            anchor_kwargs = {
                "class_id": self.anchor_class_edit.text().strip(),
                "allowed_partner_classes": partners,
                "max_gap_gu": self.anchor_gap_spin.value(),
                "max_vertical_delta_gu": self.anchor_vertical_spin.value(),
                "max_angle_deg": self.anchor_angle_spin.value(),
            }
            entry = (
                create_anchor_annotation(glyph, body, "start", **anchor_kwargs)
                if body and self.annotation_entry_check.isChecked() else None
            )
            exit_anchor = (
                create_anchor_annotation(glyph, body, "end", **anchor_kwargs)
                if body and self.annotation_exit_check.isChecked() else None
            )
            deferred = tuple(item for item in ids if item != body) if body else ()
            annotation = GlyphAnnotation(
                source_normalized_sha256=record.sha256,
                source_processed_sha256=glyph.source_processed_sha256,
                variant_id=glyph.variant_id,
                label=glyph.label,
                revision=revision,
                context_tags=frozenset({self.context_combo.currentText()}),
                stroke_order=ids,
                stroke_roles=tuple(StrokeRoleAssignment(
                    stroke_id=item, role=self._annotation_roles.get(item, "mark")
                ) for item in ids),
                join_mode=mode,
                body_stroke_id=body,
                deferred_marks=deferred,
                entry=entry,
                exit=exit_anchor,
                no_join_before=self.no_join_before_check.isChecked(),
                no_join_after=self.no_join_after_check.isChecked(),
                critical_features=tuple(item for item in deferred if self._annotation_roles.get(item) == "mark"),
            )
            self.annotation_store.save(annotation)
        except Exception as exc:
            self._annotation_status = f"{tr(self.language, 'studio.annotation_invalid')}\n{exc}"
            self._refresh_diagnostics()
            return None
        self._annotation = annotation
        self._show_annotation_tangents(annotation)
        self._annotation_status = tr(self.language, "studio.annotation_saved").format(
            revision=annotation.revision
        )
        self._refresh_annotation_partners()
        self._refresh_diagnostics()
        return annotation

    def _show_annotation_tangents(self, annotation: GlyphAnnotation) -> None:
        def value(anchor) -> str:  # noqa: ANN001
            if anchor is None:
                return "—"
            return f"({anchor.tangent.x:.3f}, {anchor.tangent.y:.3f})"
        self.annotation_tangent_value.setText(
            f"{tr(self.language, 'studio.annotation_entry')}: {value(annotation.entry)}   "
            f"{tr(self.language, 'studio.annotation_exit')}: {value(annotation.exit)}"
        )

    def _refresh_annotation_partners(self) -> None:
        selected = self.annotation_partner_combo.currentData()
        self.annotation_partner_combo.clear()
        try:
            annotations = self.annotation_store.list_all()
        except Exception as exc:
            self._annotation_status = f"{tr(self.language, 'studio.annotation_invalid')}\n{exc}"
            return
        for item in annotations:
            self.annotation_partner_combo.addItem(
                f"{item.label} · {item.variant_id}", item.source_normalized_sha256
            )
        if selected is not None:
            index = self.annotation_partner_combo.findData(selected)
            if index >= 0:
                self.annotation_partner_combo.setCurrentIndex(index)

    def preview_annotation_pair(self):  # noqa: ANN201
        left_annotation = self._annotation or self.save_annotation()
        normalized_hash = self.annotation_partner_combo.currentData()
        if left_annotation is None or not isinstance(normalized_hash, str):
            self._annotation_status = tr(self.language, "studio.annotation_partner_missing")
            self._refresh_diagnostics()
            return None
        try:
            right_annotation = self.annotation_store.load(normalized_hash)
            left_glyph = self.normalized_repository.load(
                left_annotation.source_processed_sha256, left_annotation.source_normalized_sha256
            )
            right_glyph = self.normalized_repository.load(
                right_annotation.source_processed_sha256, right_annotation.source_normalized_sha256
            )
            left_file = annotation_to_glyph_variant(left_annotation, left_glyph)
            right_file = annotation_to_glyph_variant(right_annotation, right_glyph)
            result = preview_join(
                left_file, right_file, x_height_mm=self.physical_size_spin.value()
            )
        except Exception as exc:
            self._annotation_status = f"{tr(self.language, 'studio.annotation_invalid')}\n{exc}"
            self._refresh_diagnostics()
            return None
        status = tr(self.language, f"studio.join.{result.decision}").format(reason=result.reason)
        self.join_preview.set_pair(
            left_file, right_file, result, status,
            x_height_mm=self.physical_size_spin.value(),
        )
        self._annotation_status = status
        self._refresh_diagnostics()
        return result

    def save_and_next(self) -> CaptureRecord | None:
        record = self.save_sample()
        if record is not None:
            self._move_queue(1)
            self.capture_canvas.clear()
        return record

    def open_latest_for_label(self, label: str) -> bool:
        candidates = [
            record for record in self._records
            if record.session.samples[0].label == label
            and record.sha256 not in self.queue_state.rejected_capture_hashes
        ]
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
        self._restore_latest_processed(record.sha256)
        self._sync_guide_controls()
        self._refresh_diagnostics(tr(self.language, "studio.opened").format(hash=record.sha256[:12]))
        self._refresh_variants()

    def _reload_records(self) -> None:
        try:
            self._records = list(self.repository.list_records())
        except Exception as exc:
            self._records = []
            self._load_errors.append(str(exc))
        self._sync_draft_catalog()
        self._refresh_collection()

    def _refresh_collection(self) -> None:
        selected = self.label_edit.text().strip()
        counts: dict[str, int] = {}
        for record in self._records:
            if record.sha256 in self.queue_state.rejected_capture_hashes:
                continue
            label = record.session.samples[0].label
            counts[label] = counts.get(label, 0) + 1
        tokens = list(self.queue_state.tokens)
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
        self._refresh_queue_status()

    def _filter_collection(self, query: str) -> None:
        normalized = query.casefold().strip()
        for index in range(self.glyph_list.count()):
            item = self.glyph_list.item(index)
            item.setHidden(normalized not in str(item.data(ROLE_TOKEN)).casefold())

    def _select_glyph(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is not None:
            token = str(current.data(ROLE_TOKEN))
            self.label_edit.setText(token)
            if token in self.queue_state.tokens:
                self._set_queue_state(current_index=self.queue_state.tokens.index(token))

    def _label_changed(self, label: str) -> None:
        if len(self.hash_value.text()) == 64:
            self.hash_value.setText("—")
            self._clear_processing_state()
            self._processing_status = tr(self.language, "studio.processing_invalidated")
        if not self.variant_edit.hasFocus():
            self.variant_edit.setText(self._suggest_variant_id(label.strip()))
        self._refresh_diagnostics()
        self._refresh_variants()

    def _capture_changed(self, strokes: int, points: int) -> None:
        had_processed = self._processed_record is not None
        self._clear_processing_state()
        if len(self.hash_value.text()) == 64:
            self.hash_value.setText("—")
        if had_processed:
            self._processing_status = tr(self.language, "studio.processing_invalidated")
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
        self._clear_processing_state()
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
            self.hash_value.setText("—")
            self._clear_processing_state()
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
        if self._processing_status:
            messages.append(self._processing_status)
        if self._normalization_status:
            messages.append(self._normalization_status)
        if self._annotation_status:
            messages.append(self._annotation_status)
        self.diagnostics.setPlainText("\n".join(messages))
        self.save_button.setEnabled(bool(label and self.capture_canvas.strokes))
        self.save_next_button.setEnabled(bool(label and self.capture_canvas.strokes))
        self.process_button.setEnabled(bool(label and self.capture_canvas.strokes))
        self.undo_processing_button.setEnabled(self._processed_record is not None)
        self.normalize_button.setEnabled(bool(label and self.capture_canvas.strokes))
        self.set_metrics_button.setEnabled(bool(label and self.capture_canvas.strokes))
        self.annotation_save_button.setEnabled(self._normalized_record is not None)
        self.annotation_preview_button.setEnabled(self._annotation is not None)

    def _queue_counts(self) -> dict[str, int]:
        counts = {token: 0 for token in self.queue_state.tokens}
        for record in self._records:
            if record.sha256 in self.queue_state.rejected_capture_hashes:
                continue
            label = record.session.samples[0].label
            if label in counts:
                counts[label] += 1
        return counts

    def _refresh_queue_status(self) -> None:
        tokens = self.queue_state.tokens
        index = self.queue_state.current_index
        previous = tokens[index - 1] if index > 0 else "—"
        current = tokens[index]
        following = tokens[index + 1] if index + 1 < len(tokens) else "—"
        self.queue_context.setText(
            tr(self.language, "studio.queue_context").format(
                previous=previous, current=current, next=following,
            )
        )
        counts = self._queue_counts()
        complete = sum(counts[token] >= self.queue_state.required_variants for token in tokens)
        missing = len(tokens) - complete
        self.coverage_progress.setRange(0, len(tokens))
        self.coverage_progress.setValue(complete)
        self.coverage_summary.setText(
            tr(self.language, "studio.coverage_summary").format(
                captured=complete,
                missing=missing,
                variants=counts[current],
                total=len(tokens),
            )
        )
        self.previous_button.setEnabled(index > 0)
        self.next_button.setEnabled(index + 1 < len(tokens))

    def _set_queue_state(self, **changes) -> None:  # noqa: ANN003
        data = self.queue_state.model_dump(mode="python")
        data.update(changes)
        self.queue_state = CaptureQueueState.model_validate(data, strict=True)
        self.queue_store.save(self.queue_state)
        self.required_variants.blockSignals(True)
        self.required_variants.setValue(self.queue_state.required_variants)
        self.required_variants.blockSignals(False)
        self._refresh_collection()

    def _move_queue(self, delta: int) -> None:
        target = max(0, min(len(self.queue_state.tokens) - 1, self.queue_state.current_index + delta))
        self._set_queue_state(current_index=target)
        self.label_edit.setText(self.queue_state.tokens[target])

    def _skip_current(self) -> None:
        skipped = set(self.queue_state.skipped_tokens)
        skipped.add(self.queue_state.tokens[self.queue_state.current_index])
        self._set_queue_state(skipped_tokens=frozenset(skipped))
        self._move_queue(1)

    def _retry_current(self) -> None:
        self.capture_canvas.clear()
        self.hash_value.setText("—")
        self.label_edit.setText(self.queue_state.tokens[self.queue_state.current_index])

    def _open_current(self) -> None:
        self.open_latest_for_label(self.queue_state.tokens[self.queue_state.current_index])

    def reject_current_sample(self) -> bool:
        digest = self.hash_value.text()
        if len(digest) != 64:
            self._refresh_diagnostics(tr(self.language, "studio.reject_missing"))
            return False
        rejected = set(self.queue_state.rejected_capture_hashes)
        rejected.add(digest)
        self._set_queue_state(rejected_capture_hashes=frozenset(rejected))
        variant = next((item for item in self.draft_catalog.variants if item.capture_sha256 == digest), None)
        if variant is not None:
            self.draft_catalog = self.draft_catalog.update_status(
                variant.variant_id, "rejected", self._now_utc()
            )
            self.draft_store.save(self.draft_catalog)
        self.capture_canvas.clear()
        self.hash_value.setText("—")
        self._refresh_diagnostics(tr(self.language, "studio.rejected").format(hash=digest[:12]))
        self._refresh_variants()
        return True

    def _required_variants_changed(self, value: int) -> None:
        self._set_queue_state(required_variants=value)

    def _apply_preset(self) -> None:
        preset = self.queue_preset.currentData()
        mapping = {"uk": UKRAINIAN_QUEUE, "ru": RUSSIAN_QUEUE, "en": ENGLISH_QUEUE}
        if preset in mapping:
            self._replace_queue(mapping[preset], tr(self.language, f"studio.queue.{preset}"))

    def _apply_custom_queue(self) -> None:
        tokens = tuple(unicodedata.normalize("NFC", token) for token in self.custom_queue.text().split())
        if not tokens:
            self._refresh_diagnostics(tr(self.language, "studio.custom_queue_empty"))
            return
        try:
            self._replace_queue(tokens, tr(self.language, "studio.queue.custom"))
        except ValueError as exc:
            self._refresh_diagnostics(str(exc))

    def _replace_queue(self, tokens: tuple[str, ...], name: str) -> None:
        self.queue_state = CaptureQueueState(
            queue_id=self.queue_state.queue_id,
            name=name,
            tokens=tokens,
            required_variants=self.required_variants.value(),
            rejected_capture_hashes=self.queue_state.rejected_capture_hashes,
        )
        self.queue_store.save(self.queue_state)
        self.label_edit.setText(tokens[0])
        self.capture_canvas.clear()
        self._refresh_collection()

    @staticmethod
    def _now_utc() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _sync_draft_catalog(self) -> None:
        known = {item.capture_sha256 for item in self.draft_catalog.variants}
        changed = False
        for record in self._records:
            if record.sha256 not in known:
                self.draft_catalog = self._catalog_with_record(self.draft_catalog, record)
                known.add(record.sha256)
                changed = True
        if changed:
            self.draft_store.save(self.draft_catalog)

    def _add_record_to_draft(self, record: CaptureRecord) -> None:
        self.draft_catalog = self._catalog_with_record(self.draft_catalog, record)
        self.draft_store.save(self.draft_catalog)

    def _catalog_with_record(self, catalog: DraftCatalog, record: CaptureRecord) -> DraftCatalog:
        sample = record.session.samples[0]
        metadata = record.session.extensions.get("cadpisun.studio", {})
        requested = str(metadata.get("variant_id", self._suggest_variant_id(sample.label))) if isinstance(metadata, dict) else self._suggest_variant_id(sample.label)
        existing_ids = {item.variant_id for item in catalog.variants}
        variant_id = requested
        suffix = 2
        while variant_id in existing_ids:
            variant_id = f"{requested}-{suffix}"
            suffix += 1
        context = str(metadata.get("context_tag", "isolated")) if isinstance(metadata, dict) else "isolated"
        if context not in {"isolated", "initial", "medial", "final"}:
            context = "isolated"
        variant = VariantDraft(
            variant_id=variant_id,
            sample_id=sample.sample_id,
            capture_sha256=record.sha256,
            label=sample.label,
            context_tag=context,
            history=(DraftEvent(
                revision=1,
                action="captured",
                occurred_at_utc=record.session.created_at_utc,
            ),),
        )
        return DraftCatalog(
            style_id=catalog.style_id,
            display_name=self.style_name.text().strip() or catalog.display_name,
            variants=(*catalog.variants, variant),
        )

    def _refresh_variants(self) -> None:
        label = self.label_edit.text().strip()
        selected_id = self.variant_list.currentItem().data(ROLE_TOKEN) if self.variant_list.currentItem() else None
        self.variant_list.clear()
        for variant in self.draft_catalog.visible_variants(label):
            try:
                record = next(item for item in self._records if item.sha256 == variant.capture_sha256)
            except StopIteration:
                continue
            marker = "★" if variant.preferred else ("✕" if variant.review_status == "rejected" else "")
            item = QListWidgetItem(self._thumbnail(record), f"{marker} {variant.variant_id}".strip())
            item.setData(ROLE_TOKEN, variant.variant_id)
            item.setToolTip(f"{variant.context_tag} · {variant.review_status} · {variant.capture_sha256[:12]}")
            self.variant_list.addItem(item)
            if variant.variant_id == selected_id:
                self.variant_list.setCurrentItem(item)

    def _thumbnail(self, record: CaptureRecord) -> QIcon:
        sample = record.session.samples[0]
        pixmap = QPixmap(120, 80)
        pixmap.fill(QColor("#f8f8f6"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#20242a"), 2.0))
        sx = 110 / sample.coordinate_reference.width
        sy = 70 / sample.coordinate_reference.height
        for stroke in sample.strokes:
            points = [QPointF(5 + point.x * sx, 5 + point.y * sy) for point in stroke.points]
            for first, second in zip(points, points[1:], strict=False):
                painter.drawLine(first, second)
        painter.end()
        return QIcon(pixmap)

    def _selected_variant(self) -> VariantDraft | None:
        item = self.variant_list.currentItem()
        if item is None:
            return None
        variant_id = str(item.data(ROLE_TOKEN))
        return next((variant for variant in self.draft_catalog.variants if variant.variant_id == variant_id), None)

    def _open_variant_item(self, item: QListWidgetItem) -> None:
        variant_id = str(item.data(ROLE_TOKEN))
        variant = next(value for value in self.draft_catalog.variants if value.variant_id == variant_id)
        record = next(value for value in self._records if value.sha256 == variant.capture_sha256)
        self.open_record(record)

    def _set_selected_preferred(self) -> None:
        variant = self._selected_variant()
        if variant is None:
            return
        self.draft_catalog = self.draft_catalog.set_preferred(variant.variant_id, self._now_utc())
        self.draft_store.save(self.draft_catalog)
        self._refresh_variants()

    def _delete_selected_variant(self) -> None:
        variant = self._selected_variant()
        if variant is None:
            return
        self.draft_catalog = self.draft_catalog.delete_from_draft(variant.variant_id, self._now_utc())
        self.draft_store.save(self.draft_catalog)
        self._refresh_variants()

    def _suggest_variant_id(self, label: str) -> str:
        if not label:
            return ""
        code = "-".join(f"u-{ord(char):04x}" for char in label)
        count = sum(record.session.samples[0].label == label for record in self._records) + 1
        return f"{code}-v{count}"

