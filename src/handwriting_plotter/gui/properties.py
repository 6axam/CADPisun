"""Editable property surfaces for pages and text objects."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .document import PageSettings, TextObject
from .styles import StyleSummary


def _millimetre_spin(minimum: float = 0.0, maximum: float = 297.0) -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setRange(minimum, maximum)
    field.setDecimals(2)
    field.setSingleStep(0.5)
    field.setSuffix(" mm")
    return field


class PropertiesPanel(QWidget):
    text_object_changed = Signal(str, object)
    page_changed = Signal(object)

    def __init__(self, styles: tuple[StyleSummary, ...], parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setObjectName("properties-panel")
        self._styles = styles
        self._object_id: str | None = None
        self._loading = False
        self.stack = QStackedWidget()
        self.page_widget = self._build_page_widget()
        self.text_widget = self._build_text_widget()
        self.resource_widget = self._build_resource_widget()
        self.empty_widget = QLabel("Select a page, text object, or StylePack.")
        self.empty_widget.setWordWrap(True)
        for widget in (self.empty_widget, self.page_widget, self.text_widget, self.resource_widget):
            self.stack.addWidget(widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self.stack)

    def _build_page_widget(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow("Format", QLabel("A4 · 210 × 297 mm"))
        self.page_fields = {
            "margin_left_mm": _millimetre_spin(0, 100),
            "margin_right_mm": _millimetre_spin(0, 100),
            "margin_top_mm": _millimetre_spin(0, 140),
            "margin_bottom_mm": _millimetre_spin(0, 140),
            "paragraph_gap_mm": _millimetre_spin(0, 50),
            "pen_width_mm": _millimetre_spin(0.05, 3),
        }
        labels = {
            "margin_left_mm": "Left margin",
            "margin_right_mm": "Right margin",
            "margin_top_mm": "Top margin",
            "margin_bottom_mm": "Bottom margin",
            "paragraph_gap_mm": "Paragraph gap",
            "pen_width_mm": "Pen width",
        }
        for name, field in self.page_fields.items():
            field.valueChanged.connect(self._emit_page)
            form.addRow(labels[name], field)
        return widget

    def _build_text_widget(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.name_field = QLineEdit()
        self.text_field = QPlainTextEdit()
        self.text_field.setMinimumHeight(150)
        self.x_field = _millimetre_spin(0, 209.9)
        self.y_field = _millimetre_spin(0, 296.9)
        self.x_height_field = _millimetre_spin(0.5, 30)
        self.line_pitch_field = _millimetre_spin(0.5, 100)
        self.style_field = QComboBox()
        for style in self._styles:
            label = f"{style.display_name} · {style.revision}"
            self.style_field.addItem(label, f"{style.style_id}\0{style.revision}")
        self.seed_field = QDoubleSpinBox()
        self.seed_field.setDecimals(0)
        self.seed_field.setRange(-2_147_483_648, 2_147_483_647)
        self.realism_field = QDoubleSpinBox()
        self.realism_field.setRange(0, 1)
        self.realism_field.setSingleStep(0.05)
        self.realism_field.setDecimals(2)
        form.addRow("Name", self.name_field)
        form.addRow("Text", self.text_field)
        form.addRow("X", self.x_field)
        form.addRow("Y", self.y_field)
        form.addRow("x-height", self.x_height_field)
        form.addRow("Line pitch", self.line_pitch_field)
        form.addRow("Style", self.style_field)
        form.addRow("Seed", self.seed_field)
        form.addRow("Realism", self.realism_field)
        self.name_field.editingFinished.connect(self._emit_text)
        self.text_field.textChanged.connect(self._emit_text)
        for field in (self.x_field, self.y_field, self.x_height_field, self.line_pitch_field,
                      self.seed_field, self.realism_field):
            field.valueChanged.connect(self._emit_text)
        self.style_field.currentIndexChanged.connect(self._emit_text)
        return widget

    def _build_resource_widget(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.resource_name = QLabel()
        self.resource_reference = QLabel()
        self.resource_status = QLabel()
        self.resource_detail = QLabel()
        self.resource_detail.setWordWrap(True)
        form.addRow("StylePack", self.resource_name)
        form.addRow("Reference", self.resource_reference)
        form.addRow("Status", self.resource_status)
        form.addRow("Validation", self.resource_detail)
        return widget

    def show_page(self, page: PageSettings) -> None:
        self._loading = True
        self._object_id = None
        for name, field in self.page_fields.items():
            field.setValue(getattr(page, name))
        self._loading = False
        self.stack.setCurrentWidget(self.page_widget)

    def show_text_object(self, item: TextObject) -> None:
        self._loading = True
        self._object_id = item.object_id
        self.name_field.setText(item.name)
        self.text_field.setPlainText(item.text)
        self.x_field.setValue(item.x_mm)
        self.y_field.setValue(item.y_mm)
        self.x_height_field.setValue(item.x_height_mm)
        self.line_pitch_field.setValue(item.line_pitch_mm)
        index = self.style_field.findData(f"{item.style_id}\0{item.style_revision}")
        self.style_field.setCurrentIndex(max(index, 0))
        self.seed_field.setValue(item.seed)
        self.realism_field.setValue(item.realism)
        self._loading = False
        self.stack.setCurrentWidget(self.text_widget)

    def show_style(self, style: StyleSummary) -> None:
        self._object_id = None
        self.resource_name.setText(style.display_name)
        self.resource_reference.setText(f"{style.style_id}@{style.revision}")
        status = "Test only" if style.test_only else "Production eligible"
        self.resource_status.setText(status if style.valid else "Invalid")
        self.resource_detail.setText(style.detail)
        self.stack.setCurrentWidget(self.resource_widget)

    def _emit_page(self) -> None:
        if self._loading:
            return
        self.page_changed.emit({name: field.value() for name, field in self.page_fields.items()})

    def _emit_text(self) -> None:
        if self._loading or self._object_id is None or self.style_field.currentIndex() < 0:
            return
        style_id, revision = self.style_field.currentData().split("\0", 1)
        self.text_object_changed.emit(self._object_id, {
            "name": self.name_field.text().strip() or "Text",
            "text": self.text_field.toPlainText(),
            "x_mm": self.x_field.value(),
            "y_mm": self.y_field.value(),
            "x_height_mm": self.x_height_field.value(),
            "line_pitch_mm": self.line_pitch_field.value(),
            "style_id": style_id,
            "style_revision": revision,
            "seed": int(self.seed_field.value()),
            "realism": self.realism_field.value(),
        })
