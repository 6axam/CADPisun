"""Editor for portable notebook paper templates."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .notebook_templates import NotebookPageTemplate


def _millimetres(minimum: float, maximum: float, value: float) -> QDoubleSpinBox:
    field = QDoubleSpinBox()
    field.setDecimals(2)
    field.setSingleStep(0.5)
    field.setRange(minimum, maximum)
    field.setSuffix(" mm")
    field.setValue(value)
    return field


class NotebookTemplateDialog(QDialog):
    """Compact control surface for A4 blank, squared and ruled backgrounds."""

    def __init__(self, template: NotebookPageTemplate | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("notebook-template-dialog")
        self.setWindowTitle("Notebook page template")
        current = template or NotebookPageTemplate()
        form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem("Blank", "blank")
        self.kind.addItem("Squared", "squared")
        self.kind.addItem("Ruled", "ruled")
        self.kind.setCurrentIndex(self.kind.findData(current.kind))
        self.orientation = QComboBox()
        self.orientation.addItem("Portrait · 210 × 297 mm", "portrait")
        self.orientation.addItem("Landscape · 297 × 210 mm", "landscape")
        self.orientation.setCurrentIndex(self.orientation.findData(current.orientation))
        self.margin_left = _millimetres(0, 100, current.margin_left_mm)
        self.margin_right = _millimetres(0, 100, current.margin_right_mm)
        self.margin_top = _millimetres(0, 100, current.margin_top_mm)
        self.margin_bottom = _millimetres(0, 100, current.margin_bottom_mm)
        self.pitch_x = _millimetres(0.1, 50, current.pitch_x_mm)
        self.pitch_y = _millimetres(0.1, 50, current.pitch_y_mm)
        self.offset_x = _millimetres(-100, 100, current.offset_x_mm)
        self.offset_y = _millimetres(-100, 100, current.offset_y_mm)
        self.line_color = QLineEdit(current.line_color.upper())
        self.line_color.setPlaceholderText("#RRGGBB")
        self.line_width = _millimetres(0.01, 2, current.line_width_mm)
        self.major_every = QSpinBox()
        self.major_every.setRange(1, 50)
        self.major_every.setValue(current.major_every)
        self.major_color = QLineEdit(current.major_line_color.upper())
        self.major_color.setPlaceholderText("#RRGGBB")
        self.major_width = _millimetres(0.01, 2, current.major_line_width_mm)
        form.addRow("Paper", self.kind)
        form.addRow("A4 orientation", self.orientation)
        form.addRow("Left / right margin", self._pair(self.margin_left, self.margin_right))
        form.addRow("Top / bottom margin", self._pair(self.margin_top, self.margin_bottom))
        form.addRow("Vertical / horizontal pitch", self._pair(self.pitch_x, self.pitch_y))
        form.addRow("Grid X / Y offset", self._pair(self.offset_x, self.offset_y))
        form.addRow("Line color", self.line_color)
        form.addRow("Line thickness", self.line_width)
        form.addRow("Major division every", self.major_every)
        form.addRow("Major line color", self.major_color)
        form.addRow("Major line thickness", self.major_width)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @staticmethod
    def _pair(first: QWidget, second: QWidget) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(first)
        layout.addWidget(second)
        return holder

    def value(self) -> NotebookPageTemplate:
        return NotebookPageTemplate(
            kind=self.kind.currentData(), orientation=self.orientation.currentData(),
            margin_left_mm=self.margin_left.value(), margin_right_mm=self.margin_right.value(),
            margin_top_mm=self.margin_top.value(), margin_bottom_mm=self.margin_bottom.value(),
            pitch_x_mm=self.pitch_x.value(), pitch_y_mm=self.pitch_y.value(),
            offset_x_mm=self.offset_x.value(), offset_y_mm=self.offset_y.value(),
            line_color=self.line_color.text().strip().upper(), line_width_mm=self.line_width.value(),
            major_every=self.major_every.value(), major_line_color=self.major_color.text().strip().upper(),
            major_line_width_mm=self.major_width.value(),
        )
