"""Small desktop dialogs for controls, settings, and release identity."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QKeySequenceEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True, slots=True)
class ShortcutBinding:
    identifier: str
    label: str
    action: QAction
    default: str


class ControlsDialog(QDialog):
    """Show discoverable action shortcuts and canvas gestures."""

    def __init__(self, bindings: tuple[ShortcutBinding, ...], *, language: str, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        uk = language == "uk"
        self.setObjectName("controls-dialog")
        self.setWindowTitle("Керування" if uk else "Controls")
        self.resize(620, 540)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Комбінації відображають поточні налаштування програми."
            if uk else "Shortcuts below reflect the current program settings."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.table = QTableWidget(len(bindings), 2)
        self.table.setObjectName("controls-shortcuts")
        self.table.setHorizontalHeaderLabels(("Дія", "Клавіші") if uk else ("Action", "Shortcut"))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, binding in enumerate(bindings):
            self.table.setItem(row, 0, QTableWidgetItem(binding.label.replace("&", "")))
            shortcuts = ", ".join(
                sequence.toString(QKeySequence.SequenceFormat.NativeText)
                for sequence in binding.action.shortcuts()
            )
            self.table.setItem(row, 1, QTableWidgetItem(shortcuts or "—"))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table, 1)
        gestures = QLabel(
            (
                "Полотно: колесо — прокрутка; Ctrl+колесо — масштаб; "
                "Space+перетягування — панорама; клік — вибір; Ctrl+клік — додати/зняти; "
                "рамка зліва направо — повне охоплення, справа наліво — перетин."
            ) if uk else (
                "Canvas: wheel scrolls; Ctrl+wheel zooms; Space+drag pans; click selects; "
                "Ctrl+click adds/removes; left-to-right box contains, right-to-left box crosses."
            )
        )
        gestures.setObjectName("controls-gestures")
        gestures.setWordWrap(True)
        layout.addWidget(gestures)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ProgramSettingsDialog(QDialog):
    """Edit basic UI preferences and persistent keyboard shortcuts."""

    def __init__(
        self,
        bindings: tuple[ShortcutBinding, ...],
        *,
        language: str,
        parent=None,  # noqa: ANN001
    ) -> None:
        super().__init__(parent)
        self._bindings = bindings
        self._uk = language == "uk"
        self.reset_layout_requested = False
        self.setObjectName("program-settings-dialog")
        self.setWindowTitle("Налаштування програми" if self._uk else "Program Settings")
        self.resize(610, 620)
        layout = QVBoxLayout(self)

        interface_group = QGroupBox("Інтерфейс" if self._uk else "Interface")
        interface_form = QFormLayout(interface_group)
        self.language_combo = QComboBox()
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("Українська", "uk")
        self.language_combo.setCurrentIndex(self.language_combo.findData(language))
        interface_form.addRow("Мова" if self._uk else "Language", self.language_combo)
        self.reset_layout_button = QPushButton(
            "Скинути компонування вікна" if self._uk else "Reset window layout"
        )
        self.reset_layout_button.clicked.connect(self._request_layout_reset)
        interface_form.addRow(self.reset_layout_button)
        layout.addWidget(interface_group)

        shortcuts_group = QGroupBox("Комбінації клавіш" if self._uk else "Keyboard shortcuts")
        shortcuts_outer = QVBoxLayout(shortcuts_group)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        self.shortcut_edits: dict[str, QKeySequenceEdit] = {}
        for binding in bindings:
            edit = QKeySequenceEdit(binding.action.shortcut())
            edit.setObjectName(f"shortcut-{binding.identifier}")
            form.addRow(binding.label.replace("&", ""), edit)
            self.shortcut_edits[binding.identifier] = edit
        scroll.setWidget(content)
        shortcuts_outer.addWidget(scroll)
        reset_shortcuts = QPushButton(
            "Типові комбінації" if self._uk else "Restore default shortcuts"
        )
        reset_shortcuts.clicked.connect(self._restore_defaults)
        shortcuts_outer.addWidget(reset_shortcuts)
        layout.addWidget(shortcuts_group, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selected_language(self) -> str:
        return str(self.language_combo.currentData())

    def shortcut_values(self) -> dict[str, QKeySequence]:
        return {key: edit.keySequence() for key, edit in self.shortcut_edits.items()}

    def _request_layout_reset(self) -> None:
        self.reset_layout_requested = True
        self.reset_layout_button.setText(
            "Компонування буде скинуто" if self._uk else "Window layout will be reset"
        )
        self.reset_layout_button.setEnabled(False)

    def _restore_defaults(self) -> None:
        for binding in self._bindings:
            self.shortcut_edits[binding.identifier].setKeySequence(QKeySequence(binding.default))
