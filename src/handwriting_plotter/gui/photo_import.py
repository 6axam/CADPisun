"""Dedicated notebook-photo import and inspection workspace."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPen, QPixmap, QResizeEvent, QTransform
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from handwriting_plotter.adapters.images.qt import QtImageDecoder
from handwriting_plotter.adapters.images.opencv import OpenCvPageCorrector, opencv_available
from handwriting_plotter.learning import (
    PageCorners,
    PhotoRecord,
    PhotoRepository,
    PixelPoint,
    persist_correction,
)
from handwriting_plotter.version import __version__

from .i18n import Language, tr

PHOTO_FILE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"


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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("photo-import-workspace")
        self.language = language
        self.repository = PhotoRepository(root)
        self.current_record: PhotoRecord | None = None
        self._source_pixmap = QPixmap()
        self._corrected_pixmap = QPixmap()
        self._display_rotation = 0
        self._proposal_method = "manual-four-corner/1"
        self._proposal_confidence = None
        self._status_key = "photo.status.empty"
        self._status_values: dict[str, object] = {}
        self._build_ui()
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
                key=lambda item: (item.photo.metadata.imported_at_utc, len(item.photo.transforms)),
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
        self._refresh_diagnostics()

    def rotate_preview(self, degrees: int) -> None:
        if self.current_record is None:
            return
        self._display_rotation = (self._display_rotation + degrees) % 360
        self._refresh_corrected_preview()
        self._refresh_diagnostics()

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

    def _set_status(self, key: str, **values: object) -> None:
        self._status_key = key
        self._status_values = values
        self.status_label.setText(tr(self.language, key).format(**values))

    def _refresh_diagnostics(self) -> None:
        if self.current_record is None:
            self.diagnostics.setPlainText(tr(self.language, "photo.diagnostics.empty"))
            return
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
            ("photo.diagnostics.ruling", photo.ruling.status),
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
        self._refresh_diagnostics()
