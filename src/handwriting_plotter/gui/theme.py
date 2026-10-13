"""Centralized desktop visual system."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


COLORS = {
    "window": "#17191d",
    "panel": "#202329",
    "panel_alt": "#262a31",
    "border": "#343943",
    "text": "#e6e9ef",
    "muted": "#9aa3b2",
    "accent": "#4b8df8",
    "accent_hover": "#64a0ff",
    "danger": "#ef6b73",
    "warning": "#e6b85c",
    "paper": "#f8f8f6",
}


STYLESHEET = f"""
QWidget {{
    color: {COLORS['text']};
    background-color: {COLORS['window']};
    font-size: 10pt;
}}
QMainWindow, QMenuBar, QMenu, QStatusBar {{
    background-color: {COLORS['window']};
}}
QMenuBar::item {{ padding: 5px 9px; background: transparent; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {COLORS['panel_alt']}; }}
QMenu {{ border: 1px solid {COLORS['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 26px 6px 10px; }}
QToolBar {{
    background: {COLORS['panel']};
    border: 0;
    border-bottom: 1px solid {COLORS['border']};
    spacing: 4px;
    padding: 4px;
}}
QToolButton {{ border: 0; border-radius: 4px; padding: 5px; }}
QToolButton:hover {{ background: {COLORS['panel_alt']}; }}
QDockWidget {{ color: {COLORS['muted']}; font-weight: 600; }}
QDockWidget::title {{
    background: {COLORS['panel']};
    border-bottom: 1px solid {COLORS['border']};
    padding: 7px 9px;
}}
QTreeWidget, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget {{
    background: {COLORS['panel']};
    border: 0;
    selection-background-color: #294f86;
    alternate-background-color: {COLORS['panel_alt']};
}}
QHeaderView::section {{
    background: {COLORS['panel_alt']};
    border: 0;
    border-right: 1px solid {COLORS['border']};
    padding: 5px;
}}
QTabWidget::pane {{ border: 0; border-top: 1px solid {COLORS['border']}; }}
QTabBar::tab {{
    background: {COLORS['panel']};
    color: {COLORS['muted']};
    padding: 7px 13px;
    border: 0;
}}
QTabBar::tab:selected {{ color: {COLORS['text']}; border-bottom: 2px solid {COLORS['accent']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {COLORS['panel_alt']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    padding: 5px 7px;
    min-height: 20px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {COLORS['accent']}; }}
QPushButton {{
    background: {COLORS['panel_alt']};
    border: 1px solid {COLORS['border']};
    border-radius: 4px;
    padding: 6px 12px;
}}
QPushButton:hover {{ border-color: {COLORS['accent_hover']}; }}
QPushButton:pressed {{ background: #1d3d69; }}
QPushButton:disabled {{ color: #676e79; }}
QSplitter::handle {{ background: {COLORS['border']}; }}
QScrollBar:vertical {{ width: 11px; background: {COLORS['panel']}; }}
QScrollBar::handle:vertical {{ background: #4a515e; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QStatusBar {{ color: {COLORS['muted']}; border-top: 1px solid {COLORS['border']}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["window"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["panel"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["panel_alt"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["panel_alt"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
