"""Main desktop workspace."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QThreadPool, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QDockWidget, QHBoxLayout, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .canvas import PageCanvas
from .backend import GuiBackend
from .document import DocumentController, ProjectSnapshot, default_project, load_project, save_project
from .exporting import export_artifact
from .properties import PropertiesPanel
from .styles import discover_styles
from .workers import GenerationWorker


ROLE_KIND = int(Qt.ItemDataRole.UserRole)
ROLE_VALUE = ROLE_KIND + 1


class MainWindow(QMainWindow):
    """Dockable engineering workspace backed by an undoable project model."""

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.setObjectName("main-window")
        self.resize(1440, 900)
        self.setDockNestingEnabled(True)
        self.styles = discover_styles()
        self.settings = settings or QSettings("Handwriting Plotter", "Handwriting Plotter")
        self.controller = DocumentController(default_project(), self)
        self.backend = GuiBackend()
        self.thread_pool = QThreadPool.globalInstance()
        self.generated_result = None
        self.generated_revision: int | None = None
        self._generation_worker: GenerationWorker | None = None
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
        self._restore_window_state()
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
        self.generate_action = self._action("&Generate Page", self.generate_page, QKeySequence("Ctrl+Return"))
        self.export_svg_action = self._action("Production SVG…", lambda: self._export("page-0001.svg"))
        self.export_preview_action = self._action("Diagnostic SVG…", lambda: self._export("page-0001.preview.svg"))
        self.export_gcode_action = self._action("Virtual G-code (simulation only)…", lambda: self._export("page-0001.gcode"))
        self.export_report_action = self._action("Validation Report…", lambda: self._export("report.json"))
        self.export_actions = (
            self.export_svg_action, self.export_preview_action, self.export_gcode_action, self.export_report_action,
        )
        self._update_export_actions()

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([self.new_action, self.open_action, self.save_action, self.save_as_action])
        export_menu = file_menu.addMenu("&Export")
        export_menu.addActions(self.export_actions)
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
        self.tools_menu.addAction(self.generate_action)
        self.machine_menu = self.menuBar().addMenu("&Machine")
        self.machine_menu.addAction(self._action("Virtual Profile Information…", self._virtual_profile_info))
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self._action("&About", self._about))

    def _build_toolbar(self) -> None:
        toolbar = self.addToolBar("Workspace")
        toolbar.setObjectName("workspace-toolbar")
        toolbar.addActions([self.new_action, self.open_action, self.save_action])
        toolbar.addSeparator()
        toolbar.addActions([self.add_text_action, self.delete_action])
        toolbar.addSeparator()
        toolbar.addAction(self.generate_action)
        toolbar.addSeparator()
        toolbar.addAction(self._action("Fit Page", self.canvas.zoom_to_fit, "F"))
        self.travel_action = self._action("Travel", self.canvas.set_show_travel)
        self.travel_action.setCheckable(True)
        toolbar.addAction(self.travel_action)
        self.markers_action = self._action("Start / End", self.canvas.set_show_markers)
        self.markers_action.setCheckable(True)
        toolbar.addAction(self.markers_action)

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
        focus = QApplication.focusWidget()
        if focus is None or not self.properties.isAncestorOf(focus):
            self._show_selected_properties()
        self._update_title()
        if self.generated_revision is not None and self.generated_revision != revision:
            self._update_export_actions()
            self.statusBar().showMessage("Project changed · generated preview is stale", 4000)
            return
        self.statusBar().showMessage(f"Project changed · revision {revision}", 2500)

    def _on_selection_changed(self, current: QTreeWidgetItem | None, previous=None) -> None:  # noqa: ANN001
        if current is None or self._refreshing_tree:
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
        self.generated_result = None
        self.generated_revision = None
        self._update_export_actions()
        self.console.setPlainText("New project created.")

    def open_project(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Open Handwriting Plotter Project", "", "Plotter Project (*.hplot.json)")
        if not filename:
            return
        try:
            self.controller.reset(load_project(Path(filename)), Path(filename))
            self.canvas.clear_artifacts()
            self.generated_result = None
            self.generated_revision = None
            self._update_export_actions()
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

    def generate_page(self) -> None:
        if self._generation_worker is not None:
            return
        revision = self.controller.revision
        worker = GenerationWorker(self.backend, self.controller.snapshot, revision)
        worker.signals.succeeded.connect(self._generation_succeeded)
        worker.signals.failed.connect(self._generation_failed)
        self._generation_worker = worker
        self.generate_action.setEnabled(False)
        self.statusBar().showMessage("Generating page…")
        self.console.setPlainText(f"Generation started for revision {revision}.")
        self.thread_pool.start(worker)

    def _generation_succeeded(self, revision: int, result) -> None:  # noqa: ANN001
        self._generation_worker = None
        self.generate_action.setEnabled(True)
        if revision != self.controller.revision:
            self.console.appendPlainText(
                f"Discarded stale result for revision {revision}; current revision is {self.controller.revision}."
            )
            self.statusBar().showMessage("Discarded stale generation result", 5000)
            return
        self.generated_result = result
        self.generated_revision = revision
        self._update_export_actions()
        files = result.files
        self.canvas.set_artifacts(files["page-0001.svg"], files["page-0001.preview.svg"],
                                  files["page-0001.plan.json"])
        diagnostics = result.report.get("diagnostics", [])
        styles = result.report.get("styles", [])
        validation_lines = [
            "Validation passed",
            "G-code round trip: passed",
            "Machine profile: virtual simulation only",
            "Hardware verified: no",
            *(f"Style: {item['style_id']}@{item['revision']} · "
              f"{'test only' if item['test_only'] else 'production eligible'}" for item in styles),
        ]
        if diagnostics:
            validation_lines.extend(("", "Warnings:", *diagnostics))
        self.diagnostics.setPlainText("\n".join(validation_lines))
        page = result.report["pages"][0]
        logical = page["logical"]
        motion = page["motion"]
        self.toolpath.setPlainText(
            "Virtual toolpath · simulation only\n"
            f"Pen lifts: {logical['pen_lifts']}\n"
            f"Draw length: {logical['drawn_length_mm']:.2f} mm\n"
            f"Travel length: {logical['travel_length_mm']:.2f} mm\n"
            f"Logical segments: {logical['segment_count']}\n"
            f"Flattened segments: {motion['segment_count']}\n"
            f"Lower-bound time: {motion['lower_bound_time_s']:.2f} s"
        )
        self.console.setPlainText(
            f"Generated {result.document_id}\n"
            f"Page count: {result.page_count}\n"
            f"Style status: {'test only' if result.test_only_style else 'production eligible'}\n"
            "Machine status: virtual simulation only; hardware unverified."
        )
        self.canvas.zoom_to_fit()
        self.statusBar().showMessage("Generation complete", 5000)

    def _generation_failed(self, revision: int, message: str, details: str) -> None:
        self._generation_worker = None
        self.generate_action.setEnabled(True)
        if revision != self.controller.revision:
            self.console.appendPlainText(f"Ignored error from stale revision {revision}: {message}")
            return
        friendly = message.replace("MISSING_GLYPH:", "The selected style is missing: ")
        self.diagnostics.setPlainText(friendly)
        self.console.setPlainText(details)
        self.output_tabs.setCurrentWidget(self.diagnostics)
        self.statusBar().showMessage("Generation failed — see Diagnostics", 7000)

    def _update_export_actions(self) -> None:
        current = self.generated_result is not None and self.generated_revision == self.controller.revision
        for action in getattr(self, "export_actions", ()):
            action.setEnabled(current)

    def _export(self, artifact: str) -> None:
        if self.generated_result is None or self.generated_revision != self.controller.revision:
            QMessageBox.information(self, "Generate first", "Generate the current project before exporting.")
            return
        specifications = {
            "page-0001.svg": ("Export Production SVG", "page.svg", "SVG (*.svg)"),
            "page-0001.preview.svg": ("Export Diagnostic SVG", "page.preview.svg", "SVG (*.svg)"),
            "page-0001.gcode": ("Export Virtual G-code — Simulation Only", "page.virtual.gcode", "G-code (*.gcode *.nc)"),
            "report.json": ("Export Validation Report", "validation-report.json", "JSON (*.json)"),
        }
        title, suggestion, file_filter = specifications[artifact]
        filename, _ = QFileDialog.getSaveFileName(self, title, suggestion, file_filter)
        if not filename:
            return
        try:
            export_artifact(self.generated_result, artifact, Path(filename))
            self.statusBar().showMessage(f"Exported {filename}", 5000)
            self.console.appendPlainText(f"Exported {artifact} to {filename}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _virtual_profile_info(self) -> None:
        QMessageBox.information(
            self,
            "Virtual machine profile",
            "virtual-cartesian-z-v1 is a deterministic simulation profile.\n\n"
            "Generated G-code is for validation and simulation only. No hardware sender is included.",
        )

    def _restore_window_state(self) -> None:
        geometry = self.settings.value("main/geometry")
        state = self.settings.value("main/state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state, 1)
        show_travel = self.settings.value("canvas/show_travel", False, type=bool)
        show_markers = self.settings.value("canvas/show_markers", False, type=bool)
        self.travel_action.setChecked(show_travel)
        self.markers_action.setChecked(show_markers)
        self.canvas.set_show_travel(show_travel)
        self.canvas.set_show_markers(show_markers)

    def _save_window_state(self) -> None:
        self.settings.setValue("main/geometry", self.saveGeometry())
        self.settings.setValue("main/state", self.saveState(1))
        self.settings.setValue("canvas/show_travel", self.travel_action.isChecked())
        self.settings.setValue("canvas/show_markers", self.markers_action.isChecked())
        self.settings.sync()

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802 - Qt API
        if self.controller.dirty:
            choice = QMessageBox.question(
                self,
                "Unsaved project",
                "Save changes before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if choice == QMessageBox.StandardButton.Save:
                self.save_project()
                if self.controller.dirty:
                    event.ignore()
                    return
        self._save_window_state()
        event.accept()

    def _action(self, text: str, callback, shortcut=None) -> QAction:  # noqa: ANN001
        action = QAction(text, self)
        action.triggered.connect(callback)
        if shortcut is not None:
            action.setShortcut(shortcut)
        return action

    def _about(self) -> None:
        QMessageBox.about(self, "About Handwriting Plotter",
                          "Handwriting Plotter\n\nDeterministic single-line handwriting and virtual plotter planning.")
