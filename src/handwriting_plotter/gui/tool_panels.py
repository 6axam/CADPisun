"""Compact action panels that reflow inside dock widgets."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QAction, QResizeEvent
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QToolButton, QWidget
from shiboken6 import isValid


class ResponsiveActionPanel(QWidget):
    """Lay out square action buttons in as many columns as currently fit."""

    BUTTON_SIZE = 38
    SPACING = 5

    def __init__(self, specifications: tuple[tuple[str, QAction, str], ...], parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(self.SPACING)
        self.buttons = tuple(
            self._symbol_button(symbol, action, object_name)
            for symbol, action, object_name in specifications
        )
        self.column_count = 0
        self._reflow(self.sizeHint().width())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        extent = self.BUTTON_SIZE + 12
        return QSize(extent, extent)

    def sizeHint(self) -> QSize:  # noqa: N802
        columns = min(5, max(1, len(self.buttons))) if hasattr(self, "buttons") else 5
        rows = max(1, (len(self.buttons) + columns - 1) // columns) if hasattr(self, "buttons") else 1
        return QSize(
            columns * self.BUTTON_SIZE + (columns - 1) * self.SPACING + 12,
            rows * self.BUTTON_SIZE + (rows - 1) * self.SPACING + 12,
        )

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reflow(event.size().width())

    def _reflow(self, width: int) -> None:
        usable = max(1, width - self._layout.contentsMargins().left() - self._layout.contentsMargins().right())
        columns = max(1, min(len(self.buttons), (usable + self.SPACING) // (self.BUTTON_SIZE + self.SPACING)))
        if columns == self.column_count:
            return
        self.column_count = columns
        while self._layout.count():
            self._layout.takeAt(0)
        for index, button in enumerate(self.buttons):
            self._layout.addWidget(button, index // columns, index % columns)
        self._layout.setColumnStretch(columns, 1)

    @staticmethod
    def _symbol_button(symbol: str, action: QAction, object_name: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName(object_name)
        button.setText(symbol)
        button.setFixedSize(ResponsiveActionPanel.BUTTON_SIZE, ResponsiveActionPanel.BUTTON_SIZE)
        button.setCheckable(action.isCheckable())
        button.setStyleSheet(
            "QToolButton { border: 1px solid #343943; border-radius: 6px; "
            "background: #262A31; font-size: 16px; font-weight: 600; padding: 0; }"
            "QToolButton:hover { border-color: #64A0FF; background: #303640; }"
            "QToolButton:checked { border-color: #4B8DF8; background: #294F86; }"
            "QToolButton:disabled { color: #676E79; background: #202329; }"
        )

        def sync_action() -> None:
            # The action belongs to the main window while the button belongs to a
            # dock.  Qt may queue ``changed`` while either owner is being torn
            # down, so guard the Python wrappers before touching the C++ objects.
            if not isValid(action) or not isValid(button):
                return
            label = action.text().replace("&", "")
            button.setAccessibleName(label)
            button.setToolTip(action.toolTip() or label)
            button.setEnabled(action.isEnabled())
            button.setChecked(action.isChecked())

        button.clicked.connect(lambda _checked=False: action.trigger())
        action.changed.connect(sync_action)
        sync_action()
        return button
