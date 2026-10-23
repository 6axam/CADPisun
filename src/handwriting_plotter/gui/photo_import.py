"""Dedicated notebook-photo import and inspection workspace."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap, QResizeEvent, QTransform
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
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
from handwriting_plotter.learning import PhotoRecord, PhotoRepository
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
        self._display_rotation = 0
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
            record = max(records, key=lambda item: item.photo.metadata.imported_at_utc)
            self._show_record(record, self._read_preview(record))
            self._set_status("photo.status.restored", name=record.photo.metadata.original_filename)
        except (OSError, ValueError) as exc:
            self._set_status("photo.status.restore_failed", error=str(exc))

    def _read_preview(self, record: PhotoRecord) -> QImage:
        image = QImage.fromData(self.repository.read_original(record.photo))
        if image.isNull():
            raise ValueError("PHOTO_PREVIEW_DECODE_FAILED")
        return image

    def _show_record(self, record: PhotoRecord, image: QImage) -> None:
        self.current_record = record
        self._source_pixmap = QPixmap.fromImage(image)
        self._display_rotation = 0
        self.original_view.set_pixmap(self._source_pixmap)
        self._refresh_corrected_preview()
        self._set_controls_enabled(True)
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
        display = self._source_pixmap.transformed(transform, Qt.TransformationMode.SmoothTransformation)
        self.corrected_view.set_pixmap(display)

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
            ("photo.diagnostics.correction", tr(self.language, "photo.correction.pending")),
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
        self.original_group.setTitle(tr(language, "photo.original"))
        self.corrected_group.setTitle(tr(language, "photo.corrected"))
        self.correction_notice.setText(tr(language, "photo.correction.notice"))
        self.diagnostics_group.setTitle(tr(language, "photo.diagnostics"))
        self._set_status(self._status_key, **self._status_values)
        self._refresh_diagnostics()
