"""Main desktop workspace."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog, QDockWidget, QHBoxLayout, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .canvas import PageCanvas
from .document import DocumentController, ProjectSnapshot, default_project, load_project, save_project
from .properties import PropertiesPanel
from .styles import discover_styles


ROLE_KIND = int(Qt.ItemDataRole.UserRole)
ROLE_VALUE = ROLE_KIND + 1


class MainWindow(QMainWindow):
    """Dockable engineering workspace backed by an undoable project model."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("main-window")
        self.resize(1440, 900)
        self.setDockNestingEnabled(True)
        self.styles = discover_styles()
        self.controller = DocumentController(default_project(), self)
        self._selected_kind = "page"
        self._selected_value: object = None
        self._refreshing_tree = False
        self._build_canvas()
        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._connect_model()
        self._refresh_tree(self.controller.snapshot)
        self.properties.show_page(self.controller.snapshot.page)
        self._update_title()
        self.statusBar().showMessage("Ready")

    def _build_canvas(self) -> None:
        self.canvas = PageCanvas(self)
        self.setCentralWidget(self.canvas)

    def _build_docks(self) -> None:
        project_panel = QWidget()
        project_layout = QVBoxLayout(project_panel)
        project_layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.add_text_button = QPushButton("+ Text")
        self.remove_text_button = QPushButton("Remove")
        controls.addWidget(self.add_text_button)
        controls.addWidget(self.remove_text_button)
        project_layout.addLayout(controls)
        self.project_tree = QTreeWidget()
        self.project_tree.setObjectName("project-explorer")
        self.project_tree.setHeaderHidden(True)
        self.project_tree.setAlternatingRowColors(True)
        project_layout.addWidget(self.project_tree)
        self.project_dock = self._dock("Project Explorer", "project-dock", project_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.project_dock)

        self.properties = PropertiesPanel(self.styles)
        self.properties_dock = self._dock("Properties", "properties-dock", self.properties)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.properties_dock)

        self.console = self._read_only_log("Application events will appear here.")
        self.diagnostics = self._read_only_log("No diagnostics.")
        self.toolpath = self._read_only_log("Generate a document to inspect its toolpath.")
        self.output_tabs = QTabWidget()
        self.output_tabs.setObjectName("output-tabs")
        self.output_tabs.addTab(self.console, "Console")
        self.output_tabs.addTab(self.diagnostics, "Diagnostics")
        self.output_tabs.addTab(self.toolpath, "Toolpath")
        self.output_dock = self._dock("Output", "output-dock", self.output_tabs)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)
        self.resizeDocks([self.project_dock, self.properties_dock], [275, 340], Qt.Orientation.Horizontal)
        self.resizeDocks([self.output_dock], [200], Qt.Orientation.Vertical)

    def _build_actions(self) -> None:
        self.new_action = self._action("&New Project", self.new_project, QKeySequence.StandardKey.New)
        self.open_action = self._action("&Open…", self.open_project, QKeySequence.StandardKey.Open)
        self.save_action = self._action("&Save", self.save_project, QKeySequence.StandardKey.Save)
        self.save_as_action = self._action("Save &As…", self.save_project_as, QKeySequence.StandardKey.SaveAs)
        self.exit_action = self._action("E&xit", self.close, QKeySequence.StandardKey.Quit)
        self.undo_action = self.controller.undo_stack.createUndoAction(self, "&Undo")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action = self.controller.undo_stack.createRedoAction(self, "&Redo")
        self.redo_action.setShortcuts([QKeySequence.StandardKey.Redo, QKeySequence("Ctrl+Shift+Z")])
        self.add_text_action = self._action("Add &Text Object", self.add_text_object, QKeySequence("Insert"))
        self.delete_action = self._action("&Delete Object", self.remove_selected_object, QKeySequence.StandardKey.Delete)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([self.new_action, self.open_action, self.save_action, self.save_as_action])
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)
        edit = self.menuBar().addMenu("&Edit")
        edit.addActions([self.undo_action, self.redo_action])
        edit.addSeparator()
        edit.addActions([self.add_text_action, self.delete_action])
        view = self.menuBar().addMenu("&View")
        for dock in (self.project_dock, self.properties_dock, self.output_dock):
            view.addAction(dock.toggleViewAction())
        self.tools_menu = self.menuBar().addMenu("&Tools")
        self.machine_menu = self.menuBar().addMenu("&Machine")
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self._action("&About", self._about))

    def _build_toolbar(self) -> None:
        toolbar = self.addToolBar("Workspace")
        toolbar.setObjectName("workspace-toolbar")
        toolbar.addActions([self.new_action, self.open_action, self.save_action])
        toolbar.addSeparator()
        toolbar.addActions([self.add_text_action, self.delete_action])
        toolbar.addSeparator()
        toolbar.addAction(self._action("Fit Page", self.canvas.zoom_to_fit, "F"))
        travel = self._action("Travel", self.canvas.set_show_travel)
        travel.setCheckable(True)
        toolbar.addAction(travel)
        markers = self._action("Start / End", self.canvas.set_show_markers)
        markers.setCheckable(True)
        toolbar.addAction(markers)

    def _connect_model(self) -> None:
        self.controller.snapshot_changed.connect(self._on_snapshot_changed)
        self.controller.dirty_changed.connect(lambda _: self._update_title())
        self.controller.path_changed.connect(lambda _: self._update_title())
        self.project_tree.currentItemChanged.connect(self._on_selection_changed)
        self.project_tree.itemChanged.connect(self._on_tree_item_changed)
        self.properties.text_object_changed.connect(self._update_text_object)
        self.properties.page_changed.connect(self._update_page)
        self.add_text_button.clicked.connect(self.add_text_object)
        self.remove_text_button.clicked.connect(self.remove_selected_object)

    def _dock(self, title: str, name: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable |
                         QDockWidget.DockWidgetFeature.DockWidgetMovable |
                         QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setWidget(widget)
        return dock

    def _read_only_log(self, initial: str) -> QPlainTextEdit:
        widget = QPlainTextEdit(initial)
        widget.setReadOnly(True)
        widget.setMaximumBlockCount(2000)
        return widget

    def _refresh_tree(self, snapshot: ProjectSnapshot) -> None:
        selected = (self._selected_kind, self._selected_value)
        self._refreshing_tree = True
        self.project_tree.clear()
        project = QTreeWidgetItem([snapshot.name])
        project.setData(0, ROLE_KIND, "project")
        document = QTreeWidgetItem(["Document"])
        page = QTreeWidgetItem(["Page 1 · A4"])
        page.setData(0, ROLE_KIND, "page")
        document.addChild(page)
        project.addChild(document)
        for item in snapshot.objects:
            node = QTreeWidgetItem([item.name])
            node.setData(0, ROLE_KIND, "text")
            node.setData(0, ROLE_VALUE, item.object_id)
            node.setFlags(node.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
            node.setCheckState(0, Qt.CheckState.Checked if item.visible else Qt.CheckState.Unchecked)
            document.addChild(node)
        resources = QTreeWidgetItem(["Style Packs"])
        resources.setData(0, ROLE_KIND, "styles")
        for style in self.styles:
            state = "✓" if style.valid else "!"
            node = QTreeWidgetItem([f"{state} {style.style_id} · {style.revision}"])
            node.setData(0, ROLE_KIND, "style")
            node.setData(0, ROLE_VALUE, style.reference)
            resources.addChild(node)
        self.project_tree.addTopLevelItems([project, resources])
        self.project_tree.expandAll()
        self.project_tree.setCurrentItem(self._find_tree_item(*selected) or page)
        self._refreshing_tree = False

    def _find_tree_item(self, kind: str, value: object) -> QTreeWidgetItem | None:
        root = self.project_tree.invisibleRootItem()
        pending = [root.child(i) for i in range(root.childCount())]
        while pending:
            item = pending.pop(0)
            if item.data(0, ROLE_KIND) == kind and item.data(0, ROLE_VALUE) == value:
                return item
            pending.extend(item.child(i) for i in range(item.childCount()))
        return None

    def _on_snapshot_changed(self, snapshot: ProjectSnapshot, revision: int) -> None:
        self._refresh_tree(snapshot)
        page = snapshot.page
        self.canvas.set_margins(page.margin_left_mm, page.margin_top_mm, page.margin_right_mm, page.margin_bottom_mm)
        self._show_selected_properties()
        self._update_title()
        self.statusBar().showMessage(f"Project changed · revision {revision}", 2500)

    def _on_selection_changed(self, current: QTreeWidgetItem | None, previous=None) -> None:  # noqa: ANN001
        if current is None:
            return
        self._selected_kind = current.data(0, ROLE_KIND) or "project"
        self._selected_value = current.data(0, ROLE_VALUE)
        self._show_selected_properties()
        enabled = self._selected_kind == "text"
        self.delete_action.setEnabled(enabled)
        self.remove_text_button.setEnabled(enabled)

    def _show_selected_properties(self) -> None:
        if self._selected_kind == "page":
            self.properties.show_page(self.controller.snapshot.page)
        elif self._selected_kind == "text":
            item = next((obj for obj in self.controller.snapshot.objects if obj.object_id == self._selected_value), None)
            if item:
                self.properties.show_text_object(item)
        elif self._selected_kind == "style":
            style = next((obj for obj in self.styles if obj.reference == self._selected_value), None)
            if style:
                self.properties.show_style(style)

    def _on_tree_item_changed(self, node: QTreeWidgetItem, column: int) -> None:
        if self._refreshing_tree or node.data(0, ROLE_KIND) != "text":
            return
        self.controller.update_text_object(node.data(0, ROLE_VALUE), name=node.text(0).strip() or "Text",
                                           visible=node.checkState(0) == Qt.CheckState.Checked)

    def _update_text_object(self, object_id: str, changes: dict) -> None:
        try:
            self.controller.update_text_object(object_id, **changes)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc), 5000)

    def _update_page(self, changes: dict) -> None:
        try:
            self.controller.update_page(**changes)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc), 5000)

    def add_text_object(self) -> None:
        item = self.controller.add_text_object()
        self._selected_kind, self._selected_value = "text", item.object_id
        self._refresh_tree(self.controller.snapshot)

    def remove_selected_object(self) -> None:
        if self._selected_kind != "text" or not isinstance(self._selected_value, str):
            return
        self.controller.remove_text_object(self._selected_value)
        self._selected_kind, self._selected_value = "page", None

    def new_project(self) -> None:
        self.controller.reset(default_project())
        self.canvas.clear_artifacts()
        self.console.setPlainText("New project created.")

    def open_project(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Open Handwriting Plotter Project", "", "Plotter Project (*.hplot.json)")
        if not filename:
            return
        try:
            self.controller.reset(load_project(Path(filename)), Path(filename))
            self.canvas.clear_artifacts()
            self.console.setPlainText(f"Opened {filename}")
        except Exception as exc:
            QMessageBox.critical(self, "Could not open project", str(exc))

    def save_project(self) -> None:
        if self.controller.path is None:
            self.save_project_as()
        else:
            self._write_project(self.controller.path)

    def save_project_as(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "Save Handwriting Plotter Project", "project.hplot.json", "Plotter Project (*.hplot.json)")
        if not filename:
            return
        path = Path(filename)
        if not path.name.endswith(".hplot.json"):
            path = path.with_name(path.name + ".hplot.json")
        self._write_project(path)

    def _write_project(self, path: Path) -> None:
        try:
            save_project(path, self.controller.snapshot)
            self.controller.mark_saved(path)
            self.statusBar().showMessage(f"Saved {path}", 4000)
        except Exception as exc:
            QMessageBox.critical(self, "Could not save project", str(exc))

    def _update_title(self) -> None:
        name = self.controller.path.name if self.controller.path else self.controller.snapshot.name
        self.setWindowTitle(f"{name}{' *' if self.controller.dirty else ''} — Handwriting Plotter")

    def _action(self, text: str, callback, shortcut=None) -> QAction:  # noqa: ANN001
        action = QAction(text, self)
        action.triggered.connect(callback)
        if shortcut is not None:
            action.setShortcut(shortcut)
        return action

    def _about(self) -> None:
        QMessageBox.about(self, "About Handwriting Plotter",
                          "Handwriting Plotter\n\nDeterministic single-line handwriting and virtual plotter planning.")
