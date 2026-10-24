"""Dedicated notebook-photo import and inspection workspace."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
import math
import os
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, QSignalBlocker, QThreadPool, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPen, QPixmap, QResizeEvent, QTransform
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QSpinBox,
    QSplitter,
)

from handwriting_plotter.adapters.images.qt import QtImageDecoder
from handwriting_plotter.adapters.images.opencv import (
    OpenCvPageCorrector,
    OpenCvInkSeparator,
    OpenCvLineSegmenter,
    OpenCvRulingGeometryEstimator,
    OpenCvRulingClassifier,
    opencv_available,
)
from handwriting_plotter.learning import (
    HtrProcessClient,
    HtrResultRepository,
    HtrRunRecord,
    HtrRuntime,
    PageCorners,
    PhotoRecord,
    PhotoRepository,
    PixelPoint,
    RulingEstimate,
    ReadingOrderEntry,
    ReviewConflict,
    TranscriptionReviewRecord,
    TranscriptionReviewRepository,
    calibration_from_ruling_pitch,
    make_htr_request,
    manual_ruling_estimate,
    manual_ruling_geometry,
    persist_correction,
    persist_ink_mask,
    persist_line_regions,
    persist_physical_scale_calibration,
    persist_ruling_estimate,
    select_ink_mask_variant,
)
from handwriting_plotter.version import __version__

from .i18n import Language, tr
from .workers import HtrRecognitionWorker

PHOTO_FILE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"


@dataclass(frozen=True, slots=True)
class _ReviewLine:
    """Current immutable crop plus optional source HTR result for one line."""

    line_id: str
    crop_sha256: str
    png: bytes
    original_prediction: str | None
    htr_run_sha256: str | None
    provider_summary: str
    confidence_summary: str


class PhotoPreviewView(QGraphicsView):
    """Small bounded image viewer with deterministic fit and 1:1 modes."""

    MIN_ZOOM = 0.125
    MAX_ZOOM = 8.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("photo-preview-view")
        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem()
        self._scene.addItem(self._item)
        self._corner_handles: list[QGraphicsEllipseItem] = []
        self._ruling_overlay: list[QGraphicsLineItem] = []
        self.setScene(self._scene)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._zoom = 1.0
        self._fit = True

    @property
    def zoom_factor(self) -> float:
        return self._zoom

    @property
    def has_image(self) -> bool:
        return not self._item.pixmap().isNull()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._item.setPixmap(pixmap)
        self._scene.setSceneRect(self._item.boundingRect())
        self.fit_image()

    def clear_corners(self) -> None:
        for handle in self._corner_handles:
            self._scene.removeItem(handle)
        self._corner_handles.clear()

    def clear_ruling_overlay(self) -> None:
        for line in self._ruling_overlay:
            self._scene.removeItem(line)
        self._ruling_overlay.clear()

    def set_ruling_overlay(self, estimate: RulingEstimate) -> None:
        self.clear_ruling_overlay()
        bounds = self._item.boundingRect()
        if bounds.isEmpty():
            return
        diagonal = math.hypot(bounds.width(), bounds.height())
        pen = QPen(QColor("#e91e63"), 1.6)
        pen.setCosmetic(True)

        def add_family(pitch: float | None, origin: float | None, angle_deg: float | None, *, vertical: bool) -> None:
            if pitch is None or origin is None or angle_deg is None:
                return
            radians = math.radians(angle_deg)
            normal = (math.sin(radians), -math.cos(radians)) if vertical else (-math.sin(radians), math.cos(radians))
            direction = (math.cos(radians), math.sin(radians))
            start = math.floor((-diagonal - origin) / pitch)
            end = math.ceil((diagonal - origin) / pitch)
            for index in range(max(start, -128), min(end, 128) + 1):
                coordinate = origin + index * pitch
                point_x, point_y = normal[0] * coordinate, normal[1] * coordinate
                line = QGraphicsLineItem(
                    point_x - direction[0] * diagonal,
                    point_y - direction[1] * diagonal,
                    point_x + direction[0] * diagonal,
                    point_y + direction[1] * diagonal,
                )
                line.setPen(pen)
                line.setZValue(5)
                self._scene.addItem(line)
                self._ruling_overlay.append(line)

        add_family(
            estimate.ruling_pitch_px or estimate.cell_pitch_y_px,
            estimate.origin_y_px,
            estimate.horizontal_angle_deg,
            vertical=False,
        )
        add_family(
            estimate.cell_pitch_x_px,
            estimate.origin_x_px,
            estimate.vertical_angle_deg,
            vertical=True,
        )

    def set_corners(self, corners: PageCorners) -> None:
        self.clear_corners()
        colors = ("#ff5252", "#ffd740", "#69f0ae", "#40c4ff")
        for point, color in zip(corners.points, colors, strict=True):
            handle = QGraphicsEllipseItem(-7, -7, 14, 14)
            handle.setBrush(QBrush(QColor(color)))
            handle.setPen(QPen(QColor("#202124"), 2))
            handle.setPos(point.x, point.y)
            handle.setZValue(10)
            handle.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable, True)
            handle.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
            handle.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            self._scene.addItem(handle)
            self._corner_handles.append(handle)

    def corners(self, frame_id: str) -> PageCorners:
        if len(self._corner_handles) != 4:
            raise ValueError("PAGE_CORNERS_NOT_SET")
        bounds = self._item.boundingRect()
        points = tuple(
            PixelPoint(
                x=max(0.0, min(bounds.width() - 1, handle.pos().x())),
                y=max(0.0, min(bounds.height() - 1, handle.pos().y())),
            )
            for handle in self._corner_handles
        )
        return PageCorners(
            frame_id=frame_id,
            top_left=points[0],
            top_right=points[1],
            bottom_right=points[2],
            bottom_left=points[3],
        )

    def set_zoom_factor(self, factor: float) -> None:
        self._fit = False
        self._zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, factor))
        self.resetTransform()
        self.scale(self._zoom, self._zoom)

    def fit_image(self) -> None:
        self._fit = True
        self._zoom = 1.0
        self.resetTransform()
        if self.has_image:
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)

    def actual_size(self) -> None:
        self.set_zoom_factor(1.0)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if self._fit:
            self.fit_image()


class PhotoImportWorkspace(QWidget):
    """Import immutable source photos and compare source/correction previews."""

    def __init__(
        self,
        root: Path,
        *,
        language: Language = "en",
        htr_worker_script: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("photo-import-workspace")
        self.language = language
        self.repository = PhotoRepository(root)
        self.htr_results = HtrResultRepository(root)
        self.transcription_reviews = TranscriptionReviewRepository(root)
        self.current_record: PhotoRecord | None = None
        self._source_pixmap = QPixmap()
        self._corrected_pixmap = QPixmap()
        self._display_rotation = 0
        self._proposal_method = "manual-four-corner/1"
        self._proposal_confidence = None
        self._status_key = "photo.status.empty"
        self._status_values: dict[str, object] = {}
        self._htr_worker: HtrRecognitionWorker | None = None
        self._review_lines: list[_ReviewLine] = []
        self._review_current_index: int | None = None
        self._review_current_record: TranscriptionReviewRecord | None = None
        self._review_order_sha256: str | None = None
        self._review_source_manifest_sha256: str | None = None
        self._review_dirty = False
        self._review_selection_guard = False
        self._thread_pool = QThreadPool.globalInstance()
        self._htr_worker_script = htr_worker_script
        self._build_ui()
        self._set_controls_enabled(False)
        self._connect()
        self.set_language(language)
        self._restore_latest()

    @property
    def display_rotation(self) -> int:
        return self._display_rotation

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        heading_column = QVBoxLayout()
        self.title_label = QLabel()
        self.title_label.setObjectName("photo-import-title")
        title_font = self.title_label.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.subtitle_label = QLabel()
        self.subtitle_label.setWordWrap(True)
        heading_column.addWidget(self.title_label)
        heading_column.addWidget(self.subtitle_label)
        header.addLayout(heading_column, 1)
        self.choose_button = QPushButton()
        self.choose_button.setObjectName("photo-choose-button")
        self.choose_button.setMinimumHeight(36)
        header.addWidget(self.choose_button)
        layout.addLayout(header)

        tools = QHBoxLayout()
        self.zoom_out_button = QPushButton("−")
        self.actual_size_button = QPushButton("1:1")
        self.fit_button = QPushButton()
        self.zoom_in_button = QPushButton("+")
        self.rotate_left_button = QPushButton("↶ 90°")
        self.rotate_right_button = QPushButton("↷ 90°")
        self.reset_button = QPushButton()
        for button in (
            self.zoom_out_button,
            self.actual_size_button,
            self.fit_button,
            self.zoom_in_button,
            self.rotate_left_button,
            self.rotate_right_button,
            self.reset_button,
        ):
            button.setEnabled(False)
            tools.addWidget(button)
        tools.addStretch(1)
        layout.addLayout(tools)

        correction_tools = QHBoxLayout()
        self.detect_page_button = QPushButton()
        self.manual_corners_button = QPushButton()
        self.apply_correction_button = QPushButton()
        self.apply_correction_button.setEnabled(False)
        self.deskew_check = QCheckBox()
        self.deskew_spin = QDoubleSpinBox()
        self.deskew_spin.setRange(-5.0, 5.0)
        self.deskew_spin.setDecimals(2)
        self.deskew_spin.setSingleStep(0.25)
        self.deskew_spin.setSuffix("°")
        self.deskew_spin.setEnabled(False)
        correction_tools.addWidget(self.detect_page_button)
        correction_tools.addWidget(self.manual_corners_button)
        correction_tools.addWidget(self.apply_correction_button)
        correction_tools.addSpacing(12)
        correction_tools.addWidget(self.deskew_check)
        correction_tools.addWidget(self.deskew_spin)
        correction_tools.addStretch(1)
        layout.addLayout(correction_tools)

        ruling_tools = QHBoxLayout()
        self.analyze_paper_button = QPushButton()
        self.paper_classification_label = QLabel()
        self.paper_classification_combo = QComboBox()
        self.paper_classification_combo.setObjectName("photo-paper-classification")
        for classification in ("unknown", "blank", "squared", "ruled", "mixed"):
            self.paper_classification_combo.addItem("", classification)
        self.override_ruling_button = QPushButton()
        self.paper_summary_label = QLabel()
        self.paper_summary_label.setObjectName("photo-paper-summary")
        self.analyze_paper_button.setEnabled(False)
        self.paper_classification_combo.setEnabled(False)
        self.override_ruling_button.setEnabled(False)
        ruling_tools.addWidget(self.analyze_paper_button)
        ruling_tools.addSpacing(12)
        ruling_tools.addWidget(self.paper_classification_label)
        ruling_tools.addWidget(self.paper_classification_combo)
        ruling_tools.addWidget(self.override_ruling_button)
        ruling_tools.addWidget(self.paper_summary_label, 1)
        layout.addLayout(ruling_tools)

        geometry_tools = QHBoxLayout()
        self.detect_geometry_button = QPushButton()
        self.show_ruling_overlay_check = QCheckBox()
        self.pitch_x_label = QLabel()
        self.pitch_x_spin = QDoubleSpinBox()
        self.pitch_y_label = QLabel()
        self.pitch_y_spin = QDoubleSpinBox()
        self.origin_x_label = QLabel()
        self.origin_x_spin = QDoubleSpinBox()
        self.origin_y_label = QLabel()
        self.origin_y_spin = QDoubleSpinBox()
        self.ruling_angle_label = QLabel()
        self.ruling_angle_spin = QDoubleSpinBox()
        self.apply_geometry_button = QPushButton()
        self.geometry_summary_label = QLabel()
        self.geometry_summary_label.setObjectName("photo-geometry-summary")
        for spin in (self.pitch_x_spin, self.pitch_y_spin, self.origin_x_spin, self.origin_y_spin):
            spin.setRange(-20_000.0, 20_000.0)
            spin.setDecimals(2)
            spin.setSingleStep(1.0)
            spin.setSuffix(" px")
        self.pitch_x_spin.setMinimum(0.01)
        self.pitch_y_spin.setMinimum(0.01)
        self.ruling_angle_spin.setRange(-45.0, 45.0)
        self.ruling_angle_spin.setDecimals(2)
        self.ruling_angle_spin.setSuffix("°")
        self.detect_geometry_button.setEnabled(False)
        self.show_ruling_overlay_check.setEnabled(False)
        self.apply_geometry_button.setEnabled(False)
        for widget in (
            self.detect_geometry_button,
            self.show_ruling_overlay_check,
            self.pitch_x_label,
            self.pitch_x_spin,
            self.pitch_y_label,
            self.pitch_y_spin,
            self.origin_x_label,
            self.origin_x_spin,
            self.origin_y_label,
            self.origin_y_spin,
            self.ruling_angle_label,
            self.ruling_angle_spin,
            self.apply_geometry_button,
        ):
            geometry_tools.addWidget(widget)
        geometry_tools.addWidget(self.geometry_summary_label, 1)
        layout.addLayout(geometry_tools)

        calibration_tools = QHBoxLayout()
        self.scale_reference_label = QLabel()
        self.scale_reference_spin = QDoubleSpinBox()
        self.scale_reference_spin.setRange(0.1, 100.0)
        self.scale_reference_spin.setDecimals(2)
        self.scale_reference_spin.setSingleStep(0.5)
        self.scale_reference_spin.setSuffix(" mm")
        self.scale_reference_spin.setValue(5.0)
        self.apply_scale_button = QPushButton()
        self.apply_5mm_preset_button = QPushButton()
        self.scale_summary_label = QLabel()
        self.scale_summary_label.setObjectName("photo-scale-summary")
        self.scale_reference_spin.setEnabled(False)
        self.apply_scale_button.setEnabled(False)
        self.apply_5mm_preset_button.setEnabled(False)
        calibration_tools.addWidget(self.scale_reference_label)
        calibration_tools.addWidget(self.scale_reference_spin)
        calibration_tools.addWidget(self.apply_scale_button)
        calibration_tools.addWidget(self.apply_5mm_preset_button)
        calibration_tools.addWidget(self.scale_summary_label, 1)
        layout.addLayout(calibration_tools)

        mask_tools = QHBoxLayout()
        self.separate_ink_button = QPushButton()
        self.use_raw_mask_button = QPushButton()
        self.mask_summary_label = QLabel()
        self.mask_summary_label.setObjectName("photo-mask-summary")
        self.separate_ink_button.setEnabled(False)
        self.use_raw_mask_button.setEnabled(False)
        mask_tools.addWidget(self.separate_ink_button)
        mask_tools.addWidget(self.use_raw_mask_button)
        mask_tools.addWidget(self.mask_summary_label, 1)
        layout.addLayout(mask_tools)

        region_tools = QHBoxLayout()
        self.detect_lines_button = QPushButton()
        self.lines_summary_label = QLabel()
        self.lines_summary_label.setObjectName("photo-lines-summary")
        self.detect_lines_button.setEnabled(False)
        region_tools.addWidget(self.detect_lines_button)
        region_tools.addWidget(self.lines_summary_label, 1)
        layout.addLayout(region_tools)

        self.htr_group = QGroupBox()
        self.htr_group.setObjectName("photo-htr-group")
        htr_layout = QVBoxLayout(self.htr_group)
        htr_form = QFormLayout()
        self.htr_provider_combo = QComboBox()
        self.htr_provider_combo.setObjectName("photo-htr-provider")
        self.htr_provider_combo.addItem("CRNN — fast CPU", "crnn-rukopys")
        self.htr_provider_combo.addItem("TrOCR — quality CPU", "trocr-rukopys")
        self.htr_python_path = QLineEdit(os.environ.get("HP_HTR_PYTHON", ""))
        self.htr_python_path.setObjectName("photo-htr-python")
        self.htr_python_path.setPlaceholderText(tr(self.language, "photo.htr.python_hint"))
        self.htr_model_root = QLineEdit(os.environ.get("HP_HTR_MODEL_ROOT", ""))
        self.htr_model_root.setObjectName("photo-htr-model-root")
        self.htr_model_root.setPlaceholderText(tr(self.language, "photo.htr.model_root_hint"))
        self.htr_timeout = QSpinBox()
        self.htr_timeout.setObjectName("photo-htr-timeout")
        self.htr_timeout.setRange(1, 900)
        self.htr_timeout.setSuffix(" s")
        self.htr_timeout.setValue(120)
        self._htr_labels: dict[str, QLabel] = {}
        for key, widget in (
            ("photo.htr.provider", self.htr_provider_combo),
            ("photo.htr.python", self.htr_python_path),
            ("photo.htr.model_root", self.htr_model_root),
            ("photo.htr.timeout", self.htr_timeout),
        ):
            label = QLabel()
            self._htr_labels[key] = label
            htr_form.addRow(label, widget)
        htr_layout.addLayout(htr_form)
        htr_actions = QHBoxLayout()
        self.htr_run_button = QPushButton()
        self.htr_run_button.setObjectName("photo-htr-run")
        self.htr_cancel_button = QPushButton()
        self.htr_cancel_button.setObjectName("photo-htr-cancel")
        self.htr_cancel_button.setEnabled(False)
        self.htr_progress = QProgressBar()
        self.htr_progress.setObjectName("photo-htr-progress")
        self.htr_progress.setTextVisible(True)
        htr_actions.addWidget(self.htr_run_button)
        htr_actions.addWidget(self.htr_cancel_button)
        htr_actions.addWidget(self.htr_progress, 1)
        htr_layout.addLayout(htr_actions)
        self.htr_results_view = QPlainTextEdit()
        self.htr_results_view.setObjectName("photo-htr-results")
        self.htr_results_view.setReadOnly(True)
        self.htr_results_view.setMaximumHeight(150)
        htr_layout.addWidget(self.htr_results_view)
        layout.addWidget(self.htr_group)

        # Review is intentionally a compact splitter rather than another page in
        # the workspace stack.  It can shrink on laptop-sized windows and never
        # contributes a hidden workflow minimum to the document workspace.
        self.review_group = QGroupBox("Review transcription")
        self.review_group.setObjectName("photo-transcription-review")
        self.review_group.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.review_group.setMinimumSize(0, 0)
        self.review_group.setMaximumHeight(390)
        review_layout = QVBoxLayout(self.review_group)
        self.review_summary_label = QLabel()
        self.review_summary_label.setObjectName("photo-review-summary")
        self.review_summary_label.setWordWrap(True)
        review_layout.addWidget(self.review_summary_label)
        self.review_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.review_splitter.setObjectName("photo-review-splitter")
        self.review_splitter.setChildrenCollapsible(False)
        self.review_line_list = QListWidget()
        self.review_line_list.setObjectName("photo-review-lines")
        self.review_line_list.setMinimumWidth(120)
        self.review_line_list.setMaximumWidth(240)
        self.review_splitter.addWidget(self.review_line_list)
        review_detail = QWidget()
        review_detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        detail_layout = QVBoxLayout(review_detail)
        detail_layout.setContentsMargins(4, 0, 0, 0)
        self.review_crop_label = QLabel()
        self.review_crop_label.setObjectName("photo-review-crop")
        self.review_crop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.review_crop_label.setMinimumHeight(74)
        self.review_crop_label.setMaximumHeight(112)
        self.review_crop_label.setStyleSheet("background: #303030; border: 1px solid #606060;")
        detail_layout.addWidget(self.review_crop_label)
        self.review_prediction_label = QLabel()
        self.review_prediction_label.setObjectName("photo-review-original-prediction")
        self.review_prediction_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.review_prediction_label.setWordWrap(True)
        detail_layout.addWidget(self.review_prediction_label)
        self.review_provenance_label = QLabel()
        self.review_provenance_label.setObjectName("photo-review-provenance")
        self.review_provenance_label.setWordWrap(True)
        detail_layout.addWidget(self.review_provenance_label)
        self.review_editor = QPlainTextEdit()
        self.review_editor.setObjectName("photo-review-editor")
        self.review_editor.setPlaceholderText("Enter a transcription when no prediction is available.")
        self.review_editor.setMaximumBlockCount(128)
        self.review_editor.setMinimumHeight(62)
        detail_layout.addWidget(self.review_editor, 1)
        review_actions = QHBoxLayout()
        self.review_status_combo = QComboBox()
        self.review_status_combo.setObjectName("photo-review-status")
        for status in ("unreviewed", "edited", "accepted", "unresolved"):
            self.review_status_combo.addItem(status, status)
        self.review_previous_button = QPushButton("←")
        self.review_next_button = QPushButton("→")
        self.review_move_up_button = QPushButton("Move up")
        self.review_move_down_button = QPushButton("Move down")
        self.review_save_button = QPushButton("Save revision")
        self.review_save_button.setObjectName("photo-review-save")
        review_actions.addWidget(self.review_status_combo)
        review_actions.addWidget(self.review_previous_button)
        review_actions.addWidget(self.review_next_button)
        review_actions.addWidget(self.review_move_up_button)
        review_actions.addWidget(self.review_move_down_button)
        review_actions.addWidget(self.review_save_button)
        detail_layout.addLayout(review_actions)
        self.review_splitter.addWidget(review_detail)
        self.review_splitter.setStretchFactor(0, 0)
        self.review_splitter.setStretchFactor(1, 1)
        self.review_splitter.setSizes([180, 640])
        review_layout.addWidget(self.review_splitter, 1)
        layout.addWidget(self.review_group)
        self.review_group.setVisible(False)

        comparison = QGridLayout()
        comparison.setContentsMargins(0, 0, 0, 0)
        comparison.setSpacing(10)
        self.original_group = QGroupBox()
        original_layout = QVBoxLayout(self.original_group)
        self.original_view = PhotoPreviewView()
        self.original_view.setObjectName("photo-original-view")
        original_layout.addWidget(self.original_view)
        self.corrected_group = QGroupBox()
        corrected_layout = QVBoxLayout(self.corrected_group)
        self.correction_notice = QLabel()
        self.correction_notice.setObjectName("photo-correction-notice")
        self.correction_notice.setWordWrap(True)
        self.corrected_view = PhotoPreviewView()
        self.corrected_view.setObjectName("photo-corrected-view")
        corrected_layout.addWidget(self.correction_notice)
        corrected_layout.addWidget(self.corrected_view, 1)
        comparison.addWidget(self.original_group, 0, 0)
        comparison.addWidget(self.corrected_group, 0, 1)
        comparison.setColumnStretch(0, 1)
        comparison.setColumnStretch(1, 1)
        layout.addLayout(comparison, 1)

        self.diagnostics_group = QGroupBox()
        diagnostics_layout = QVBoxLayout(self.diagnostics_group)
        self.status_label = QLabel()
        self.status_label.setObjectName("photo-import-status")
        self.status_label.setWordWrap(True)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setObjectName("photo-import-diagnostics")
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setMaximumHeight(145)
        diagnostics_layout.addWidget(self.status_label)
        diagnostics_layout.addWidget(self.diagnostics)
        layout.addWidget(self.diagnostics_group)

    def _connect(self) -> None:
        self.choose_button.clicked.connect(self.choose_photo)
        self.zoom_out_button.clicked.connect(lambda: self._set_zoom(self.corrected_view.zoom_factor / 1.25))
        self.zoom_in_button.clicked.connect(lambda: self._set_zoom(self.corrected_view.zoom_factor * 1.25))
        self.actual_size_button.clicked.connect(self._actual_size)
        self.fit_button.clicked.connect(self._fit_views)
        self.rotate_left_button.clicked.connect(lambda: self.rotate_preview(-90))
        self.rotate_right_button.clicked.connect(lambda: self.rotate_preview(90))
        self.reset_button.clicked.connect(self.reset_view)
        self.detect_page_button.clicked.connect(self.detect_page)
        self.manual_corners_button.clicked.connect(self.enable_manual_corners)
        self.apply_correction_button.clicked.connect(self.apply_correction)
        self.analyze_paper_button.clicked.connect(self.analyze_paper)
        self.override_ruling_button.clicked.connect(self.apply_ruling_override)
        self.detect_geometry_button.clicked.connect(self.detect_ruling_geometry)
        self.apply_geometry_button.clicked.connect(self.apply_ruling_geometry)
        self.show_ruling_overlay_check.toggled.connect(self._refresh_ruling_overlay)
        self.apply_scale_button.clicked.connect(self.apply_user_scale)
        self.apply_5mm_preset_button.clicked.connect(self.apply_5mm_preset)
        self.separate_ink_button.clicked.connect(self.separate_ink)
        self.use_raw_mask_button.clicked.connect(self.use_raw_mask)
        self.detect_lines_button.clicked.connect(self.detect_lines)
        self.htr_run_button.clicked.connect(self.run_htr)
        self.htr_cancel_button.clicked.connect(self.cancel_htr)
        self.review_line_list.currentRowChanged.connect(self._review_select_row)
        self.review_editor.textChanged.connect(self._review_text_changed)
        self.review_status_combo.currentIndexChanged.connect(self._review_status_changed)
        self.review_previous_button.clicked.connect(lambda: self._review_navigate(-1))
        self.review_next_button.clicked.connect(lambda: self._review_navigate(1))
        self.review_move_up_button.clicked.connect(lambda: self._move_review_line(-1))
        self.review_move_down_button.clicked.connect(lambda: self._move_review_line(1))
        self.review_save_button.clicked.connect(self.save_review_revision)
        self.deskew_check.toggled.connect(self.deskew_spin.setEnabled)

    def choose_photo(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            tr(self.language, "photo.dialog.title"),
            "",
            PHOTO_FILE_FILTER,
        )
        if filename:
            self.import_path(Path(filename))

    def import_path(self, path: Path) -> PhotoRecord | None:
        if self._review_dirty:
            self._set_status("photo.htr.failed", error="SAVE_REVIEW_BEFORE_CHANGING_PHOTO")
            return None
        try:
            record = self.repository.import_file(
                path,
                QtImageDecoder(),
                imported_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                application_version=__version__,
                source_kind="image_file",
                rights_status="private_user_material",
            )
            image = self._read_preview(record)
        except (OSError, ValueError) as exc:
            self._set_status("photo.status.failed", error=str(exc))
            return None

        self._show_record(record, image)
        self._set_status("photo.status.imported", name=record.photo.metadata.original_filename)
        return record

    def _restore_latest(self) -> None:
        try:
            records = self.repository.list_records()
            if not records:
                return
            record = max(
                records,
                key=lambda item: (
                    item.photo.metadata.imported_at_utc,
                    len(item.photo.transforms),
                    {"not_evaluated": 0, "proposed": 1, "confirmed": 2, "overridden": 3}[item.photo.ruling.status],
                    item.path.stat().st_mtime_ns,
                ),
            )
            self._show_record(record, self._read_preview(record))
            self._set_status("photo.status.restored", name=record.photo.metadata.original_filename)
        except (OSError, ValueError) as exc:
            self._set_status("photo.status.restore_failed", error=str(exc))

    def _read_preview(self, record: PhotoRecord) -> QImage:
        image = QImage.fromData(self.repository.read_original(record.photo))
        if image.isNull():
            raise ValueError("PHOTO_PREVIEW_DECODE_FAILED")
        return self._apply_orientation(image, record.photo.metadata.embedded_orientation)

    def _show_record(self, record: PhotoRecord, image: QImage) -> None:
        self.current_record = record
        self._source_pixmap = QPixmap.fromImage(image)
        self._corrected_pixmap = QPixmap()
        self.original_view.clear_corners()
        self._display_rotation = 0
        self.original_view.set_pixmap(self._source_pixmap)
        self._restore_correction_preview(record)
        self._refresh_corrected_preview()
        self._set_controls_enabled(True)
        self.apply_correction_button.setEnabled(False)
        self._refresh_ruling_controls()
        self._refresh_geometry_controls()
        self._refresh_calibration_controls()
        self._refresh_mask_controls()
        self._refresh_line_controls()
        self._refresh_htr_controls()
        self._restore_htr_results(record)
        self._refresh_transcription_review()
        self._refresh_ruling_overlay()
        self._refresh_diagnostics()

    def rotate_preview(self, degrees: int) -> None:
        if self.current_record is None:
            return
        self._display_rotation = (self._display_rotation + degrees) % 360
        self._refresh_corrected_preview()
        self._refresh_diagnostics()

    def _ruling_input(self) -> tuple[bytes, str]:
        if self.current_record is None:
            raise ValueError("PHOTO_NOT_SELECTED")
        photo = self.current_record.photo
        if photo.transforms:
            latest = photo.transforms[-1]
            return (
                self.repository.derivative_path(latest.output_sha256, "png").read_bytes(),
                latest.output_frame_id,
            )
        return self.repository.read_original(photo), photo.frames[0].frame_id

    def analyze_paper(self) -> None:
        if self.current_record is None:
            return
        try:
            content, frame_id = self._ruling_input()
            estimate = OpenCvRulingClassifier().classify(content, frame_id=frame_id)
            self.current_record = persist_ruling_estimate(
                self.repository, self.current_record, estimate
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self._set_status("photo.ruling.failed", error=str(exc))
            return
        confidence = f"{estimate.confidence.value:.0%}" if estimate.confidence else "—"
        self._refresh_ruling_controls()
        self._refresh_geometry_controls()
        self._refresh_calibration_controls()
        self._refresh_mask_controls()
        self._refresh_line_controls()
        self._refresh_ruling_overlay()
        self._refresh_diagnostics()
        self._set_status(
            "photo.ruling.analysis_complete",
            classification=self._classification_label(estimate.classification),
            confidence=confidence,
        )

    def apply_ruling_override(self) -> None:
        if self.current_record is None:
            return
        try:
            _, frame_id = self._ruling_input()
            classification = self.paper_classification_combo.currentData()
            if classification not in {"unknown", "blank", "squared", "ruled", "mixed"}:
                raise ValueError("INVALID_RULING_CLASSIFICATION")
            estimate = manual_ruling_estimate(classification, frame_id=frame_id)
            self.current_record = persist_ruling_estimate(
                self.repository, self.current_record, estimate
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self._set_status("photo.ruling.failed", error=str(exc))
            return
        self._refresh_ruling_controls()
        self._refresh_geometry_controls()
        self._refresh_calibration_controls()
        self._refresh_mask_controls()
        self._refresh_line_controls()
        self._refresh_ruling_overlay()
        self._refresh_diagnostics()
        self._set_status(
            "photo.ruling.override_complete",
            classification=self._classification_label(estimate.classification),
        )

    def detect_ruling_geometry(self) -> None:
        if self.current_record is None:
            return
        try:
            classification = self.current_record.photo.ruling.classification
            content, frame_id = self._ruling_input()
            estimate = OpenCvRulingGeometryEstimator().estimate(
                content, frame_id=frame_id, classification=classification
            )
            self.current_record = persist_ruling_estimate(
                self.repository, self.current_record, estimate
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self._set_status("photo.geometry.failed", error=str(exc))
            return
        self._refresh_ruling_controls()
        self._refresh_geometry_controls()
        self._refresh_calibration_controls()
        self._refresh_mask_controls()
        self._refresh_line_controls()
        self._refresh_ruling_overlay()
        self._refresh_diagnostics()
        confidence = f"{estimate.confidence.value:.0%}" if estimate.confidence else "—"
        self._set_status("photo.geometry.complete", confidence=confidence)

    def apply_ruling_geometry(self) -> None:
        if self.current_record is None:
            return
        try:
            classification = self.current_record.photo.ruling.classification
            _, frame_id = self._ruling_input()
            if classification == "squared":
                estimate = manual_ruling_geometry(
                    "squared",
                    frame_id=frame_id,
                    origin_x_px=self.origin_x_spin.value(),
                    origin_y_px=self.origin_y_spin.value(),
                    cell_pitch_x_px=self.pitch_x_spin.value(),
                    cell_pitch_y_px=self.pitch_y_spin.value(),
                    horizontal_angle_deg=self.ruling_angle_spin.value(),
                )
            elif classification == "ruled":
                estimate = manual_ruling_geometry(
                    "ruled",
                    frame_id=frame_id,
                    origin_y_px=self.origin_y_spin.value(),
                    ruling_pitch_px=self.pitch_y_spin.value(),
                    horizontal_angle_deg=self.ruling_angle_spin.value(),
                )
            else:
                raise ValueError("RULING_GEOMETRY_NOT_APPLICABLE")
            self.current_record = persist_ruling_estimate(
                self.repository, self.current_record, estimate
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self._set_status("photo.geometry.failed", error=str(exc))
            return
        self._refresh_ruling_controls()
        self._refresh_geometry_controls()
        self._refresh_calibration_controls()
        self._refresh_mask_controls()
        self._refresh_line_controls()
        self._refresh_ruling_overlay()
        self._refresh_diagnostics()
        self._set_status("photo.geometry.override_complete")

    def apply_user_scale(self) -> None:
        self._apply_physical_scale("user_entered")

    def apply_5mm_preset(self) -> None:
        self.scale_reference_spin.setValue(5.0)
        self._apply_physical_scale("notebook_cell_preset")

    def _apply_physical_scale(
        self, source: Literal["user_entered", "notebook_cell_preset"]
    ) -> None:
        if self.current_record is None:
            return
        try:
            calibration = calibration_from_ruling_pitch(
                self.current_record.photo.ruling,
                pitch_mm=self.scale_reference_spin.value(),
                source=source,
            )
            self.current_record = persist_physical_scale_calibration(
                self.repository, self.current_record, calibration
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self._set_status("photo.scale.failed", error=str(exc))
            return
        self._refresh_calibration_controls()
        self._refresh_diagnostics()
        self._set_status(
            "photo.scale.complete",
            source=tr(self.language, f"photo.scale.source.{calibration.source}"),
        )

    def separate_ink(self) -> None:
        if self.current_record is None:
            return
        try:
            content, frame_id = self._ruling_input()
            raster = OpenCvInkSeparator().separate(
                content, frame_id=frame_id, ruling=self.current_record.photo.ruling
            )
            self.current_record = persist_ink_mask(self.repository, self.current_record, raster)
        except (OSError, RuntimeError, ValueError) as exc:
            self._set_status("photo.mask.failed", error=str(exc))
            return
        self._refresh_mask_controls()
        self._refresh_line_controls()
        self._refresh_htr_controls()
        self._refresh_diagnostics()
        self._set_status("photo.mask.complete")

    def use_raw_mask(self) -> None:
        if self.current_record is None:
            return
        try:
            self.current_record = select_ink_mask_variant(
                self.repository, self.current_record, "raw"
            )
        except (OSError, ValueError) as exc:
            self._set_status("photo.mask.failed", error=str(exc))
            return
        self._refresh_mask_controls()
        self._refresh_line_controls()
        self._refresh_diagnostics()
        self._set_status("photo.mask.raw_selected")

    def detect_lines(self) -> None:
        if self.current_record is None or self.current_record.photo.ink_mask is None:
            return
        try:
            mask = self.current_record.photo.ink_mask
            relative = (
                mask.raw_relative_path if mask.selected_variant == "raw"
                else mask.cleaned_relative_path
            )
            regions = OpenCvLineSegmenter().segment(
                (self.repository.root / relative).read_bytes(), frame_id=mask.frame_id
            )
            self.current_record = persist_line_regions(self.repository, self.current_record, regions)
        except (OSError, RuntimeError, ValueError) as exc:
            self._set_status("photo.lines.failed", error=str(exc))
            return
        self._refresh_line_controls()
        self._refresh_htr_controls()
        self._refresh_diagnostics()
        self._set_status("photo.lines.complete", count=len(regions))

    @staticmethod
    def _png_bytes(image: QImage) -> bytes:
        payload = QByteArray()
        buffer = QBuffer(payload)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
            raise ValueError("HTR_CROP_ENCODE_FAILED")
        return bytes(payload)

    def _htr_crops(self) -> tuple[str, tuple[tuple[str, str, bytes], ...]]:
        if self.current_record is None:
            raise ValueError("PHOTO_NOT_SELECTED")
        content, frame_id = self._ruling_input()
        image = QImage.fromData(content)
        if image.isNull():
            raise ValueError("HTR_SOURCE_FRAME_DECODE_FAILED")
        lines = tuple(
            region for region in self.current_record.photo.regions
            if region.kind == "line" and region.frame_id == frame_id
        )
        if not lines:
            raise ValueError("HTR_REQUIRES_LINE_REGIONS")
        crops: list[tuple[str, str, bytes]] = []
        for region in lines:
            left = max(0, int(math.floor(min(point.x for point in region.polygon))))
            top = max(0, int(math.floor(min(point.y for point in region.polygon))))
            right = min(image.width(), int(math.ceil(max(point.x for point in region.polygon))))
            bottom = min(image.height(), int(math.ceil(max(point.y for point in region.polygon))))
            if right <= left or bottom <= top:
                raise ValueError("HTR_LINE_CROP_OUTSIDE_FRAME")
            png = self._png_bytes(image.copy(QRect(left, top, right - left, bottom - top)))
            digest, _path = self.repository.store_derivative(png, suffix="png")
            crops.append((region.region_id, digest, png))
        return frame_id, tuple(crops)

    def _htr_runtime(self, provider_id: str) -> HtrRuntime:
        memory_limit = 1024 * 1024 * 1024 if provider_id == "crnn-rukopys" else 4 * 1024 * 1024 * 1024
        python_text = self.htr_python_path.text().strip()
        model_root_text = self.htr_model_root.text().strip()
        if not python_text:
            raise ValueError("HTR_PYTHON_NOT_CONFIGURED")
        if not model_root_text:
            raise ValueError("HTR_MODEL_ROOT_NOT_CONFIGURED")
        return HtrRuntime(
            python_executable=Path(python_text), model_root=Path(model_root_text),
            timeout_seconds=self.htr_timeout.value(),
            memory_limit_bytes=memory_limit,
        )

    def run_htr(self) -> None:
        if self.current_record is None or self._htr_worker is not None:
            return
        provider_id = str(self.htr_provider_combo.currentData())
        try:
            frame_id, crops = self._htr_crops()
            runtime = self._htr_runtime(provider_id)
            request = make_htr_request(
                provider_id, crops, timeout_seconds=runtime.timeout_seconds,
                memory_limit_bytes=runtime.memory_limit_bytes,
            )
            client = HtrProcessClient(runtime, worker_script=self._htr_worker_script)
        except (OSError, ValueError) as exc:
            self._set_status("photo.htr.failed", error=str(exc))
            return
        worker = HtrRecognitionWorker(
            client, self.htr_results, request,
            source_manifest_sha256=self.current_record.sha256,
            original_sha256=self.current_record.photo.original_sha256,
            frame_id=frame_id,
        )
        worker.signals.progress.connect(self._htr_progress)
        worker.signals.succeeded.connect(self._htr_succeeded)
        worker.signals.cancelled.connect(self._htr_cancelled)
        worker.signals.failed.connect(self._htr_failed)
        self._htr_worker = worker
        self._refresh_htr_controls()
        self.htr_progress.setRange(0, len(crops))
        self.htr_progress.setValue(0)
        self._set_status("photo.htr.started", count=len(crops))
        self._thread_pool.start(worker)

    def cancel_htr(self) -> None:
        if self._htr_worker is not None:
            self._htr_worker.cancel()
            self.htr_cancel_button.setEnabled(False)
            self._set_status("photo.htr.cancelling")

    def _htr_progress(self, completed: int, total: int, _stage: str) -> None:
        self.htr_progress.setRange(0, total)
        self.htr_progress.setValue(completed)
        self._set_status("photo.htr.progress", completed=completed, total=total)

    def _htr_succeeded(self, record: HtrRunRecord) -> None:
        self._htr_worker = None
        self._show_htr_run(record)
        self._refresh_htr_controls()
        self._set_status("photo.htr.complete", count=len(record.run.lines))

    def _htr_cancelled(self, record: HtrRunRecord) -> None:
        self._htr_worker = None
        self._show_htr_run(record)
        self._refresh_htr_controls()
        self._set_status("photo.htr.cancelled")

    def _htr_failed(self, record: HtrRunRecord) -> None:
        self._htr_worker = None
        self._show_htr_run(record)
        self._refresh_htr_controls()
        self._set_status("photo.htr.failed", error=record.run.error_code or "HTR_PROVIDER_FAILED")

    def _restore_htr_results(self, record: PhotoRecord) -> None:
        runs = self.htr_results.list_for_source(record.sha256)
        if runs:
            self._show_htr_run(runs[0])
        else:
            self.htr_results_view.setPlainText(tr(self.language, "photo.htr.empty"))

    def _show_htr_run(self, record: HtrRunRecord) -> None:
        run = record.run
        header = f"{run.provider_id} · {run.status} · {run.model_revision or '—'}"
        if run.status != "succeeded":
            self.htr_results_view.setPlainText(f"{header}\n{run.error_code or '—'}")
            return
        rows = [header, tr(self.language, "photo.htr.no_confidence")]
        rows.extend(f"{item.line_id}: {item.text}" for item in run.lines)
        self.htr_results_view.setPlainText("\n".join(rows))
        self._refresh_transcription_review()

    def _latest_successful_htr(self) -> HtrRunRecord | None:
        if self.current_record is None:
            return None
        return next(
            (record for record in self.htr_results.list_for_source(self.current_record.sha256)
             if record.run.status == "succeeded"),
            None,
        )

    def _refresh_transcription_review(self) -> None:
        """Rebuild only from current immutable crops and local HTR provenance.

        A review revision is selected only when its manifest, line ID and crop
        hash all match.  Thus a later segmentation can never receive text from
        an earlier crop just because it reused a visual line position.
        """
        if (
            self._review_dirty
            and self.current_record is not None
            and self._review_source_manifest_sha256 == self.current_record.sha256
        ):
            self.review_summary_label.setText("Save this revision before accepting a newer HTR result.")
            return
        selected_line_id = (
            self._review_lines[self._review_current_index].line_id
            if self._review_current_index is not None and self._review_current_index < len(self._review_lines)
            else None
        )
        self._review_lines = []
        self._review_current_index = None
        self._review_current_record = None
        self._review_dirty = False
        self._review_order_sha256 = None
        if self.current_record is None:
            self._review_source_manifest_sha256 = None
            self.review_group.setVisible(False)
            return
        self._review_source_manifest_sha256 = self.current_record.sha256
        try:
            _frame_id, crops = self._htr_crops()
        except (OSError, ValueError):
            self.review_group.setVisible(False)
            return
        successful_run = self._latest_successful_htr()
        result_by_line = (
            {result.line_id: result for result in successful_run.run.lines}
            if successful_run is not None else {}
        )
        lines = [
            _ReviewLine(
                line_id=line_id,
                crop_sha256=crop_sha256,
                png=png,
                original_prediction=(
                    result_by_line[line_id].text
                    if line_id in result_by_line and result_by_line[line_id].crop_sha256 == crop_sha256
                    else None
                ),
                htr_run_sha256=successful_run.sha256 if line_id in result_by_line else None,
                provider_summary=(
                    f"{successful_run.run.provider_id} · {successful_run.run.model_revision or 'unknown revision'}"
                    if line_id in result_by_line else "No successful HTR result"
                ),
                confidence_summary=(
                    "Confidence: not provided by this provider."
                    if line_id in result_by_line else "Confidence: unavailable (no HTR result)."
                ),
            )
            for line_id, crop_sha256, png in crops
        ]
        latest_order = self.transcription_reviews.latest_order(self.current_record.sha256)
        current_keys = {(line.line_id, line.crop_sha256) for line in lines}
        if latest_order is not None:
            stored_keys = {(entry.line_id, entry.crop_sha256) for entry in latest_order.revision.entries}
            if stored_keys == current_keys and len(stored_keys) == len(lines):
                positions = {
                    (entry.line_id, entry.crop_sha256): index
                    for index, entry in enumerate(latest_order.revision.entries)
                }
                lines.sort(key=lambda line: positions[(line.line_id, line.crop_sha256)])
                self._review_order_sha256 = latest_order.sha256
        self._review_lines = lines
        self.review_group.setVisible(bool(lines))
        with QSignalBlocker(self.review_line_list):
            self.review_line_list.clear()
            for index, line in enumerate(lines, start=1):
                record = self.transcription_reviews.latest_for_line(
                    self.current_record.sha256, line.line_id, line.crop_sha256
                )
                status = record.revision.status if record is not None else "unreviewed"
                item = QListWidgetItem(f"{index}. {line.line_id} · {status}")
                item.setData(Qt.ItemDataRole.UserRole, line.line_id)
                self.review_line_list.addItem(item)
        self.review_summary_label.setText(
            f"{len(lines)} line(s). Reviews are local, append-only revisions; source pixels and HTR runs stay unchanged."
        )
        if not lines:
            return
        target_index = next(
            (index for index, line in enumerate(lines) if line.line_id == selected_line_id), 0
        )
        self._load_review_row(target_index)
        with QSignalBlocker(self.review_line_list):
            self.review_line_list.setCurrentRow(target_index)

    def _review_select_row(self, row: int) -> None:
        if self._review_selection_guard or row < 0 or row >= len(self._review_lines):
            return
        if self._review_dirty and row != self._review_current_index:
            self._review_selection_guard = True
            self.review_line_list.setCurrentRow(self._review_current_index or 0)
            self._review_selection_guard = False
            self.review_summary_label.setText("Save this revision before changing lines; unsaved text was kept in the editor.")
            return
        self._load_review_row(row)

    def _load_review_row(self, row: int) -> None:
        if self.current_record is None or row < 0 or row >= len(self._review_lines):
            return
        line = self._review_lines[row]
        latest = self.transcription_reviews.latest_for_line(
            self.current_record.sha256, line.line_id, line.crop_sha256
        )
        self._review_current_index = row
        self._review_current_record = latest
        original_prediction = latest.revision.original_prediction if latest is not None else line.original_prediction
        reviewed_text = latest.revision.reviewed_text if latest is not None else (original_prediction or "")
        status = latest.revision.status if latest is not None else "unreviewed"
        pixmap = QPixmap()
        pixmap.loadFromData(line.png, "PNG")
        if not pixmap.isNull():
            self.review_crop_label.setPixmap(pixmap.scaledToHeight(100, Qt.TransformationMode.SmoothTransformation))
        else:
            self.review_crop_label.setText("Crop preview unavailable")
        self.review_prediction_label.setText(
            f"Original HTR prediction: {original_prediction if original_prediction is not None else '— (none)'}"
        )
        run_sha = latest.revision.htr_run_sha256 if latest is not None else line.htr_run_sha256
        self.review_provenance_label.setText(
            f"Line: {line.line_id} · {line.provider_summary}\n{line.confidence_summary}\n"
            f"Crop SHA-256: {line.crop_sha256}\nHTR run: {run_sha or '—'}"
        )
        with QSignalBlocker(self.review_editor), QSignalBlocker(self.review_status_combo):
            self.review_editor.setPlainText(reviewed_text)
            self.review_status_combo.setCurrentIndex(self.review_status_combo.findData(status))
        self._review_dirty = False
        self._refresh_review_actions()

    def _refresh_review_actions(self) -> None:
        current = self._review_current_index
        has_current = current is not None
        self.review_editor.setEnabled(has_current)
        self.review_status_combo.setEnabled(has_current)
        self.review_save_button.setEnabled(has_current)
        self.review_previous_button.setEnabled(bool(has_current and current > 0))
        self.review_next_button.setEnabled(bool(has_current and current < len(self._review_lines) - 1))
        self.review_move_up_button.setEnabled(bool(has_current and current > 0 and not self._review_dirty))
        self.review_move_down_button.setEnabled(bool(
            has_current and current < len(self._review_lines) - 1 and not self._review_dirty
        ))

    def _review_text_changed(self) -> None:
        if self._review_current_index is not None:
            self._review_dirty = True
            self._refresh_review_actions()

    def _review_status_changed(self, _index: int) -> None:
        if self._review_current_index is not None:
            self._review_dirty = True
            self._refresh_review_actions()

    def _review_navigate(self, offset: int) -> None:
        if self._review_current_index is None or self._review_dirty:
            if self._review_dirty:
                self.review_summary_label.setText("Save this revision before changing lines; unsaved text was kept in the editor.")
            return
        destination = self._review_current_index + offset
        if 0 <= destination < len(self._review_lines):
            self.review_line_list.setCurrentRow(destination)

    def save_review_revision(self) -> None:
        if self.current_record is None or self._review_current_index is None:
            return
        if self._review_source_manifest_sha256 != self.current_record.sha256:
            self.review_summary_label.setText(
                "The segmentation changed. This editor still shows the old crop; reload before saving."
            )
            return
        line = self._review_lines[self._review_current_index]
        previous = self._review_current_record
        original_prediction = previous.revision.original_prediction if previous is not None else line.original_prediction
        htr_run_sha256 = previous.revision.htr_run_sha256 if previous is not None else line.htr_run_sha256
        status = str(self.review_status_combo.currentData())
        if status == "unreviewed" and self.review_editor.toPlainText() != (original_prediction or ""):
            status = "edited"
        try:
            saved = self.transcription_reviews.append(
                source_manifest_sha256=self.current_record.sha256,
                line_id=line.line_id,
                crop_sha256=line.crop_sha256,
                htr_run_sha256=htr_run_sha256,
                original_prediction=original_prediction,
                reviewed_text=self.review_editor.toPlainText(),
                status=status,  # type: ignore[arg-type]  # populated from the closed combo set above
                expected_parent_revision_sha256=previous.sha256 if previous is not None else None,
            )
        except ReviewConflict:
            self.review_summary_label.setText("A newer review revision exists. Reload this line before saving.")
            return
        except (OSError, ValueError) as exc:
            self.review_summary_label.setText(f"Could not save review revision: {exc}")
            return
        self._review_current_record = saved
        self._review_dirty = False
        self._load_review_row(self._review_current_index)
        self.review_line_list.item(self._review_current_index).setText(
            f"{self._review_current_index + 1}. {line.line_id} · {saved.revision.status}"
        )
        self.review_summary_label.setText("Review revision saved locally. The original HTR result remains unchanged.")

    def _move_review_line(self, offset: int) -> None:
        if self.current_record is None or self._review_current_index is None or self._review_dirty:
            return
        destination = self._review_current_index + offset
        if not 0 <= destination < len(self._review_lines):
            return
        reordered = list(self._review_lines)
        selected = reordered.pop(self._review_current_index)
        reordered.insert(destination, selected)
        try:
            self.transcription_reviews.append_order(
                source_manifest_sha256=self.current_record.sha256,
                entries=tuple(
                    ReadingOrderEntry(line_id=line.line_id, crop_sha256=line.crop_sha256)
                    for line in reordered
                ),
                expected_parent_revision_sha256=self._review_order_sha256,
            )
        except ReviewConflict:
            self.review_summary_label.setText("A newer reading order exists. Reload the photo before changing order.")
            return
        except (OSError, ValueError) as exc:
            self.review_summary_label.setText(f"Could not save reading order: {exc}")
            return
        selected_line_id = selected.line_id
        self._refresh_transcription_review()
        selected_index = next(
            index for index, line in enumerate(self._review_lines) if line.line_id == selected_line_id
        )
        self.review_line_list.setCurrentRow(selected_index)
        self.review_summary_label.setText("Reading order saved as an immutable local revision.")

    def reset_view(self) -> None:
        if self.current_record is None:
            return
        self._display_rotation = 0
        self._refresh_corrected_preview()
        self._fit_views()
        self._refresh_diagnostics()

    def _refresh_corrected_preview(self) -> None:
        transform = QTransform().rotate(self._display_rotation)
        base = self._corrected_pixmap if not self._corrected_pixmap.isNull() else self._source_pixmap
        display = base.transformed(transform, Qt.TransformationMode.SmoothTransformation)
        self.corrected_view.set_pixmap(display)
        self._refresh_ruling_overlay()

    def detect_page(self) -> None:
        if self.current_record is None:
            return
        try:
            photo = self.current_record.photo
            proposal = OpenCvPageCorrector().propose(
                self.repository.read_original(photo),
                orientation=photo.metadata.embedded_orientation,
                source_frame_id=self._preview_frame_id(photo.metadata.embedded_orientation),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self._set_status("photo.correction.failed", error=str(exc))
            return
        if proposal.status == "not_found" or proposal.corners is None:
            self._set_status("photo.correction.not_found")
            self.apply_correction_button.setEnabled(False)
            return
        self.original_view.set_corners(proposal.corners)
        self._proposal_method = proposal.method
        self._proposal_confidence = proposal.confidence
        self.apply_correction_button.setEnabled(True)
        confidence = f"{proposal.confidence.value:.0%}" if proposal.confidence else "—"
        self._set_status("photo.correction.proposed", confidence=confidence)

    def enable_manual_corners(self) -> None:
        if self.current_record is None or self._source_pixmap.isNull():
            return
        width = self._source_pixmap.width()
        height = self._source_pixmap.height()
        inset_x = max(1.0, width * 0.05)
        inset_y = max(1.0, height * 0.05)
        self.original_view.set_corners(
            PageCorners(
                frame_id=self._preview_frame_id(
                    self.current_record.photo.metadata.embedded_orientation
                ),
                top_left=PixelPoint(x=inset_x, y=inset_y),
                top_right=PixelPoint(x=width - 1 - inset_x, y=inset_y),
                bottom_right=PixelPoint(
                    x=width - 1 - inset_x, y=height - 1 - inset_y
                ),
                bottom_left=PixelPoint(x=inset_x, y=height - 1 - inset_y),
            )
        )
        self._proposal_method = "manual-four-corner/1"
        self._proposal_confidence = None
        self.apply_correction_button.setEnabled(True)
        self._set_status("photo.correction.manual")

    def apply_correction(self) -> None:
        if self.current_record is None:
            return
        try:
            photo = self.current_record.photo
            corners = self.original_view.corners(
                self._preview_frame_id(photo.metadata.embedded_orientation)
            )
            raster = OpenCvPageCorrector().correct(
                self.repository.read_original(photo),
                corners,
                orientation=photo.metadata.embedded_orientation,
                deskew_degrees=(
                    self.deskew_spin.value() if self.deskew_check.isChecked() else 0.0
                ),
            )
            correction = persist_correction(
                self.repository,
                self.current_record,
                raster,
                proposal_method=self._proposal_method,
                confidence=self._proposal_confidence,
            )
            image = QImage.fromData(raster.content)
            if image.isNull():
                raise ValueError("CORRECTED_PHOTO_PREVIEW_FAILED")
        except (OSError, RuntimeError, ValueError) as exc:
            self._set_status("photo.correction.failed", error=str(exc))
            return
        self.current_record = correction.record
        self._corrected_pixmap = QPixmap.fromImage(image)
        self._display_rotation = 0
        self._refresh_corrected_preview()
        self.correction_notice.setText(tr(self.language, "photo.correction.applied"))
        self._set_status(
            "photo.correction.complete", width=raster.width_px, height=raster.height_px
        )
        self._refresh_diagnostics()
        self._refresh_geometry_controls()
        self._refresh_ruling_overlay()

    def _restore_correction_preview(self, record: PhotoRecord) -> None:
        if not record.photo.transforms:
            self.correction_notice.setText(tr(self.language, "photo.correction.notice"))
            return
        transform = record.photo.transforms[-1]
        image = QImage.fromData(
            self.repository.derivative_path(transform.output_sha256, "png").read_bytes()
        )
        if image.isNull():
            raise ValueError("CORRECTED_PHOTO_PREVIEW_FAILED")
        self._corrected_pixmap = QPixmap.fromImage(image)
        self.correction_notice.setText(tr(self.language, "photo.correction.applied"))

    @staticmethod
    def _preview_frame_id(orientation: str) -> str:
        return "source-pixels" if orientation == "none" else "oriented-preview"

    @staticmethod
    def _apply_orientation(image: QImage, orientation: str) -> QImage:
        if orientation == "none":
            return image
        if orientation == "mirror_horizontal":
            return image.mirrored(True, False)
        if orientation == "flip_vertical":
            return image.mirrored(False, True)
        if orientation == "rotate_180":
            return image.transformed(QTransform().rotate(180))
        if orientation == "rotate_90":
            return image.transformed(QTransform().rotate(90))
        if orientation == "rotate_270":
            return image.transformed(QTransform().rotate(-90))
        if orientation == "mirror_horizontal_rotate_90":
            return image.mirrored(True, False).transformed(QTransform().rotate(-90))
        if orientation == "flip_vertical_rotate_90":
            return image.mirrored(True, False).transformed(QTransform().rotate(90))
        raise ValueError("UNSUPPORTED_PHOTO_ORIENTATION")

    def _set_zoom(self, factor: float) -> None:
        self.original_view.set_zoom_factor(factor)
        self.corrected_view.set_zoom_factor(factor)

    def _actual_size(self) -> None:
        self.original_view.actual_size()
        self.corrected_view.actual_size()

    def _fit_views(self) -> None:
        self.original_view.fit_image()
        self.corrected_view.fit_image()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for button in (
            self.zoom_out_button,
            self.actual_size_button,
            self.fit_button,
            self.zoom_in_button,
            self.rotate_left_button,
            self.rotate_right_button,
            self.reset_button,
        ):
            button.setEnabled(enabled)
        cv_enabled = enabled and opencv_available()
        self.detect_page_button.setEnabled(cv_enabled)
        self.manual_corners_button.setEnabled(cv_enabled)
        self.analyze_paper_button.setEnabled(cv_enabled)
        self.paper_classification_combo.setEnabled(enabled)
        self.override_ruling_button.setEnabled(enabled)
        self.detect_geometry_button.setEnabled(False)
        self.show_ruling_overlay_check.setEnabled(False)
        self.apply_geometry_button.setEnabled(False)
        self.scale_reference_spin.setEnabled(False)
        self.apply_scale_button.setEnabled(False)
        self.apply_5mm_preset_button.setEnabled(False)
        self.separate_ink_button.setEnabled(False)
        self.use_raw_mask_button.setEnabled(False)
        self.detect_lines_button.setEnabled(False)
        self.htr_group.setEnabled(False)
        for widget in (
            self.pitch_x_spin,
            self.pitch_y_spin,
            self.origin_x_spin,
            self.origin_y_spin,
            self.ruling_angle_spin,
        ):
            widget.setEnabled(False)

    def _classification_label(self, classification: str) -> str:
        return tr(self.language, f"photo.ruling.classification.{classification}")

    def _refresh_ruling_controls(self) -> None:
        if self.current_record is None:
            self.paper_summary_label.clear()
            return
        ruling = self.current_record.photo.ruling
        index = self.paper_classification_combo.findData(ruling.classification)
        if index >= 0:
            self.paper_classification_combo.setCurrentIndex(index)
        confidence = ""
        if ruling.confidence is not None:
            confidence = f" · {ruling.confidence.value:.0%}"
        self.paper_summary_label.setText(
            tr(self.language, "photo.ruling.summary").format(
                classification=self._classification_label(ruling.classification),
                status=tr(self.language, f"photo.ruling.status.{ruling.status}"),
                confidence=confidence,
            )
        )

    @staticmethod
    def _has_ruling_geometry(ruling: RulingEstimate) -> bool:
        return ruling.ruling_pitch_px is not None or (
            ruling.cell_pitch_x_px is not None and ruling.cell_pitch_y_px is not None
        )

    def _refresh_geometry_controls(self) -> None:
        if self.current_record is None:
            self.geometry_summary_label.clear()
            return
        ruling = self.current_record.photo.ruling
        applicable = ruling.classification in {"squared", "ruled"}
        detected = self._has_ruling_geometry(ruling)
        cv_enabled = opencv_available() and applicable
        self.detect_geometry_button.setEnabled(cv_enabled)
        self.show_ruling_overlay_check.setEnabled(detected)
        self.apply_geometry_button.setEnabled(applicable)
        for widget in (self.pitch_y_spin, self.origin_y_spin, self.ruling_angle_spin):
            widget.setEnabled(applicable)
        squared = ruling.classification == "squared"
        self.pitch_x_spin.setEnabled(squared)
        self.origin_x_spin.setEnabled(squared)
        if detected:
            self.pitch_x_spin.setValue(ruling.cell_pitch_x_px or 0.01)
            self.pitch_y_spin.setValue(ruling.cell_pitch_y_px or ruling.ruling_pitch_px or 0.01)
            self.origin_x_spin.setValue(ruling.origin_x_px or 0.0)
            self.origin_y_spin.setValue(ruling.origin_y_px or 0.0)
            self.ruling_angle_spin.setValue(ruling.horizontal_angle_deg or 0.0)
        self.pitch_y_label.setText(
            tr(self.language, "photo.geometry.pitch_y" if squared else "photo.geometry.ruling_pitch")
        )
        self.geometry_summary_label.setText(self._geometry_summary(ruling))

    def _geometry_summary(self, ruling: RulingEstimate) -> str:
        if not self._has_ruling_geometry(ruling):
            return tr(self.language, "photo.geometry.empty")
        if ruling.classification == "squared":
            return tr(self.language, "photo.geometry.grid_summary").format(
                x=ruling.cell_pitch_x_px,
                y=ruling.cell_pitch_y_px,
                residual=max(ruling.horizontal_residual_px or 0.0, ruling.vertical_residual_px or 0.0),
            )
        return tr(self.language, "photo.geometry.ruled_summary").format(
            pitch=ruling.ruling_pitch_px,
            residual=ruling.horizontal_residual_px or 0.0,
        )

    def _refresh_calibration_controls(self) -> None:
        if self.current_record is None:
            self.scale_summary_label.clear()
            return
        photo = self.current_record.photo
        available = self._has_ruling_geometry(photo.ruling)
        self.scale_reference_spin.setEnabled(available)
        self.apply_scale_button.setEnabled(available)
        self.apply_5mm_preset_button.setEnabled(available)
        calibration = photo.calibration
        if calibration is None:
            self.scale_summary_label.setText(tr(self.language, "photo.scale.unknown"))
            return
        if calibration.reference_pitch_mm is not None:
            self.scale_reference_spin.setValue(calibration.reference_pitch_mm)
        x_value = (
            tr(self.language, "photo.scale.axis_unknown")
            if calibration.mm_per_px_x is None
            else tr(self.language, "photo.scale.axis_value").format(
                value=calibration.mm_per_px_x
            )
        )
        y_value = (
            tr(self.language, "photo.scale.axis_unknown")
            if calibration.mm_per_px_y is None
            else tr(self.language, "photo.scale.axis_value").format(
                value=calibration.mm_per_px_y
            )
        )
        self.scale_summary_label.setText(
            tr(self.language, "photo.scale.summary").format(
                source=tr(self.language, f"photo.scale.source.{calibration.source}"),
                x=x_value,
                y=y_value,
            )
        )

    def _refresh_mask_controls(self) -> None:
        if self.current_record is None:
            self.mask_summary_label.clear()
            return
        self.separate_ink_button.setEnabled(opencv_available())
        mask = self.current_record.photo.ink_mask
        self.use_raw_mask_button.setEnabled(mask is not None and mask.selected_variant != "raw")
        if mask is None:
            self.mask_summary_label.setText(tr(self.language, "photo.mask.empty"))
            return
        self.mask_summary_label.setText(
            tr(self.language, "photo.mask.summary").format(
                variant=tr(self.language, f"photo.mask.variant.{mask.selected_variant}"),
                status=tr(self.language, f"photo.mask.status.{mask.status}"),
            )
        )

    def _refresh_line_controls(self) -> None:
        if self.current_record is None:
            self.lines_summary_label.clear()
            return
        mask = self.current_record.photo.ink_mask
        self.detect_lines_button.setEnabled(mask is not None and opencv_available())
        lines = tuple(region for region in self.current_record.photo.regions if region.kind == "line")
        self.lines_summary_label.setText(
            tr(self.language, "photo.lines.summary").format(count=len(lines))
            if lines else tr(self.language, "photo.lines.empty")
        )

    def _refresh_htr_controls(self) -> None:
        active = self._htr_worker is not None
        has_lines = self.current_record is not None and any(
            region.kind == "line" for region in self.current_record.photo.regions
        )
        self.htr_group.setEnabled(self.current_record is not None)
        self.htr_provider_combo.setEnabled(not active)
        self.htr_python_path.setEnabled(not active)
        self.htr_model_root.setEnabled(not active)
        self.htr_timeout.setEnabled(not active)
        self.htr_run_button.setEnabled(has_lines and not active)
        self.htr_cancel_button.setEnabled(active)

    def _refresh_ruling_overlay(self) -> None:
        self.original_view.clear_ruling_overlay()
        self.corrected_view.clear_ruling_overlay()
        if (
            not self.show_ruling_overlay_check.isChecked()
            or self.current_record is None
            or self._display_rotation != 0
        ):
            return
        ruling = self.current_record.photo.ruling
        if not self._has_ruling_geometry(ruling):
            return
        if self.current_record.photo.transforms and ruling.frame_id == self.current_record.photo.transforms[-1].output_frame_id:
            self.corrected_view.set_ruling_overlay(ruling)
        elif ruling.frame_id == self.current_record.photo.frames[0].frame_id:
            self.original_view.set_ruling_overlay(ruling)

    def _set_status(self, key: str, **values: object) -> None:
        self._status_key = key
        self._status_values = values
        self.status_label.setText(tr(self.language, key).format(**values))

    def _refresh_diagnostics(self) -> None:
        if self.current_record is None:
            self.diagnostics.setPlainText(tr(self.language, "photo.diagnostics.empty"))
            return
        if self._review_source_manifest_sha256 != self.current_record.sha256 and not self._review_dirty:
            self._refresh_transcription_review()
        photo = self.current_record.photo
        metadata = photo.metadata
        correction_status = tr(self.language, "photo.correction.pending")
        if photo.transforms:
            latest = photo.transforms[-1]
            correction_status = f"{latest.algorithm_id} · {latest.output_frame_id}"
        diagnostics = (
            ("photo.diagnostics.file", metadata.original_filename),
            ("photo.diagnostics.format", f"{metadata.detected_format} · {metadata.media_type}"),
            ("photo.diagnostics.dimensions", f"{photo.page_dimensions.width_px} × {photo.page_dimensions.height_px} px"),
            ("photo.diagnostics.size", f"{metadata.encoded_bytes:,} B"),
            ("photo.diagnostics.orientation", metadata.embedded_orientation),
            ("photo.diagnostics.rotation", f"{self._display_rotation}°"),
            ("photo.diagnostics.hash", photo.original_sha256),
            ("photo.diagnostics.storage", str(self.current_record.path)),
            (
                "photo.diagnostics.ruling",
                f"{self._classification_label(photo.ruling.classification)} · "
                f"{tr(self.language, f'photo.ruling.status.{photo.ruling.status}')}"
                + (f" · {photo.ruling.confidence.value:.0%}" if photo.ruling.confidence else ""),
            ),
            ("photo.diagnostics.geometry", self._geometry_summary(photo.ruling)),
            ("photo.diagnostics.scale", self.scale_summary_label.text()),
            ("photo.diagnostics.mask", self.mask_summary_label.text()),
            ("photo.diagnostics.lines", self.lines_summary_label.text()),
            ("photo.diagnostics.correction", correction_status),
        )
        self.diagnostics.setPlainText(
            "\n".join(f"{tr(self.language, key)}: {value}" for key, value in diagnostics)
        )

    def set_language(self, language: Language) -> None:
        self.language = language
        self.title_label.setText(tr(language, "photo.title"))
        self.subtitle_label.setText(tr(language, "photo.subtitle"))
        self.choose_button.setText(tr(language, "photo.choose"))
        self.fit_button.setText(tr(language, "photo.fit"))
        self.reset_button.setText(tr(language, "photo.reset"))
        self.detect_page_button.setText(tr(language, "photo.correction.detect"))
        self.manual_corners_button.setText(tr(language, "photo.correction.manual_button"))
        self.apply_correction_button.setText(tr(language, "photo.correction.apply"))
        self.deskew_check.setText(tr(language, "photo.correction.deskew"))
        self.analyze_paper_button.setText(tr(language, "photo.ruling.analyze"))
        self.paper_classification_label.setText(tr(language, "photo.ruling.label"))
        self.override_ruling_button.setText(tr(language, "photo.ruling.override"))
        self.detect_geometry_button.setText(tr(language, "photo.geometry.detect"))
        self.show_ruling_overlay_check.setText(tr(language, "photo.geometry.overlay"))
        self.pitch_x_label.setText(tr(language, "photo.geometry.pitch_x"))
        self.origin_x_label.setText(tr(language, "photo.geometry.origin_x"))
        self.origin_y_label.setText(tr(language, "photo.geometry.origin_y"))
        self.ruling_angle_label.setText(tr(language, "photo.geometry.angle"))
        self.apply_geometry_button.setText(tr(language, "photo.geometry.apply"))
        self.scale_reference_label.setText(tr(language, "photo.scale.reference"))
        self.apply_scale_button.setText(tr(language, "photo.scale.apply"))
        self.apply_5mm_preset_button.setText(tr(language, "photo.scale.preset"))
        self.separate_ink_button.setText(tr(language, "photo.mask.separate"))
        self.use_raw_mask_button.setText(tr(language, "photo.mask.use_raw"))
        self.detect_lines_button.setText(tr(language, "photo.lines.detect"))
        self.htr_group.setTitle(tr(language, "photo.htr.title"))
        for key, label in self._htr_labels.items():
            label.setText(tr(language, key))
        self.htr_run_button.setText(tr(language, "photo.htr.run"))
        self.htr_cancel_button.setText(tr(language, "photo.htr.cancel"))
        for index in range(self.paper_classification_combo.count()):
            classification = self.paper_classification_combo.itemData(index)
            self.paper_classification_combo.setItemText(
                index, self._classification_label(str(classification))
            )
        self.original_group.setTitle(tr(language, "photo.original"))
        self.corrected_group.setTitle(tr(language, "photo.corrected"))
        correction_key = (
            "photo.correction.applied"
            if self.current_record is not None and self.current_record.photo.transforms
            else "photo.correction.notice"
        )
        self.correction_notice.setText(tr(language, correction_key))
        self.diagnostics_group.setTitle(tr(language, "photo.diagnostics"))
        self._set_status(self._status_key, **self._status_values)
        self._refresh_ruling_controls()
        self._refresh_geometry_controls()
        self._refresh_calibration_controls()
        self._refresh_mask_controls()
        self._refresh_line_controls()
        self._refresh_htr_controls()
        self._refresh_ruling_overlay()
        self._refresh_diagnostics()
