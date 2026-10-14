"""Main desktop workspace."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .backend import GuiBackend
from .canvas import PageCanvas
from .document import (
    DocumentController,
    GridObject,
    ProjectSnapshot,
    TextObject,
    default_project,
    load_project_file,
    save_project,
)
from .exporting import export_artifact
from .i18n import Language, normalize_language, tr
from .properties import PropertiesPanel
from .styles import discover_styles
from .workers import GenerationWorker
from handwriting_plotter.version import __version__

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
        self.language = normalize_language(self.settings.value("ui/language", "en"))
        self.controller = DocumentController(default_project(), self)
        self.backend = GuiBackend()
        self.thread_pool = QThreadPool.globalInstance()
        self.generated_result = None
        self.generated_revision: int | None = None
        self._generation_worker: GenerationWorker | None = None
        self._regeneration_pending = False
        self._regeneration_timer = QTimer(self)
        self._regeneration_timer.setSingleShot(True)
        self._regeneration_timer.setInterval(120)
        self._regeneration_timer.timeout.connect(self._regenerate_after_change)
        self._selected_kind = "page"
        self._selected_value: object = None
        self._selected_object_ids: set[str] = set()
        self._refreshing_tree = False
        self._build_canvas()
        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_status_bar()
        self._connect_model()
        self._refresh_tree(self.controller.snapshot)
        self.canvas.set_object_frames(self.controller.snapshot.objects)
        self.properties.show_page(self.controller.snapshot.page)
        self._restore_window_state()
        self._update_title()
        self.statusBar().showMessage(self._t("status.ready"))

    def _t(self, key: str) -> str:
        return tr(self.language, key)

    def _build_canvas(self) -> None:
        self.canvas = PageCanvas(self)
        self.setCentralWidget(self.canvas)

    def _build_docks(self) -> None:
        project_panel = QWidget()
        project_layout = QVBoxLayout(project_panel)
        project_layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.add_text_button = QPushButton(self._t("button.add_text"))
        self.add_grid_button = QPushButton(self._t("button.add_grid"))
        self.remove_text_button = QPushButton(self._t("button.remove"))
        controls.addWidget(self.add_text_button)
        controls.addWidget(self.add_grid_button)
        controls.addWidget(self.remove_text_button)
        project_layout.addLayout(controls)
        self.project_tree = QTreeWidget()
        self.project_tree.setObjectName("project-explorer")
        self.project_tree.setHeaderHidden(True)
        self.project_tree.setAlternatingRowColors(True)
        self.project_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        project_layout.addWidget(self.project_tree)
        self.project_dock = self._dock(self._t("dock.project"), "project-dock", project_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.project_dock)

        self.properties = PropertiesPanel(self.styles, language=self.language)
        self.properties_dock = self._dock(self._t("dock.properties"), "properties-dock", self.properties)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.properties_dock)

        self.console = self._read_only_log("Application events will appear here.")
        self.diagnostics = self._read_only_log("No diagnostics.")
        self.toolpath = self._read_only_log("Generate a document to inspect its toolpath.")
        self.output_tabs = QTabWidget()
        self.output_tabs.setObjectName("output-tabs")
        self.output_tabs.addTab(self.console, self._t("tab.console"))
        self.output_tabs.addTab(self.diagnostics, self._t("tab.diagnostics"))
        self.output_tabs.addTab(self.toolpath, self._t("tab.toolpath"))
        self.output_dock = self._dock(self._t("dock.output"), "output-dock", self.output_tabs)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)
        self.resizeDocks([self.project_dock, self.properties_dock], [275, 340], Qt.Orientation.Horizontal)
        self.resizeDocks([self.output_dock], [200], Qt.Orientation.Vertical)

    def _build_actions(self) -> None:
        self.new_action = self._action(self._t("action.new"), self.new_project, QKeySequence.StandardKey.New)
        self.open_action = self._action(self._t("action.open"), self.open_project, QKeySequence.StandardKey.Open)
        self.save_action = self._action(self._t("action.save"), self.save_project, QKeySequence.StandardKey.Save)
        self.save_as_action = self._action(self._t("action.save_as"), self.save_project_as, QKeySequence.StandardKey.SaveAs)
        self.exit_action = self._action(self._t("action.exit"), self.close, QKeySequence.StandardKey.Quit)
        self.undo_action = self.controller.undo_stack.createUndoAction(self, self._t("action.undo"))
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action = self.controller.undo_stack.createRedoAction(self, self._t("action.redo"))
        self.redo_action.setShortcuts([QKeySequence.StandardKey.Redo, QKeySequence("Ctrl+Shift+Z")])
        self.add_text_action = self._action(self._t("action.add_text"), self.add_text_object, QKeySequence("Insert"))
        self.add_grid_action = self._action(self._t("action.add_grid"), self.add_grid_object)
        self.delete_action = self._action(self._t("action.delete"), self.remove_selected_object, QKeySequence.StandardKey.Delete)
        self.generate_action = self._action(self._t("action.generate"), self.generate_page, QKeySequence("Ctrl+Return"))
        self.export_svg_action = self._action(self._t("action.export_svg"), lambda: self._export("page-0001.svg"))
        self.export_preview_action = self._action(self._t("action.export_preview"), lambda: self._export("page-0001.preview.svg"))
        self.export_gcode_action = self._action(self._t("action.export_gcode"), lambda: self._export("page-0001.gcode"))
        self.export_report_action = self._action(self._t("action.export_report"), lambda: self._export("report.json"))
        self.export_actions = (
            self.export_svg_action, self.export_preview_action, self.export_gcode_action, self.export_report_action,
        )
        self._update_export_actions()

    def _build_menus(self) -> None:
        self.file_menu = self.menuBar().addMenu(self._t("menu.file"))
        self.file_menu.addActions([self.new_action, self.open_action, self.save_action, self.save_as_action])
        self.export_menu = self.file_menu.addMenu(self._t("menu.export"))
        self.export_menu.addActions(self.export_actions)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_action)
        self.edit_menu = self.menuBar().addMenu(self._t("menu.edit"))
        self.edit_menu.addActions([self.undo_action, self.redo_action])
        self.edit_menu.addSeparator()
        self.edit_menu.addActions([self.add_text_action, self.add_grid_action, self.delete_action])
        self.view_menu = self.menuBar().addMenu(self._t("menu.view"))
        for dock in (self.project_dock, self.properties_dock, self.output_dock):
            self.view_menu.addAction(dock.toggleViewAction())
        self.language_menu = self.menuBar().addMenu(self._t("menu.language"))
        self.language_group = QActionGroup(self)
        self.language_group.setExclusive(True)
        self.english_language_action = self._language_action("en")
        self.ukrainian_language_action = self._language_action("uk")
        self.language_menu.addActions(self.language_group.actions())
        self.tools_menu = self.menuBar().addMenu(self._t("menu.tools"))
        self.tools_menu.addAction(self.generate_action)
        self.machine_menu = self.menuBar().addMenu(self._t("menu.machine"))
        self.virtual_profile_action = self._action(self._t("action.virtual_profile"), self._virtual_profile_info)
        self.machine_menu.addAction(self.virtual_profile_action)
        self.help_menu = self.menuBar().addMenu(self._t("menu.help"))
        self.about_action = self._action(self._t("action.about"), self._about)
        self.help_menu.addAction(self.about_action)

    def _build_toolbar(self) -> None:
        self.workspace_toolbar = self.addToolBar(self._t("toolbar.workspace"))
        self.workspace_toolbar.setObjectName("workspace-toolbar")
        self.workspace_toolbar.addActions([self.new_action, self.open_action, self.save_action])
        self.workspace_toolbar.addSeparator()
        self.workspace_toolbar.addActions([self.add_text_action, self.add_grid_action, self.delete_action])
        self.workspace_toolbar.addSeparator()
        self.workspace_toolbar.addAction(self.generate_action)
        self.workspace_toolbar.addSeparator()
        self.fit_page_action = self._action(self._t("action.fit_page"), self.canvas.zoom_to_fit, "F")
        self.workspace_toolbar.addAction(self.fit_page_action)
        self.travel_action = self._action(self._t("action.travel"), self.canvas.set_show_travel)
        self.travel_action.setCheckable(True)
        self.workspace_toolbar.addAction(self.travel_action)
        self.markers_action = self._action(self._t("action.markers"), self.canvas.set_show_markers)
        self.markers_action.setCheckable(True)
        self.workspace_toolbar.addAction(self.markers_action)

    def _build_status_bar(self) -> None:
        self.version_label = QLabel()
        self.version_label.setObjectName("application-version")
        self.statusBar().addPermanentWidget(self.version_label)
        self._update_version_label()

    def _update_version_label(self) -> None:
        self.version_label.setText(self._t("status.version").format(version=__version__))

    def _language_action(self, language: Language) -> QAction:
        action = QAction(self._t(f"language.{language}"), self)
        action.setCheckable(True)
        action.setData(language)
        action.setChecked(language == self.language)
        action.triggered.connect(lambda checked=False, value=language: self.set_language(value))
        self.language_group.addAction(action)
        return action

    def set_language(self, language: Language) -> None:
        normalized = normalize_language(language)
        if normalized == self.language:
            return
        self.language = normalized
        self.settings.setValue("ui/language", normalized)
        self.settings.sync()
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        self.file_menu.setTitle(self._t("menu.file"))
        self.export_menu.setTitle(self._t("menu.export"))
        self.edit_menu.setTitle(self._t("menu.edit"))
        self.view_menu.setTitle(self._t("menu.view"))
        self.language_menu.setTitle(self._t("menu.language"))
        self.tools_menu.setTitle(self._t("menu.tools"))
        self.machine_menu.setTitle(self._t("menu.machine"))
        self.help_menu.setTitle(self._t("menu.help"))
        action_keys = {
            self.new_action: "action.new",
            self.open_action: "action.open",
            self.save_action: "action.save",
            self.save_as_action: "action.save_as",
            self.exit_action: "action.exit",
            self.undo_action: "action.undo",
            self.redo_action: "action.redo",
            self.add_text_action: "action.add_text",
            self.add_grid_action: "action.add_grid",
            self.delete_action: "action.delete",
            self.generate_action: "action.generate",
            self.export_svg_action: "action.export_svg",
            self.export_preview_action: "action.export_preview",
            self.export_gcode_action: "action.export_gcode",
            self.export_report_action: "action.export_report",
            self.virtual_profile_action: "action.virtual_profile",
            self.about_action: "action.about",
            self.fit_page_action: "action.fit_page",
            self.travel_action: "action.travel",
            self.markers_action: "action.markers",
        }
        for action, key in action_keys.items():
            action.setText(self._t(key))
        self.english_language_action.setText(self._t("language.en"))
        self.ukrainian_language_action.setText(self._t("language.uk"))
        self.english_language_action.setChecked(self.language == "en")
        self.ukrainian_language_action.setChecked(self.language == "uk")
        self.project_dock.setWindowTitle(self._t("dock.project"))
        self.properties_dock.setWindowTitle(self._t("dock.properties"))
        self.output_dock.setWindowTitle(self._t("dock.output"))
        self.add_text_button.setText(self._t("button.add_text"))
        self.add_grid_button.setText(self._t("button.add_grid"))
        self.remove_text_button.setText(self._t("button.remove"))
        self.output_tabs.setTabText(0, self._t("tab.console"))
        self.output_tabs.setTabText(1, self._t("tab.diagnostics"))
        self.output_tabs.setTabText(2, self._t("tab.toolpath"))
        self.workspace_toolbar.setWindowTitle(self._t("toolbar.workspace"))
        self._update_version_label()
        self.properties.set_language(self.language)
        self._refresh_tree(self.controller.snapshot)
        self.statusBar().showMessage(self._t("status.ready"), 2500)

    def _connect_model(self) -> None:
        self.controller.snapshot_changed.connect(self._on_snapshot_changed)
        self.controller.dirty_changed.connect(lambda _: self._update_title())
        self.controller.path_changed.connect(lambda _: self._update_title())
        self.project_tree.currentItemChanged.connect(self._on_selection_changed)
        self.project_tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.canvas.selection_changed.connect(self._on_canvas_selection_changed)
        self.canvas.objects_moved.connect(self._on_canvas_objects_moved)
        self.project_tree.itemChanged.connect(self._on_tree_item_changed)
        self.properties.text_object_changed.connect(self._update_text_object)
        self.properties.grid_object_changed.connect(self._update_grid_object)
        self.properties.page_changed.connect(self._update_page)
        self.add_text_button.clicked.connect(self.add_text_object)
        self.add_grid_button.clicked.connect(self.add_grid_object)
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
        selected_object_ids = set(self._selected_object_ids)
        self._refreshing_tree = True
        self.project_tree.clear()
        project = QTreeWidgetItem([snapshot.name])
        project.setData(0, ROLE_KIND, "project")
        document = QTreeWidgetItem([self._t("tree.document")])
        page = QTreeWidgetItem([self._t("tree.page")])
        page.setData(0, ROLE_KIND, "page")
        document.addChild(page)
        project.addChild(document)
        for item in snapshot.objects:
            node = QTreeWidgetItem([item.name])
            node.setData(0, ROLE_KIND, item.kind)
            node.setData(0, ROLE_VALUE, item.object_id)
            node.setFlags(node.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
            node.setCheckState(0, Qt.CheckState.Checked if item.visible else Qt.CheckState.Unchecked)
            document.addChild(node)
        resources = QTreeWidgetItem([self._t("tree.styles")])
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
        for object_id in selected_object_ids:
            node = self._find_object_tree_item(object_id)
            if node is not None:
                node.setSelected(True)
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

    def _find_object_tree_item(self, object_id: str) -> QTreeWidgetItem | None:
        for kind in ("text", "grid"):
            item = self._find_tree_item(kind, object_id)
            if item is not None:
                return item
        return None

    def _on_snapshot_changed(self, snapshot: ProjectSnapshot, revision: int) -> None:
        self._refresh_tree(snapshot)
        page = snapshot.page
        self.canvas.set_margins(page.margin_left_mm, page.margin_top_mm, page.margin_right_mm, page.margin_bottom_mm)
        self.canvas.set_object_frames(snapshot.objects, self._selected_object_ids_copy())
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
        self._sync_tree_selection()

    def _on_tree_selection_changed(self) -> None:
        if self._refreshing_tree:
            return
        self._sync_tree_selection()

    def _sync_tree_selection(self) -> None:
        selected_ids = {
            item.data(0, ROLE_VALUE)
            for item in self.project_tree.selectedItems()
            if item.data(0, ROLE_KIND) in {"text", "grid"} and isinstance(item.data(0, ROLE_VALUE), str)
        }
        current = self.project_tree.currentItem()
        if current is not None and current.data(0, ROLE_KIND) in {"text", "grid"}:
            self._selected_kind = current.data(0, ROLE_KIND)
            self._selected_value = current.data(0, ROLE_VALUE)
            selected_ids.add(self._selected_value)
        elif not selected_ids and current is not None:
            self._selected_kind = current.data(0, ROLE_KIND) or "project"
            self._selected_value = current.data(0, ROLE_VALUE)
        self._selected_object_ids = selected_ids
        self.canvas.set_selected_objects(self._selected_object_ids_copy())
        self._show_selected_properties()
        enabled = bool(selected_ids)
        self.delete_action.setEnabled(enabled)
        self.remove_text_button.setEnabled(enabled)

    def _selected_object_ids_copy(self) -> set[str]:
        return set(self._selected_object_ids)

    def _on_canvas_selection_changed(self, object_ids) -> None:  # noqa: ANN001
        valid = {
            object_id
            for object_id in object_ids
            if any(item.object_id == object_id for item in self.controller.snapshot.objects)
        }
        self._selected_object_ids = valid
        self._refreshing_tree = True
        self.project_tree.clearSelection()
        if valid:
            primary = sorted(valid)[0]
            model = next(item for item in self.controller.snapshot.objects if item.object_id == primary)
            self._selected_kind, self._selected_value = model.kind, primary
            node = self._find_object_tree_item(primary)
            if node is not None:
                self.project_tree.setCurrentItem(node)
            for object_id in sorted(valid):
                selected_node = self._find_object_tree_item(object_id)
                if selected_node is not None:
                    selected_node.setSelected(True)
        else:
            self._selected_kind, self._selected_value = "page", None
            page = self._find_tree_item("page", None)
            if page is not None:
                self.project_tree.setCurrentItem(page)
        self._refreshing_tree = False
        self.canvas.set_selected_objects(valid)
        self._show_selected_properties()
        enabled = bool(valid)
        self.delete_action.setEnabled(enabled)
        self.remove_text_button.setEnabled(enabled)

    def _show_selected_properties(self) -> None:
        if self._selected_kind == "page":
            self.properties.show_page(self.controller.snapshot.page)
        elif self._selected_kind == "text":
            item = next((obj for obj in self.controller.snapshot.objects if obj.object_id == self._selected_value), None)
            if isinstance(item, TextObject):
                self.properties.show_text_object(item)
        elif self._selected_kind == "grid":
            item = next((obj for obj in self.controller.snapshot.objects if obj.object_id == self._selected_value), None)
            if isinstance(item, GridObject):
                self.properties.show_grid_object(item)
        elif self._selected_kind == "style":
            style = next((obj for obj in self.styles if obj.reference == self._selected_value), None)
            if style:
                self.properties.show_style(style)

    def _on_tree_item_changed(self, node: QTreeWidgetItem, column: int) -> None:
        if self._refreshing_tree or node.data(0, ROLE_KIND) not in {"text", "grid"}:
            return
        object_id = node.data(0, ROLE_VALUE)
        fallback_name = "Grid" if node.data(0, ROLE_KIND) == "grid" else "Text"
        name = node.text(0).strip() or fallback_name
        visible = node.checkState(0) == Qt.CheckState.Checked
        QTimer.singleShot(0, lambda: self._apply_tree_item_change(object_id, name, visible))

    def _apply_tree_item_change(self, object_id: str, name: str, visible: bool) -> None:
        item = next((item for item in self.controller.snapshot.objects if item.object_id == object_id), None)
        if item is None:
            return
        had_current_generation = (
            self.generated_result is not None
            and self.generated_revision == self.controller.revision
        )
        visibility_changed = item.visible != visible
        if isinstance(item, TextObject):
            self.controller.update_text_object(object_id, name=name, visible=visible)
        else:
            self.controller.update_grid_object(object_id, name=name, visible=visible)
            self._preserve_generation_revision(had_current_generation)
        if isinstance(item, TextObject) and visibility_changed and (had_current_generation or self._regeneration_pending):
            self._schedule_regeneration("Visibility changed · updating page…")

    def _schedule_regeneration(self, message: str) -> None:
        self._regeneration_pending = True
        self._regeneration_timer.start()
        self.canvas.clear_artifacts()
        self.generated_result = None
        self.generated_revision = None
        self._update_export_actions()
        self.statusBar().showMessage(message)

    def _regenerate_after_change(self) -> None:
        if not any(isinstance(item, TextObject) and item.visible for item in self.controller.snapshot.objects):
            self.console.setPlainText("All text objects are hidden.")
            self.statusBar().showMessage("All text objects are hidden", 4000)
            return
        if self._generation_worker is not None:
            self._regeneration_timer.start()
            return
        self._regeneration_pending = False
        self.generate_page()

    def _on_canvas_objects_moved(self, object_ids, dx_mm: float, dy_mm: float) -> None:  # noqa: ANN001
        had_current_generation = (
            self.generated_result is not None
            and self.generated_revision == self.controller.revision
        )
        try:
            selected = set(object_ids)
            moving_text = any(
                isinstance(item, TextObject) and item.object_id in selected
                for item in self.controller.snapshot.objects
            )
            self.controller.move_objects(selected, dx_mm, dy_mm)
        except ValueError as exc:
            self.canvas.set_object_frames(self.controller.snapshot.objects, self._selected_object_ids_copy())
            self.statusBar().showMessage(str(exc), 5000)
            return
        if not moving_text:
            self._preserve_generation_revision(had_current_generation)
        elif had_current_generation or self._regeneration_pending:
            self._schedule_regeneration("Object moved · updating page…")

    def _update_text_object(self, object_id: str, changes: dict) -> None:
        try:
            self.controller.update_text_object(object_id, **changes)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc), 5000)

    def _update_grid_object(self, object_id: str, changes: dict) -> None:
        had_current_generation = (
            self.generated_result is not None
            and self.generated_revision == self.controller.revision
        )
        try:
            self.controller.update_grid_object(object_id, **changes)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc), 5000)
            return
        self._preserve_generation_revision(had_current_generation)

    def _preserve_generation_revision(self, had_current_generation: bool) -> None:
        if had_current_generation and self.generated_result is not None:
            self.generated_revision = self.controller.revision
            self._update_export_actions()

    def _update_page(self, changes: dict) -> None:
        try:
            self.controller.update_page(**changes)
        except ValueError as exc:
            self.statusBar().showMessage(str(exc), 5000)

    def add_text_object(self) -> None:
        item = self.controller.add_text_object()
        self._selected_kind, self._selected_value = "text", item.object_id
        self._selected_object_ids = {item.object_id}
        self._refresh_tree(self.controller.snapshot)
        self._sync_tree_selection()

    def add_grid_object(self) -> None:
        had_current_generation = (
            self.generated_result is not None
            and self.generated_revision == self.controller.revision
        )
        item = self.controller.add_grid_object()
        self._selected_kind, self._selected_value = "grid", item.object_id
        self._selected_object_ids = {item.object_id}
        self._refresh_tree(self.controller.snapshot)
        self._sync_tree_selection()
        self._preserve_generation_revision(had_current_generation)

    def remove_selected_object(self) -> None:
        if not self._selected_object_ids:
            return
        selected = set(self._selected_object_ids)
        selected_models = [item for item in self.controller.snapshot.objects if item.object_id in selected]
        had_current_generation = (
            self.generated_result is not None
            and self.generated_revision == self.controller.revision
        )
        self.controller.remove_objects(selected)
        if selected_models and all(isinstance(item, GridObject) for item in selected_models):
            self._preserve_generation_revision(had_current_generation)
        self._selected_object_ids.clear()
        self._selected_kind, self._selected_value = "page", None
        self._on_canvas_selection_changed(())

    def new_project(self) -> None:
        self._regeneration_timer.stop()
        self._regeneration_pending = False
        self._selected_object_ids.clear()
        self._selected_kind, self._selected_value = "page", None
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
            self._regeneration_timer.stop()
            self._regeneration_pending = False
            loaded = load_project_file(Path(filename))
            self._selected_object_ids.clear()
            self._selected_kind, self._selected_value = "page", None
            self.controller.reset(loaded.snapshot, Path(filename))
            self.canvas.clear_artifacts()
            self.generated_result = None
            self.generated_revision = None
            self._update_export_actions()
            if loaded.generation_result is not None:
                self._display_generation_result(self.controller.revision, loaded.generation_result)
                self.console.appendPlainText(f"\nRestored generated page from {filename}")
                self.statusBar().showMessage("Project and generated page restored", 5000)
            else:
                self.console.setPlainText(f"Opened {filename}")
                if loaded.cache_warning:
                    self.console.appendPlainText(f"Ignored invalid generated cache: {loaded.cache_warning}")
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
            current_result = (
                self.generated_result
                if self.generated_revision == self.controller.revision
                else None
            )
            save_project(path, self.controller.snapshot, current_result)
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
        self._display_generation_result(revision, result)
        self.statusBar().showMessage("Generation complete", 5000)

    def _display_generation_result(self, revision: int, result) -> None:  # noqa: ANN001
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
