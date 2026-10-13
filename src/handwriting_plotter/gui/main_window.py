"""Main desktop workspace shell."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFormLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from .canvas import PageCanvas


class MainWindow(QMainWindow):
    """Dockable engineering workspace; functional surfaces are added by stages."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("main-window")
        self.setWindowTitle("Handwriting Plotter")
        self.resize(1440, 900)
        self.setDockNestingEnabled(True)
        self._build_canvas()
        self._build_docks()
        self._build_menus()
        self._build_toolbar()
        self.statusBar().showMessage("Ready")

    def _build_canvas(self) -> None:
        self.canvas = PageCanvas(self)
        self.setCentralWidget(self.canvas)

    def _build_docks(self) -> None:
        self.project_tree = QTreeWidget()
        self.project_tree.setObjectName("project-explorer")
        self.project_tree.setHeaderHidden(True)
        project = QTreeWidgetItem(["Project"])
        document = QTreeWidgetItem(["Document"])
        page = QTreeWidgetItem(["Page 1"])
        project.addChild(document)
        document.addChild(page)
        self.project_tree.addTopLevelItem(project)
        self.project_tree.expandAll()
        self.project_dock = self._dock("Project Explorer", "project-dock", self.project_tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.project_dock)

        properties = QWidget()
        properties.setObjectName("properties-panel")
        form = QFormLayout(properties)
        form.setContentsMargins(10, 10, 10, 10)
        form.addRow("Selection", QLabel("Page 1"))
        form.addRow("Format", QLabel("A4 · 210 × 297 mm"))
        self.properties_dock = self._dock("Properties", "properties-dock", properties)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.properties_dock)

        self.console = self._read_only_log("Application events will appear here.")
        self.diagnostics = self._read_only_log("No diagnostics.")
        self.toolpath = self._read_only_log("Generate a document to inspect its toolpath.")
        tabs = QTabWidget()
        tabs.setObjectName("output-tabs")
        tabs.addTab(self.console, "Console")
        tabs.addTab(self.diagnostics, "Diagnostics")
        tabs.addTab(self.toolpath, "Toolpath")
        self.output_dock = self._dock("Output", "output-dock", tabs)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)
        self.resizeDocks([self.project_dock, self.properties_dock], [250, 300], Qt.Orientation.Horizontal)
        self.resizeDocks([self.output_dock], [220], Qt.Orientation.Vertical)

    def _dock(self, title: str, name: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock.setWidget(widget)
        return dock

    def _read_only_log(self, initial: str) -> QPlainTextEdit:
        widget = QPlainTextEdit(initial)
        widget.setReadOnly(True)
        widget.setMaximumBlockCount(2000)
        return widget

    def _build_menus(self) -> None:
        self.menuBar().addMenu("&File").addAction(self._action("E&xit", self.close, QKeySequence.StandardKey.Quit))
        self.menuBar().addMenu("&Edit")
        view = self.menuBar().addMenu("&View")
        for dock in (self.project_dock, self.properties_dock, self.output_dock):
            view.addAction(dock.toggleViewAction())
        self.menuBar().addMenu("&Tools")
        self.menuBar().addMenu("&Machine")
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self._action("&About", self._about))

    def _build_toolbar(self) -> None:
        toolbar = self.addToolBar("Canvas")
        toolbar.setObjectName("canvas-toolbar")
        toolbar.addAction(self._action("Fit Page", self.canvas.zoom_to_fit, "F"))
        toolbar.addSeparator()
        travel = self._action("Travel", self.canvas.set_show_travel)
        travel.setCheckable(True)
        toolbar.addAction(travel)
        markers = self._action("Start / End", self.canvas.set_show_markers)
        markers.setCheckable(True)
        toolbar.addAction(markers)

    def _action(self, text: str, callback, shortcut=None) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(callback)
        if shortcut is not None:
            action.setShortcut(shortcut)
        return action

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "About Handwriting Plotter",
            "Handwriting Plotter\n\nDeterministic single-line handwriting and virtual plotter planning.",
        )
