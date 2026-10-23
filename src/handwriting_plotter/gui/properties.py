"""Editable property surfaces for pages and text objects."""

from __future__ import annotations

from PySide6.QtCore import QSize, QRegularExpression, Signal
from PySide6.QtGui import QRegularExpressionValidator, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .document import GridObject, PageSettings, TEXT_COLOR_GROUPS, TextObject
from .i18n import Language, normalize_language, tr
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
    text_content_changed = Signal(str, object)
    grid_object_changed = Signal(str, object)
    page_changed = Signal(object)

    def __init__(
        self,
        styles: tuple[StyleSummary, ...],
        parent=None,  # noqa: ANN001
        *,
        language: Language = "en",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("properties-panel")
        self.setMinimumWidth(0)
        self._styles = styles
        self.language = normalize_language(language)
        self._object_id: str | None = None
        self._shown_style: StyleSummary | None = None
        self._loading = False
        self._color_group = 0
        self._labels: dict[str, QLabel] = {}
        self._groups: dict[str, QGroupBox] = {}
        self.stack = QStackedWidget()
        self.page_widget = self._build_page_widget()
        self.text_widget = self._build_text_widget()
        self.grid_widget = self._build_grid_widget()
        self.resource_widget = self._build_resource_widget()
        self.empty_widget = QLabel()
        self.empty_widget.setWordWrap(True)
        for widget in (self.empty_widget, self.page_widget, self.text_widget, self.grid_widget, self.resource_widget):
            self.stack.addWidget(widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self.stack)
        self.set_language(self.language)

    def _add_row(self, form: QFormLayout, key: str, field: QWidget) -> None:
        label = QLabel()
        form.addRow(label, field)
        self._labels[key] = label

    def _add_group(
        self,
        layout: QVBoxLayout,
        key: str,
        fields: list[tuple[str, QWidget]],
        *,
        columns: int = 2,
    ) -> QGroupBox:
        group = QGroupBox()
        grid = QGridLayout(group)
        grid.setContentsMargins(8, 10, 8, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        for index, (label_key, field) in enumerate(fields):
            row = (index // columns) * 2
            column = index % columns
            label = QLabel()
            label.setBuddy(field)
            field.setSizePolicy(QSizePolicy.Policy.Ignored, field.sizePolicy().verticalPolicy())
            grid.addWidget(label, row, column)
            grid.addWidget(field, row + 1, column)
            self._labels[label_key] = label
        layout.addWidget(group)
        self._groups[key] = group
        return group

    def _build_page_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.page_format = QLabel()
        self.page_fields = {
            "margin_left_mm": _millimetre_spin(0, 100),
            "margin_right_mm": _millimetre_spin(0, 100),
            "margin_top_mm": _millimetre_spin(0, 140),
            "margin_bottom_mm": _millimetre_spin(0, 140),
            "paragraph_gap_mm": _millimetre_spin(0, 50),
            "pen_width_mm": _millimetre_spin(0.05, 3),
        }
        for field in self.page_fields.values():
            field.valueChanged.connect(self._emit_page)
        self._add_group(layout, "properties.group.page", [("properties.format", self.page_format)])
        self._add_group(layout, "properties.group.margins", [
            ("properties.margin_left", self.page_fields["margin_left_mm"]),
            ("properties.margin_right", self.page_fields["margin_right_mm"]),
            ("properties.margin_top", self.page_fields["margin_top_mm"]),
            ("properties.margin_bottom", self.page_fields["margin_bottom_mm"]),
        ])
        self._add_group(layout, "properties.group.layout", [
            ("properties.paragraph_gap", self.page_fields["paragraph_gap_mm"]),
            ("properties.pen_width", self.page_fields["pen_width_mm"]),
        ])
        layout.addStretch(1)
        return widget

    def _build_text_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.name_field = QLineEdit()
        self.text_field = QPlainTextEdit()
        self.text_field.setMinimumHeight(100)
        self.text_field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.x_field = _millimetre_spin(0, 209.9)
        self.y_field = _millimetre_spin(0, 296.9)
        self.frame_x_field = _millimetre_spin(0, 209.9)
        self.frame_y_field = _millimetre_spin(0, 296.9)
        self.frame_width_field = _millimetre_spin(0.01, 210)
        self.frame_height_field = _millimetre_spin(0.01, 297)
        self.x_height_field = _millimetre_spin(0.5, 30)
        self.line_pitch_field = _millimetre_spin(0.5, 100)
        self.character_spacing_field = _millimetre_spin(0, 30)
        self.rotation_field = QDoubleSpinBox()
        self.rotation_field.setRange(-180, 180)
        self.rotation_field.setDecimals(1)
        self.rotation_field.setSuffix("°")
        self.display_diameter_field = _millimetre_spin(1, 20)
        self.style_field = QComboBox()
        for style in self._styles:
            if not style.valid:
                continue
            label = f"{style.display_name} · {style.revision}"
            self.style_field.addItem(label, f"{style.style_id}\0{style.revision}")
        self.seed_field = QLineEdit()
        self.seed_field.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9]{1,20}")))
        self.realism_field = QDoubleSpinBox()
        self.realism_field.setRange(0, 1)
        self.realism_field.setSingleStep(0.05)
        self.realism_field.setDecimals(2)
        content_group = QGroupBox()
        self.content_layout = QVBoxLayout(content_group)
        self.content_layout.setContentsMargins(8, 10, 8, 8)
        content_top = QWidget()
        content_top_layout = QHBoxLayout(content_top)
        content_top_layout.setContentsMargins(0, 0, 0, 0)
        content_top_layout.setSpacing(8)
        identity = QWidget()
        self.content_identity_layout = QVBoxLayout(identity)
        self.content_identity_layout.setContentsMargins(0, 0, 0, 0)
        name_label = QLabel()
        name_label.setBuddy(self.name_field)
        self.content_identity_layout.addWidget(name_label)
        self.content_identity_layout.addWidget(self.name_field)
        diameter_label = QLabel()
        diameter_label.setBuddy(self.display_diameter_field)
        self.content_identity_layout.addWidget(diameter_label)
        self.content_identity_layout.addWidget(self.display_diameter_field)
        self.content_identity_layout.addStretch(1)
        self._labels["properties.name"] = name_label
        self._labels["properties.display_diameter"] = diameter_label
        text_column = QWidget()
        text_layout = QVBoxLayout(text_column)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_label = QLabel()
        text_label.setBuddy(self.text_field)
        text_layout.addWidget(text_label)
        text_layout.addWidget(self.text_field)
        self._labels["properties.text"] = text_label
        content_top_layout.addWidget(identity, 1)
        content_top_layout.addWidget(text_column, 1)
        self.content_layout.addWidget(content_top)
        color_label = QLabel()
        self.content_layout.addWidget(color_label)
        self._labels["properties.color_group"] = color_label
        self.color_palette = QWidget()
        palette_layout = QGridLayout(self.color_palette)
        palette_layout.setContentsMargins(0, 0, 0, 0)
        palette_layout.setSpacing(3)
        self.color_group_buttons: list[QToolButton] = []
        self.color_group_button_group = QButtonGroup(self)
        self.color_group_button_group.setExclusive(True)
        for index, color in enumerate(TEXT_COLOR_GROUPS):
            button = QToolButton()
            button.setCheckable(True)
            button.setFixedSize(QSize(22, 22))
            button.setStyleSheet(
                f"QToolButton {{ background: {color}; border: 1px solid #64748B; }} "
                "QToolButton:checked { border: 3px solid #F8FAFC; }"
            )
            button.setToolTip(f"{index + 1}: {color}")
            self.color_group_button_group.addButton(button, index)
            palette_layout.addWidget(button, index // 8, index % 8)
            self.color_group_buttons.append(button)
        self.content_layout.addWidget(self.color_palette)
        self.color_group_settings_button = QToolButton()
        self.color_group_settings_button.setEnabled(False)
        self.color_group_settings_button.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self.content_layout.addWidget(self.color_group_settings_button)
        layout.addWidget(content_group)
        self._groups["properties.group.content"] = content_group
        self._add_group(layout, "properties.group.position", [
            ("properties.text_start_x", self.x_field),
            ("properties.text_start_y", self.y_field),
        ])
        self._add_group(layout, "properties.group.frame", [
            ("properties.text_frame_x", self.frame_x_field),
            ("properties.text_frame_y", self.frame_y_field),
            ("properties.text_frame_width", self.frame_width_field),
            ("properties.text_frame_height", self.frame_height_field),
        ])
        self._typography_fields = [
            ("properties.x_height", self.x_height_field),
            ("properties.line_pitch", self.line_pitch_field),
            ("properties.character_spacing", self.character_spacing_field),
            ("properties.rotation", self.rotation_field),
        ]
        self.typography_group = self._add_group(
            layout, "properties.group.typography", self._typography_fields, columns=4
        )
        self._add_group(layout, "properties.group.style", [
            ("properties.style", self.style_field),
            ("properties.realism", self.realism_field),
            ("properties.seed", self.seed_field),
        ])
        layout.addStretch(1)
        self.name_field.editingFinished.connect(self._emit_text)
        self.text_field.textChanged.connect(self._emit_text_content)
        for field in (
            self.x_field, self.y_field, self.frame_x_field, self.frame_y_field,
            self.frame_width_field, self.frame_height_field, self.x_height_field,
            self.line_pitch_field, self.character_spacing_field, self.rotation_field,
            self.display_diameter_field, self.realism_field,
        ):
            field.valueChanged.connect(self._emit_text)
        self.seed_field.editingFinished.connect(self._emit_text)
        self.style_field.currentIndexChanged.connect(self._emit_text)
        self.color_group_button_group.idClicked.connect(self._set_color_group)
        return widget

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "typography_group"):
            self._reflow_typography(4 if event.size().width() >= 520 else 2)

    def _reflow_typography(self, columns: int) -> None:
        if getattr(self, "_typography_columns", None) == columns:
            return
        self._typography_columns = columns
        grid = self.typography_group.layout()
        for index, (key, field) in enumerate(self._typography_fields):
            label = self._labels[key]
            grid.removeWidget(label)
            grid.removeWidget(field)
            row = (index // columns) * 2
            column = index % columns
            grid.addWidget(label, row, column)
            grid.addWidget(field, row + 1, column)

    def _set_color_group(self, index: int) -> None:
        self._color_group = index
        self._emit_text()

    def _build_resource_widget(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        self.resource_name = QLabel()
        self.resource_reference = QLabel()
        self.resource_status = QLabel()
        self.resource_detail = QLabel()
        self.resource_detail.setWordWrap(True)
        self._add_row(form, "properties.style_pack", self.resource_name)
        self._add_row(form, "properties.reference", self.resource_reference)
        self._add_row(form, "properties.status", self.resource_status)
        self._add_row(form, "properties.validation", self.resource_detail)
        return widget

    def _build_grid_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.grid_name_field = QLineEdit()
        self.grid_x_field = _millimetre_spin(0, 209.9)
        self.grid_y_field = _millimetre_spin(0, 296.9)
        self.grid_width_field = _millimetre_spin(0.01, 210)
        self.grid_height_field = _millimetre_spin(0.01, 297)
        self.cell_width_field = _millimetre_spin(1, 210)
        self.cell_height_field = _millimetre_spin(1, 297)
        self.grid_line_style_field = QComboBox()
        for value in ("solid", "dashed", "dash_dot"):
            self.grid_line_style_field.addItem("", value)
        self.grid_color_field = QLineEdit()
        self.grid_color_field.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"#[0-9A-Fa-f]{6}"))
        )
        self.grid_snap_field = QCheckBox()
        self._add_group(layout, "properties.group.grid", [
            ("properties.name", self.grid_name_field),
            ("properties.grid_color", self.grid_color_field),
        ])
        self._add_group(layout, "properties.group.grid_geometry", [
            ("properties.frame_x", self.grid_x_field),
            ("properties.frame_y", self.grid_y_field),
            ("properties.frame_width", self.grid_width_field),
            ("properties.frame_height", self.grid_height_field),
        ])
        self._add_group(layout, "properties.group.cells", [
            ("properties.cell_width", self.cell_width_field),
            ("properties.cell_height", self.cell_height_field),
        ])
        self._add_group(layout, "properties.group.grid_lines", [
            ("properties.line_style", self.grid_line_style_field),
            ("properties.snap", self.grid_snap_field),
        ])
        layout.addStretch(1)
        self.grid_name_field.editingFinished.connect(self._emit_grid)
        self.grid_color_field.editingFinished.connect(self._emit_grid)
        for field in (
            self.grid_x_field, self.grid_y_field, self.grid_width_field,
            self.grid_height_field, self.cell_width_field, self.cell_height_field,
        ):
            field.valueChanged.connect(self._emit_grid)
        self.grid_line_style_field.currentIndexChanged.connect(self._emit_grid)
        self.grid_snap_field.toggled.connect(self._emit_grid)
        return widget

    def set_language(self, language: Language) -> None:
        self.language = normalize_language(language)
        self.empty_widget.setText(tr(self.language, "properties.empty"))
        self.page_format.setText(tr(self.language, "properties.a4"))
        for key, label in self._labels.items():
            label.setText(tr(self.language, key))
        for key, group in self._groups.items():
            group.setTitle(tr(self.language, key))
        for index, value in enumerate(("solid", "dashed", "dash_dot")):
            self.grid_line_style_field.setItemText(index, tr(self.language, f"properties.line_style.{value}"))
        self.color_group_settings_button.setText(tr(self.language, "properties.color_group_settings"))
        if self._shown_style is not None:
            self._show_style_status(self._shown_style)

    def show_page(self, page: PageSettings) -> None:
        self._loading = True
        self._object_id = None
        self._shown_style = None
        for name, field in self.page_fields.items():
            field.setValue(getattr(page, name))
        self._loading = False
        self.stack.setCurrentWidget(self.page_widget)

    def show_text_object(self, item: TextObject) -> None:
        self._loading = True
        self._object_id = item.object_id
        self._shown_style = None
        self.name_field.setText(item.name)
        self.text_field.setPlainText(item.text)
        self.x_field.setValue(item.x_mm - item.frame_x_mm)
        self.y_field.setValue(item.y_mm - item.frame_y_mm)
        self.frame_x_field.setValue(item.frame_x_mm)
        self.frame_y_field.setValue(item.frame_y_mm)
        self.frame_width_field.setValue(item.frame_width_mm)
        self.frame_height_field.setValue(item.frame_height_mm)
        self.x_height_field.setValue(item.x_height_mm)
        self.line_pitch_field.setValue(item.line_pitch_mm)
        self.character_spacing_field.setValue(item.character_spacing_mm)
        self.rotation_field.setValue(item.rotation_deg)
        self.display_diameter_field.setValue(item.display_diameter_mm)
        self._color_group = item.color_group
        self.color_group_buttons[item.color_group].setChecked(True)
        index = self.style_field.findData(f"{item.style_id}\0{item.style_revision}")
        if index < 0:
            self.style_field.addItem(
                f"Missing · {item.style_id}@{item.style_revision}",
                f"{item.style_id}\0{item.style_revision}",
            )
            index = self.style_field.count() - 1
        self.style_field.setCurrentIndex(index)
        self.seed_field.setText(str(item.seed))
        self.realism_field.setValue(item.realism)
        self._loading = False
        self.stack.setCurrentWidget(self.text_widget)

    def show_grid_object(self, item: GridObject) -> None:
        self._loading = True
        self._object_id = item.object_id
        self._shown_style = None
        self.grid_name_field.setText(item.name)
        self.grid_x_field.setValue(item.x_mm)
        self.grid_y_field.setValue(item.y_mm)
        self.grid_width_field.setValue(item.width_mm)
        self.grid_height_field.setValue(item.height_mm)
        self.cell_width_field.setValue(item.cell_width_mm)
        self.cell_height_field.setValue(item.cell_height_mm)
        self.grid_line_style_field.setCurrentIndex(self.grid_line_style_field.findData(item.line_style))
        self.grid_color_field.setText(item.color)
        self.grid_snap_field.setChecked(item.snap_enabled)
        self._loading = False
        self.stack.setCurrentWidget(self.grid_widget)

    def show_style(self, style: StyleSummary) -> None:
        self._object_id = None
        self._shown_style = style
        self.resource_name.setText(style.display_name)
        self.resource_reference.setText(f"{style.style_id}@{style.revision}")
        self._show_style_status(style)
        self.resource_detail.setText(style.detail)
        self.stack.setCurrentWidget(self.resource_widget)

    def set_styles(self, styles: tuple[StyleSummary, ...]) -> None:
        """Replace the verified catalog while preserving an explicit project reference."""
        current = self.style_field.currentData()
        self._styles = styles
        self.style_field.blockSignals(True)
        self.style_field.clear()
        for style in styles:
            if style.valid:
                self.style_field.addItem(
                    f"{style.display_name} · {style.revision}",
                    f"{style.style_id}\0{style.revision}",
                )
        index = self.style_field.findData(current)
        if index < 0 and isinstance(current, str) and "\0" in current:
            style_id, revision = current.split("\0", 1)
            self.style_field.addItem(f"Missing · {style_id}@{revision}", current)
            index = self.style_field.count() - 1
        if index >= 0:
            self.style_field.setCurrentIndex(index)
        self.style_field.blockSignals(False)

    def _show_style_status(self, style: StyleSummary) -> None:
        status_key = "properties.test_only" if style.test_only else "properties.production"
        status = tr(self.language, status_key)
        self.resource_status.setText(status if style.valid else tr(self.language, "properties.invalid"))

    def _emit_page(self) -> None:
        if self._loading:
            return
        self.page_changed.emit({name: field.value() for name, field in self.page_fields.items()})

    def _emit_text(self) -> None:
        payload = self._text_changes()
        if payload is not None:
            self.text_object_changed.emit(self._object_id, payload)

    def _emit_text_content(self) -> None:
        payload = self._text_changes()
        if payload is not None:
            self.text_content_changed.emit(self._object_id, payload)

    def _text_changes(self) -> dict | None:
        if self._loading or self._object_id is None or self.style_field.currentIndex() < 0:
            return None
        seed_text = self.seed_field.text()
        if not seed_text:
            return None
        style_id, revision = self.style_field.currentData().split("\0", 1)
        return {
            "name": self.name_field.text().strip() or "Text",
            "text": self.text_field.toPlainText(),
            "x_mm": self.frame_x_field.value() + self.x_field.value(),
            "y_mm": self.frame_y_field.value() + self.y_field.value(),
            "frame_x_mm": self.frame_x_field.value(),
            "frame_y_mm": self.frame_y_field.value(),
            "frame_width_mm": self.frame_width_field.value(),
            "frame_height_mm": self.frame_height_field.value(),
            "x_height_mm": self.x_height_field.value(),
            "line_pitch_mm": self.line_pitch_field.value(),
            "character_spacing_mm": self.character_spacing_field.value(),
            "rotation_deg": self.rotation_field.value(),
            "display_diameter_mm": self.display_diameter_field.value(),
            "color_group": self._color_group,
            "style_id": style_id,
            "style_revision": revision,
            "seed": int(seed_text),
            "realism": self.realism_field.value(),
        }

    def _emit_grid(self) -> None:
        if self._loading or self._object_id is None or not self.grid_color_field.hasAcceptableInput():
            return
        self.grid_object_changed.emit(self._object_id, {
            "name": self.grid_name_field.text().strip() or "Grid",
            "x_mm": self.grid_x_field.value(),
            "y_mm": self.grid_y_field.value(),
            "width_mm": self.grid_width_field.value(),
            "height_mm": self.grid_height_field.value(),
            "cell_width_mm": self.cell_width_field.value(),
            "cell_height_mm": self.cell_height_field.value(),
            "line_style": self.grid_line_style_field.currentData(),
            "color": self.grid_color_field.text().upper(),
            "snap_enabled": self.grid_snap_field.isChecked(),
        })
