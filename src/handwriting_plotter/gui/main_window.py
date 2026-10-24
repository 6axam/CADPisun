"""Main desktop workspace."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from handwriting_plotter.version import __version__
from handwriting_plotter.application.resources import style_root

from .backend import GuiBackend, generation_source_hash
from .artwork import import_artwork
from .canvas import PageCanvas
from .document import (
    ArtworkObject,
    DocumentController,
    GridObject,
    ProjectSnapshot,
    TextObject,
    default_project,
    load_project_file,
    save_project,
)
from .dialogs import ControlsDialog, ProgramSettingsDialog, ShortcutBinding
from .notebook_dialog import NotebookTemplateDialog
from .notebook_templates import notebook_background_svg
from .exporting import export_artifact, export_page_png
from .i18n import Language, normalize_language, tr
from .mode_workspaces import ArtifactModeWorkspace
from .properties import PropertiesPanel
from .styles import discover_styles
from .studio import HandwritingStudio, handwriting_data_root
from .theme import COLORS
from .tool_panels import ResponsiveActionPanel
from .workers import GenerationWorker

ROLE_KIND = int(Qt.ItemDataRole.UserRole)
ROLE_VALUE = ROLE_KIND + 1


class MainWindow(QMainWindow):
    """Dockable engineering workspace backed by an undoable project model."""

    def __init__(self, settings: QSettings | None = None, *, user_data_root: Path | None = None) -> None:
        super().__init__()
        self.setObjectName("main-window")
        self.resize(1440, 900)
        self.setDockNestingEnabled(True)
        self.settings = settings or QSettings("Handwriting Plotter", "Handwriting Plotter")
        self.language = normalize_language(self.settings.value("ui/language", "en"))
        self.user_data_root = user_data_root or handwriting_data_root()
        self.user_style_root = self.user_data_root / "styles"
        self.styles = discover_styles(self.user_style_root)
        self.controller = DocumentController(default_project(), self)
        self.backend = GuiBackend(style_roots=(style_root(), self.user_style_root))
        self.thread_pool = QThreadPool.globalInstance()
        self.generated_result = None
        self.generated_revision: int | None = None
        self.generated_source_hash: str | None = None
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
        self._tree_signature: tuple | None = None
        self._canvas_objects_signature: tuple | None = None
        self._margin_signature: tuple[float, float, float, float] | None = None
        self._notebook_template_signature: tuple | None = None
        self._document_dock_visibility: dict[str, bool] = {}
        self._workspace = "document"
        self._build_canvas()
        self._build_docks()
        self._build_actions()
        self._build_tool_docks()
        self._build_menus()
        self._build_status_bar()
        self._connect_model()
        self._refresh_tree(self.controller.snapshot)
        self._refresh_canvas_objects(self.controller.snapshot)
        self._refresh_canvas_template(self.controller.snapshot)
        self._refresh_canvas_margins(self.controller.snapshot)
        self.properties.show_page(self.controller.snapshot.page)
        self._restore_window_state()
        self._update_title()
        self._show_status(self._t("status.ready"))

    def _t(self, key: str) -> str:
        return tr(self.language, key)

    def _build_canvas(self) -> None:
        self.canvas = PageCanvas(self)
        self.preview_workspace = ArtifactModeWorkspace("preview", self)
        self.execution_workspace = ArtifactModeWorkspace("execution", self)
        self.studio = HandwritingStudio(self.user_data_root, language=self.language, parent=self)
        # A hidden workflow page must not enlarge the document window's minimum
        # geometry. The Studio contains a deliberately dense photo/HTR workflow;
        # QStackedWidget otherwise propagates that page's minimum size even while
        # the document canvas is active.
        self.studio.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.studio.setMinimumSize(0, 0)
        self.workspace_stack = QStackedWidget(self)
        self.workspace_stack.setObjectName("workspace-stack")
        self.workspace_stack.addWidget(self.canvas)
        self.workspace_stack.addWidget(self.preview_workspace)
        self.workspace_stack.addWidget(self.execution_workspace)
        self.workspace_stack.addWidget(self.studio)
        self.studio.style_published.connect(self._style_published)
        self.setCentralWidget(self.workspace_stack)

    def _style_published(self, style_id: str, revision: str) -> None:
        self.styles = discover_styles(self.user_style_root)
        self.properties.set_styles(self.styles)
        self.backend = GuiBackend(style_roots=(style_root(), self.user_style_root))
        self._refresh_tree(self.controller.snapshot)
        self._show_status(f"Style published · {style_id}@{revision}")

    def _build_docks(self) -> None:
        project_panel = QWidget()
        project_layout = QVBoxLayout(project_panel)
        project_layout.setContentsMargins(0, 0, 0, 0)
        self.project_tree = QTreeWidget()
        self.project_tree.setObjectName("project-explorer")
        self.project_tree.setHeaderHidden(True)
        self.project_tree.setAlternatingRowColors(True)
        self.project_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        project_layout.addWidget(self.project_tree)
        self.project_dock = self._dock(self._t("dock.project"), "project-dock", project_panel)
        self.project_dock.setMinimumWidth(200)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.project_dock)

        self.properties = PropertiesPanel(self.styles, language=self.language)
        self.properties_scroll = QScrollArea()
        self.properties_scroll.setObjectName("properties-scroll")
        self.properties_scroll.setWidgetResizable(True)
        self.properties_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.properties_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.properties_scroll.setWidget(self.properties)
        self.properties_dock = self._dock(
            self._t("dock.properties"), "properties-dock", self.properties_scroll
        )
        self.properties_dock.setMinimumWidth(320)
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
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.resizeDocks([self.project_dock, self.properties_dock], [275, 340], Qt.Orientation.Horizontal)
        self.resizeDocks([self.output_dock], [200], Qt.Orientation.Vertical)

    def _build_actions(self) -> None:
        self.workspace_group = QActionGroup(self)
        self.workspace_group.setExclusive(True)
        self.document_workspace_action = self._action(
            self._t("action.workspace.document"), lambda: self.set_workspace("document")
        )
        self.studio_workspace_action = self._action(
            self._t("action.workspace.studio"), lambda: self.set_workspace("studio")
        )
        for action in (self.document_workspace_action, self.studio_workspace_action):
            action.setCheckable(True)
            self.workspace_group.addAction(action)
        self.document_workspace_action.setChecked(True)
        self.object_mode_action = self.document_workspace_action
        self.preview_mode_action = self._action(
            self._t("action.mode.preview"), lambda: self.set_workspace("preview")
        )
        self.execution_mode_action = self._action(
            self._t("action.mode.execution"), lambda: self.set_workspace("execution")
        )
        for action in (self.preview_mode_action, self.execution_mode_action):
            action.setCheckable(True)
            action.setProperty("implementationStatus", "implemented")
            self.workspace_group.addAction(action)
        self.preview_mode_action.setToolTip(self._t("action.mode.preview_tip"))
        self.execution_mode_action.setToolTip(self._t("action.mode.execution_tip"))
        self.preview_mode_action.setData("preview")
        self.execution_mode_action.setData("execution")
        self.new_action = self._action(self._t("action.new"), self.new_project, QKeySequence.StandardKey.New)
        self.open_action = self._action(self._t("action.open"), self.open_project, QKeySequence.StandardKey.Open)
        self.import_artwork_action = self._action(
            self._t("action.import_artwork"), self.import_artwork_file, QKeySequence("Ctrl+Shift+I")
        )
        self.notebook_template_action = self._action(
            self._t("action.notebook_template"), self.edit_notebook_template
        )
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
        self.fit_page_action = self._action(self._t("action.fit_page"), self.canvas.zoom_to_fit, "F")
        self.travel_action = self._action(self._t("action.travel"), self.canvas.set_show_travel)
        self.travel_action.setCheckable(True)
        self.markers_action = self._action(self._t("action.markers"), self.canvas.set_show_markers)
        self.markers_action.setCheckable(True)
        self.export_background_action = self._action(
            self._t("action.export_background"), self.export_notebook_background
        )
        self.export_svg_action = self._action(self._t("action.export_svg"), lambda: self._export("page-0001.svg"))
        self.export_preview_action = self._action(self._t("action.export_preview"), lambda: self._export("page-0001.preview.svg"))
        self.export_png_action = self._action(self._t("action.export_png"), lambda: self._export("page-0001.png"))
        self.export_gcode_action = self._action(self._t("action.export_gcode"), lambda: self._export("page-0001.gcode"))
        self.export_report_action = self._action(self._t("action.export_report"), lambda: self._export("report.json"))
        self.export_actions = (
            self.export_svg_action, self.export_preview_action, self.export_png_action,
            self.export_gcode_action, self.export_report_action,
        )
        self._configure_shortcuts()
        self._update_export_actions()

    def _build_tool_docks(self) -> None:
        project_specifications = (
            ("◇", self.new_action, "tool-new"),
            ("↥", self.open_action, "tool-open"),
            ("▧", self.import_artwork_action, "tool-import-artwork"),
            ("▣", self.save_action, "tool-save"),
            ("▶", self.generate_action, "tool-generate"),
        )
        editing_specifications = (
            ("↶", self.undo_action, "tool-undo"),
            ("↷", self.redo_action, "tool-redo"),
            ("T+", self.add_text_action, "tool-add-text"),
            ("▦", self.add_grid_action, "tool-add-grid"),
            ("⌫", self.delete_action, "tool-delete"),
        )
        view_specifications = (
            ("⛶", self.fit_page_action, "tool-fit-page"),
            ("↝", self.travel_action, "tool-travel"),
            ("●", self.markers_action, "tool-markers"),
        )
        self.project_tools_panel = ResponsiveActionPanel(project_specifications)
        self.editing_tools_panel = ResponsiveActionPanel(editing_specifications)
        self.view_tools_panel = ResponsiveActionPanel(view_specifications)
        self.project_tools_dock = self._dock(
            self._t("dock.project_tools"), "project-tools-dock", self.project_tools_panel
        )
        self.editing_tools_dock = self._dock(
            self._t("dock.editing"), "editing-tools-dock", self.editing_tools_panel
        )
        self.view_tools_dock = self._dock(
            self._t("dock.view_tools"), "view-tools-dock", self.view_tools_panel
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.project_tools_dock)
        self.splitDockWidget(self.project_dock, self.project_tools_dock, Qt.Orientation.Vertical)
        self.splitDockWidget(self.project_tools_dock, self.editing_tools_dock, Qt.Orientation.Vertical)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.editing_tools_dock)
        self.resizeDocks(
            [self.project_dock, self.project_tools_dock, self.editing_tools_dock],
            [560, 105, 105],
            Qt.Orientation.Vertical,
        )
        self.tool_buttons = list(
            self.project_tools_panel.buttons
            + self.editing_tools_panel.buttons
            + self.view_tools_panel.buttons
        )
        self.add_text_button = self.editing_tools_panel.buttons[2]
        self.add_grid_button = self.editing_tools_panel.buttons[3]
        self.remove_text_button = self.editing_tools_panel.buttons[4]

        mode_specs = (
            ("□", self.object_mode_action, "mode-object"),
            ("▶", self.preview_mode_action, "mode-preview"),
            ("⚙", self.execution_mode_action, "mode-execution"),
        )
        self.modes_panel = ResponsiveActionPanel(mode_specs)
        self.mode_buttons = list(self.modes_panel.buttons)
        self.modes_dock = self._dock(self._t("dock.modes"), "modes-dock", self.modes_panel)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.modes_dock)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.view_tools_dock)
        self.splitDockWidget(self.modes_dock, self.view_tools_dock, Qt.Orientation.Horizontal)

    def _build_menus(self) -> None:
        self.file_menu = self.menuBar().addMenu(self._t("menu.file"))
        self.file_menu.addActions([
            self.new_action, self.open_action, self.import_artwork_action, self.notebook_template_action,
            self.save_action, self.save_as_action,
        ])
        self.export_menu = self.file_menu.addMenu(self._t("menu.export"))
        self.export_menu.addAction(self.export_background_action)
        self.export_menu.addSeparator()
        self.export_menu.addActions(self.export_actions)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_action)
        self.edit_menu = self.menuBar().addMenu(self._t("menu.edit"))
        self.edit_menu.addActions([self.undo_action, self.redo_action])
        self.edit_menu.addSeparator()
        self.edit_menu.addActions([self.add_text_action, self.add_grid_action, self.delete_action])
        self.view_menu = self.menuBar().addMenu(self._t("menu.view"))
        for dock in (
            self.project_dock, self.project_tools_dock, self.editing_tools_dock,
            self.modes_dock, self.view_tools_dock,
            self.properties_dock, self.output_dock,
        ):
            self.view_menu.addAction(dock.toggleViewAction())
        self.language_menu = self.menuBar().addMenu(self._t("menu.language"))
        self.language_group = QActionGroup(self)
        self.language_group.setExclusive(True)
        self.english_language_action = self._language_action("en")
        self.ukrainian_language_action = self._language_action("uk")
        self.language_menu.addActions(self.language_group.actions())
        self.tools_menu = self.menuBar().addMenu(self._t("menu.tools"))
        self.tools_menu.addAction(self.generate_action)
        self.tools_menu.addSeparator()
        self.tools_menu.addAction(self.studio_workspace_action)
        self.tools_menu.addSeparator()
        self.program_settings_action = self._action(
            self._t("action.program_settings"), self._show_program_settings
        )
        self.tools_menu.addAction(self.program_settings_action)
        self.machine_menu = self.menuBar().addMenu(self._t("menu.machine"))
        self.virtual_profile_action = self._action(self._t("action.virtual_profile"), self._virtual_profile_info)
        self.machine_menu.addAction(self.virtual_profile_action)
        self.help_menu = self.menuBar().addMenu(self._t("menu.help"))
        self.controls_action = self._action(self._t("action.controls"), self._show_controls, "F1")
        self.about_action = self._action(self._t("action.about"), self._about)
        self.help_menu.addActions([self.controls_action, self.about_action])

    def _build_status_bar(self) -> None:
        self._canvas_fps = 0.0
        self._cursor_position = None
        self.telemetry_label = QLabel()
        self.telemetry_label.setObjectName("canvas-telemetry")
        self.statusBar().addPermanentWidget(self.telemetry_label)
        self.operation_status_label = QLabel()
        self.operation_status_label.setObjectName("operation-status")
        self.operation_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.statusBar().addPermanentWidget(self.operation_status_label, 1)
        self._status_reset_timer = QTimer(self)
        self._status_reset_timer.setSingleShot(True)
        self._status_reset_timer.timeout.connect(self._reset_status_message)
        self.generation_progress = QProgressBar()
        self.generation_progress.setObjectName("generation-progress")
        self._progress_hide_timer = QTimer(self)
        self._progress_hide_timer.setSingleShot(True)
        self._progress_hide_timer.timeout.connect(self._hide_finished_generation_progress)
        self.generation_progress.setFixedWidth(210)
        self.generation_progress.setTextVisible(True)
        self.generation_progress.hide()
        self.statusBar().addPermanentWidget(self.generation_progress)
        self.version_label = QLabel()
        self.version_label.setObjectName("application-version")
        self.statusBar().addPermanentWidget(self.version_label)
        self._update_telemetry_label()
        self._update_version_label()

    def _start_generation_progress(self) -> None:
        self._progress_hide_timer.stop()
        self.generation_progress.setProperty("state", "running")
        self.generation_progress.setRange(0, 0)
        self.generation_progress.setFormat(self._t("status.progress.generating"))
        self.generation_progress.setStyleSheet(
            f"QProgressBar::chunk {{ background: {COLORS['accent']}; }}"
        )
        self.generation_progress.show()

    def _finish_generation_progress(self, state: str) -> None:
        states = {
            "success": (100, "status.progress.complete", COLORS["success"]),
            "warning": (0, "status.progress.stopped", COLORS["warning"]),
            "error": (0, "status.progress.failed", COLORS["danger"]),
        }
        if state not in states:
            raise ValueError(f"UNKNOWN_PROGRESS_STATE:{state}")
        value, message_key, color = states[state]
        self.generation_progress.setProperty("state", state)
        self.generation_progress.setRange(0, 100)
        self.generation_progress.setValue(value)
        self.generation_progress.setFormat(self._t(message_key))
        self.generation_progress.setStyleSheet(
            f"QProgressBar::chunk {{ background: {color}; }}"
        )
        self.generation_progress.show()
        self._progress_hide_timer.start(1600)

    def _hide_finished_generation_progress(self) -> None:
        if self.generation_progress.property("state") != "running":
            self.generation_progress.hide()

    def _update_version_label(self) -> None:
        self.version_label.setText(self._t("status.version").format(version=__version__))

    def _show_status(self, message: str, severity: str = "info", timeout: int = 0) -> None:
        colors = {
            "info": COLORS["muted"],
            "success": COLORS["success"],
            "warning": COLORS["warning"],
            "error": COLORS["danger"],
        }
        if severity not in colors:
            raise ValueError(f"UNKNOWN_STATUS_SEVERITY:{severity}")
        self._status_reset_timer.stop()
        self.statusBar().setProperty("messageSeverity", severity)
        self.operation_status_label.setProperty("severity", severity)
        self.operation_status_label.setStyleSheet(f"color: {colors[severity]};")
        self.operation_status_label.setText(message)
        self.statusBar().showMessage(message, timeout)
        if timeout > 0:
            self._status_reset_timer.start(timeout)

    def _reset_status_message(self) -> None:
        self._show_status(self._t("status.ready"))

    def _update_telemetry_label(self) -> None:
        if self._cursor_position is None:
            coordinates = self._t("status.cursor.empty")
        else:
            coordinates = self._t("status.cursor.position").format(
                x=self._cursor_position.x(),
                y=self._cursor_position.y(),
            )
        self.telemetry_label.setText(
            f"{self._t('status.fps').format(fps=self._canvas_fps)}  ·  {coordinates}"
        )

    def _on_canvas_fps_changed(self, fps: float) -> None:
        self._canvas_fps = fps
        self._update_telemetry_label()

    def _on_cursor_position_changed(self, position) -> None:  # noqa: ANN001
        self._cursor_position = position
        self._update_telemetry_label()

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
            self.document_workspace_action: "action.workspace.document",
            self.studio_workspace_action: "action.workspace.studio",
            self.preview_mode_action: "action.mode.preview",
            self.execution_mode_action: "action.mode.execution",
            self.new_action: "action.new",
            self.open_action: "action.open",
            self.import_artwork_action: "action.import_artwork",
            self.notebook_template_action: "action.notebook_template",
            self.save_action: "action.save",
            self.save_as_action: "action.save_as",
            self.exit_action: "action.exit",
            self.undo_action: "action.undo",
            self.redo_action: "action.redo",
            self.add_text_action: "action.add_text",
            self.add_grid_action: "action.add_grid",
            self.delete_action: "action.delete",
            self.generate_action: "action.generate",
            self.export_background_action: "action.export_background",
            self.export_svg_action: "action.export_svg",
            self.export_preview_action: "action.export_preview",
            self.export_png_action: "action.export_png",
            self.export_gcode_action: "action.export_gcode",
            self.export_report_action: "action.export_report",
            self.virtual_profile_action: "action.virtual_profile",
            self.program_settings_action: "action.program_settings",
            self.controls_action: "action.controls",
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
        self.project_tools_dock.setWindowTitle(self._t("dock.project_tools"))
        self.editing_tools_dock.setWindowTitle(self._t("dock.editing"))
        self.view_tools_dock.setWindowTitle(self._t("dock.view_tools"))
        self.modes_dock.setWindowTitle(self._t("dock.modes"))
        self.properties_dock.setWindowTitle(self._t("dock.properties"))
        self.output_dock.setWindowTitle(self._t("dock.output"))
        self.output_tabs.setTabText(0, self._t("tab.console"))
        self.output_tabs.setTabText(1, self._t("tab.diagnostics"))
        self.output_tabs.setTabText(2, self._t("tab.toolpath"))
        self.preview_mode_action.setToolTip(self._t("action.mode.preview_tip"))
        self.execution_mode_action.setToolTip(self._t("action.mode.execution_tip"))
        progress_state = self.generation_progress.property("state")
        if progress_state == "running":
            self.generation_progress.setFormat(self._t("status.progress.generating"))
        elif progress_state in {"success", "warning", "error"}:
            progress_key = {
                "success": "status.progress.complete",
                "warning": "status.progress.stopped",
                "error": "status.progress.failed",
            }[progress_state]
            self.generation_progress.setFormat(self._t(progress_key))
        self._update_telemetry_label()
        self._update_version_label()
        self.canvas.set_preview_stale(
            self.canvas.preview_is_stale,
            self._t("canvas.preview_stale"),
        )
        self.properties.set_language(self.language)
        self.preview_workspace.set_language(self.language)
        self.execution_workspace.set_language(self.language)
        self.studio.set_language(self.language)
        self._refresh_tree(self.controller.snapshot)
        self._show_status(self._t("status.ready"), timeout=2500)

    def set_workspace(self, workspace: str) -> None:
        if workspace not in {"document", "preview", "execution", "studio"}:
            raise ValueError("UNKNOWN_WORKSPACE")
        docks = self._document_docks()
        if workspace == "studio":
            if self._workspace == "document":
                self._document_dock_visibility = {
                    dock.objectName(): dock.toggleViewAction().isChecked() for dock in docks
                }
            self.workspace_stack.setCurrentWidget(self.studio)
            for dock in docks:
                dock.hide()
            self.studio_workspace_action.setChecked(True)
            self.telemetry_label.hide()
        elif workspace == "document":
            self.workspace_stack.setCurrentWidget(self.canvas)
            for dock in docks:
                dock.setVisible(self._document_dock_visibility.get(dock.objectName(), True))
            self.document_workspace_action.setChecked(True)
            self.telemetry_label.show()
        else:
            if self._workspace == "document":
                self._document_dock_visibility = {
                    dock.objectName(): dock.toggleViewAction().isChecked() for dock in docks
                }
            target = self.preview_workspace if workspace == "preview" else self.execution_workspace
            self.workspace_stack.setCurrentWidget(target)
            for dock in docks:
                dock.setVisible(dock in {self.modes_dock, self.view_tools_dock, self.output_dock})
            (self.preview_mode_action if workspace == "preview" else self.execution_mode_action).setChecked(True)
            self.telemetry_label.hide()
            current = (
                self.generated_result is not None
                and self.generated_source_hash == generation_source_hash(self.controller.snapshot)
            )
            target.set_stale(not current)
            if self.generated_result is None and self._generation_worker is None:
                self.generate_page()
        self._workspace = workspace

    def _document_docks(self) -> tuple[QDockWidget, ...]:
        return (
            self.project_dock,
            self.project_tools_dock,
            self.editing_tools_dock,
            self.view_tools_dock,
            self.properties_dock,
            self.output_dock,
        )

    def _connect_model(self) -> None:
        self.controller.snapshot_changed.connect(self._on_snapshot_changed)
        self.controller.dirty_changed.connect(lambda _: self._update_title())
        self.controller.path_changed.connect(lambda _: self._update_title())
        self.project_tree.currentItemChanged.connect(self._on_selection_changed)
        self.project_tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.canvas.selection_changed.connect(self._on_canvas_selection_changed)
        self.canvas.objects_moved.connect(self._on_canvas_objects_moved)
        self.canvas.object_resized.connect(self._on_canvas_object_resized)
        self.canvas.fps_changed.connect(self._on_canvas_fps_changed)
        self.canvas.cursor_position_changed.connect(self._on_cursor_position_changed)
        self.project_tree.itemChanged.connect(self._on_tree_item_changed)
        self.properties.text_object_changed.connect(self._update_text_object)
        self.properties.text_content_changed.connect(self._update_text_content)
        self.properties.grid_object_changed.connect(self._update_grid_object)
        self.properties.artwork_object_changed.connect(self._update_artwork_object)
        self.properties.page_changed.connect(self._update_page)

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
        self._tree_signature = self._project_tree_signature(snapshot)

    @staticmethod
    def _project_tree_signature(snapshot: ProjectSnapshot) -> tuple:
        return (
            snapshot.name,
            tuple((item.kind, item.object_id, item.name, item.visible) for item in snapshot.objects),
        )

    @staticmethod
    def _canvas_signature(snapshot: ProjectSnapshot) -> tuple:
        signatures: list[tuple] = []
        for item in snapshot.objects:
            if isinstance(item, TextObject):
                signatures.append((
                    item.kind,
                    item.object_id,
                    item.visible,
                    item.frame_x_mm,
                    item.frame_y_mm,
                    item.frame_width_mm,
                    item.frame_height_mm,
                    item.display_diameter_mm,
                    item.color_group,
                ))
            elif isinstance(item, GridObject):
                signatures.append((
                    item.kind,
                    item.object_id,
                    item.visible,
                    item.x_mm,
                    item.y_mm,
                    item.width_mm,
                    item.height_mm,
                    item.cell_width_mm,
                    item.cell_height_mm,
                    item.line_style,
                    item.color,
                    item.snap_enabled,
                ))
            else:
                signatures.append((
                    item.kind,
                    item.object_id,
                    item.visible,
                    item.x_mm,
                    item.y_mm,
                    item.width_mm,
                    item.height_mm,
                    item.opacity,
                    item.sha256,
                ))
        return tuple(signatures)

    def _refresh_canvas_objects(self, snapshot: ProjectSnapshot) -> None:
        self.canvas.set_object_frames(snapshot.objects, self._selected_object_ids_copy())
        self._canvas_objects_signature = self._canvas_signature(snapshot)

    @staticmethod
    def _template_signature(snapshot: ProjectSnapshot) -> tuple:
        template = snapshot.notebook_template
        return () if template is None else tuple(sorted(template.model_dump(mode="json").items()))

    def _refresh_canvas_template(self, snapshot: ProjectSnapshot) -> None:
        self.canvas.set_notebook_template(snapshot.notebook_template)
        if snapshot.notebook_template is None:
            self.canvas.set_page_size(snapshot.page.width_mm, snapshot.page.height_mm)
        self._notebook_template_signature = self._template_signature(snapshot)

    def _refresh_canvas_margins(self, snapshot: ProjectSnapshot) -> None:
        page = snapshot.page
        self.canvas.set_margins(
            page.margin_left_mm,
            page.margin_top_mm,
            page.margin_right_mm,
            page.margin_bottom_mm,
        )
        self._margin_signature = (
            page.margin_left_mm,
            page.margin_top_mm,
            page.margin_right_mm,
            page.margin_bottom_mm,
        )

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
        for kind in ("text", "grid", "artwork"):
            item = self._find_tree_item(kind, object_id)
            if item is not None:
                return item
        return None

    def _on_snapshot_changed(self, snapshot: ProjectSnapshot, revision: int) -> None:
        if self._project_tree_signature(snapshot) != self._tree_signature:
            self._refresh_tree(snapshot)
        page = snapshot.page
        margins = (
            page.margin_left_mm,
            page.margin_top_mm,
            page.margin_right_mm,
            page.margin_bottom_mm,
        )
        if self._template_signature(snapshot) != self._notebook_template_signature:
            self._refresh_canvas_template(snapshot)
        if margins != self._margin_signature:
            self._refresh_canvas_margins(snapshot)
        if self._canvas_signature(snapshot) != self._canvas_objects_signature:
            self._refresh_canvas_objects(snapshot)
        focus = QApplication.focusWidget()
        if focus is None or not self.properties.isAncestorOf(focus):
            self._show_selected_properties()
        self._update_title()
        if self.generated_result is not None:
            current = self.generated_source_hash == generation_source_hash(snapshot)
            self.canvas.set_preview_stale(
                not current,
                self._t("canvas.preview_stale"),
            )
            self.preview_workspace.set_stale(not current)
            self.execution_workspace.set_stale(not current)
            if current:
                self.generated_revision = revision
                self._update_export_actions()
            else:
                self._update_export_actions()
                self._show_status("Project changed · generated preview is stale", "warning", 4000)
                return
        elif self.generated_revision is not None and self.generated_revision != revision:
            self._update_export_actions()
        self._show_status(f"Project changed · revision {revision}", timeout=2500)

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
            if item.data(0, ROLE_KIND) in {"text", "grid", "artwork"}
            and isinstance(item.data(0, ROLE_VALUE), str)
        }
        current = self.project_tree.currentItem()
        if current is not None and current.data(0, ROLE_KIND) in {"text", "grid", "artwork"}:
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
        elif self._selected_kind == "artwork":
            item = next((obj for obj in self.controller.snapshot.objects if obj.object_id == self._selected_value), None)
            if isinstance(item, ArtworkObject):
                self.properties.show_artwork_object(item)
        elif self._selected_kind == "style":
            style = next((obj for obj in self.styles if obj.reference == self._selected_value), None)
            if style:
                self.properties.show_style(style)

    def _on_tree_item_changed(self, node: QTreeWidgetItem, column: int) -> None:
        if self._refreshing_tree or node.data(0, ROLE_KIND) not in {"text", "grid", "artwork"}:
            return
        object_id = node.data(0, ROLE_VALUE)
        fallback_name = {"grid": "Grid", "artwork": "Artwork", "text": "Text"}[
            node.data(0, ROLE_KIND)
        ]
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
        elif isinstance(item, GridObject):
            self.controller.update_grid_object(object_id, name=name, visible=visible)
            self._preserve_generation_revision(had_current_generation)
        else:
            self.controller.update_artwork_object(object_id, name=name, visible=visible)
            self._preserve_generation_revision(had_current_generation)
        if isinstance(item, TextObject) and visibility_changed and (had_current_generation or self._regeneration_pending):
            self._schedule_regeneration("Visibility changed · updating page…")

    def _schedule_regeneration(self, message: str) -> None:
        self._regeneration_pending = True
        self._regeneration_timer.start()
        self.canvas.clear_artifacts()
        self.preview_workspace.clear()
        self.execution_workspace.clear()
        self.generated_result = None
        self.generated_revision = None
        self.generated_source_hash = None
        self._update_export_actions()
        self._show_status(message)

    def _regenerate_after_change(self) -> None:
        if not any(isinstance(item, TextObject) and item.visible for item in self.controller.snapshot.objects):
            self.console.setPlainText("All text objects are hidden.")
            self._show_status("All text objects are hidden", timeout=4000)
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
            self._show_status(str(exc), "error", 5000)
            return
        if not moving_text:
            self._preserve_generation_revision(had_current_generation)
        elif had_current_generation or self._regeneration_pending:
            self._schedule_regeneration("Object moved · updating page…")

    def _on_canvas_object_resized(
        self,
        object_id: str,
        x_mm: float,
        y_mm: float,
        width_mm: float,
        height_mm: float,
    ) -> None:
        item = next(item for item in self.controller.snapshot.objects if item.object_id == object_id)
        had_current_generation = (
            self.generated_result is not None
            and self.generated_revision == self.controller.revision
        )
        try:
            if isinstance(item, TextObject):
                self.controller.update_text_object(
                    object_id,
                    frame_x_mm=x_mm,
                    frame_y_mm=y_mm,
                    frame_width_mm=width_mm,
                    frame_height_mm=height_mm,
                    x_mm=max(x_mm, min(item.x_mm, x_mm + width_mm - 0.01)),
                    y_mm=max(y_mm, min(item.y_mm, y_mm + height_mm - 0.01)),
                )
                if had_current_generation or self._regeneration_pending:
                    self._schedule_regeneration("Object resized · updating page…")
            elif isinstance(item, GridObject):
                self.controller.update_grid_object(
                    object_id, x_mm=x_mm, y_mm=y_mm, width_mm=width_mm, height_mm=height_mm
                )
                self._preserve_generation_revision(had_current_generation)
            else:
                self.controller.update_artwork_object(
                    object_id, x_mm=x_mm, y_mm=y_mm, width_mm=width_mm, height_mm=height_mm
                )
                self._preserve_generation_revision(had_current_generation)
        except ValueError as exc:
            self.canvas.set_object_frames(self.controller.snapshot.objects, self._selected_object_ids_copy())
            self._show_status(str(exc), "error", 5000)

    def _update_text_object(self, object_id: str, changes: dict) -> None:
        try:
            self.controller.update_text_object(object_id, **changes)
        except ValueError as exc:
            self._show_status(str(exc), "error", 5000)

    def _update_text_content(self, object_id: str, changes: dict) -> None:
        try:
            self.controller.update_text_object(
                object_id,
                undo_merge_key=f"text-content:{object_id}",
                **changes,
            )
        except ValueError as exc:
            self._show_status(str(exc), "error", 5000)

    def _update_grid_object(self, object_id: str, changes: dict) -> None:
        had_current_generation = (
            self.generated_result is not None
            and self.generated_revision == self.controller.revision
        )
        try:
            self.controller.update_grid_object(object_id, **changes)
        except ValueError as exc:
            self._show_status(str(exc), "error", 5000)
            return
        self._preserve_generation_revision(had_current_generation)

    def _update_artwork_object(self, object_id: str, changes: dict) -> None:
        had_current_generation = (
            self.generated_result is not None
            and self.generated_revision == self.controller.revision
        )
        try:
            self.controller.update_artwork_object(object_id, **changes)
        except ValueError as exc:
            self._show_status(str(exc), "error", 5000)
            return
        self._preserve_generation_revision(had_current_generation)

    def edit_notebook_template(self) -> None:
        dialog = NotebookTemplateDialog(self.controller.snapshot.notebook_template, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.controller.set_notebook_template(dialog.value())
            self._show_status("Notebook template applied · paper background stays outside plotting exports", "success", 5000)
        except ValueError as exc:
            self._show_status(str(exc), "error", 5000)
            QMessageBox.critical(self, "Invalid notebook template", str(exc))

    def export_notebook_background(self) -> None:
        template = self.controller.snapshot.notebook_template
        if template is None:
            QMessageBox.information(self, "Choose a template first", "Choose a notebook page template before exporting its background.")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export notebook background SVG", "notebook-background.svg", "SVG (*.svg)"
        )
        if not filename:
            return
        try:
            Path(filename).write_bytes(notebook_background_svg(template))
            self._show_status(f"Exported notebook background {filename}", "success", 5000)
            self.console.appendPlainText(f"Exported notebook background SVG to {filename}")
        except OSError as exc:
            self._show_status(str(exc), "error", 7000)
            QMessageBox.critical(self, "Background export failed", str(exc))

    def import_artwork_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            self._t("dialog.import_artwork"),
            "",
            "Artwork (*.svg *.png *.jpg *.jpeg *.webp *.bmp *.gif)",
        )
        if not filename:
            return
        try:
            item = import_artwork(Path(filename))
            had_current_generation = (
                self.generated_result is not None
                and self.generated_revision == self.controller.revision
            )
            self.controller.add_artwork_object(item)
            self._preserve_generation_revision(had_current_generation)
            self._selected_kind, self._selected_value = "artwork", item.object_id
            self._selected_object_ids = {item.object_id}
            self._refresh_tree(self.controller.snapshot)
            self._sync_tree_selection()
            self._show_status(
                self._t("status.artwork_imported").format(name=item.name), "success", 5000
            )
        except Exception as exc:
            self._show_status(str(exc), "error", 7000)
            QMessageBox.critical(self, self._t("dialog.import_failed"), str(exc))

    def _preserve_generation_revision(self, had_current_generation: bool) -> None:
        if had_current_generation and self.generated_result is not None:
            self.generated_revision = self.controller.revision
            self._update_export_actions()

    def _update_page(self, changes: dict) -> None:
        try:
            self.controller.update_page(**changes)
        except ValueError as exc:
            self._show_status(str(exc), "error", 5000)

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
        if selected_models and all(not isinstance(item, TextObject) for item in selected_models):
            self._preserve_generation_revision(had_current_generation)
        self._selected_object_ids.clear()
        self._selected_kind, self._selected_value = "page", None
        self._on_canvas_selection_changed(())

    def new_project(self) -> None:
        if not self._confirm_project_replacement("creating a new project"):
            return
        self._regeneration_timer.stop()
        self._regeneration_pending = False
        self._selected_object_ids.clear()
        self._selected_kind, self._selected_value = "page", None
        self.controller.reset(default_project())
        self.canvas.clear_artifacts()
        self.preview_workspace.clear()
        self.execution_workspace.clear()
        self.generated_result = None
        self.generated_revision = None
        self.generated_source_hash = None
        self._update_export_actions()
        self.console.setPlainText("New project created.")

    def open_project(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Open Handwriting Plotter Project", "", "Plotter Project (*.hplot.json)")
        if not filename:
            return
        if not self._confirm_project_replacement("opening another project"):
            return
        try:
            self._regeneration_timer.stop()
            self._regeneration_pending = False
            loaded = load_project_file(Path(filename))
            self._selected_object_ids.clear()
            self._selected_kind, self._selected_value = "page", None
            self.controller.reset(loaded.snapshot, Path(filename))
            self.canvas.clear_artifacts()
            self.preview_workspace.clear()
            self.execution_workspace.clear()
            self.generated_result = None
            self.generated_revision = None
            self.generated_source_hash = None
            self._update_export_actions()
            if loaded.generation_result is not None:
                self._display_generation_result(self.controller.revision, loaded.generation_result)
                self.console.appendPlainText(f"\nRestored generated page from {filename}")
                self._show_status("Project and generated page restored", "success", 5000)
            else:
                self.console.setPlainText(f"Opened {filename}")
                if loaded.cache_warning:
                    self.console.appendPlainText(f"Ignored invalid generated cache: {loaded.cache_warning}")
        except Exception as exc:
            self._show_status(str(exc), "error", 7000)
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
            self._show_status(f"Saved {path}", "success", 4000)
        except Exception as exc:
            self._show_status(str(exc), "error", 7000)
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
        self._start_generation_progress()
        self._show_status("Generating page…")
        self.console.setPlainText(f"Generation started for revision {revision}.")
        self.thread_pool.start(worker)

    def _generation_succeeded(self, revision: int, result) -> None:  # noqa: ANN001
        self._generation_worker = None
        self.generate_action.setEnabled(True)
        if revision != self.controller.revision:
            self.console.appendPlainText(
                f"Discarded stale result for revision {revision}; current revision is {self.controller.revision}."
            )
            self._show_status("Discarded stale generation result", "warning", 5000)
            self._finish_generation_progress("warning")
            return
        self._display_generation_result(revision, result)
        self._show_status("Generation complete", "success", 5000)
        self._finish_generation_progress("success")

    def _display_generation_result(self, revision: int, result) -> None:  # noqa: ANN001
        self.generated_result = result
        self.generated_revision = revision
        self.generated_source_hash = generation_source_hash(self.controller.snapshot)
        self._update_export_actions()
        files = result.files
        self.canvas.set_artifacts(files["page-0001.svg"], files["page-0001.preview.svg"],
                                  files["page-0001.plan.json"])
        for workspace in (self.preview_workspace, self.execution_workspace):
            workspace.set_artifacts(
                files["page-0001.svg"],
                files["page-0001.preview.svg"],
                files["page-0001.plan.json"],
                files["page-0001.gcode"],
            )
        self.canvas.set_object_overflows(result.report.get("overflow_object_ids", ()))
        self.canvas.set_preview_stale(False, self._t("canvas.preview_stale"))
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
            self._finish_generation_progress("warning")
            return
        friendly = message.replace("MISSING_GLYPH:", "The selected style is missing: ")
        self.diagnostics.setPlainText(friendly)
        self.console.setPlainText(details)
        self.output_tabs.setCurrentWidget(self.diagnostics)
        self._show_status("Generation failed — see Diagnostics", "error", 7000)
        self._finish_generation_progress("error")

    def _update_export_actions(self) -> None:
        current = self.generated_result is not None and self.generated_revision == self.controller.revision
        for action in getattr(self, "export_actions", ()):
            action.setEnabled(current)

    def _export(self, artifact: str) -> None:
        if self.generated_result is None or self.generated_revision != self.controller.revision:
            self._show_status("Generate the current project before exporting", "warning", 5000)
            QMessageBox.information(self, "Generate first", "Generate the current project before exporting.")
            return
        specifications = {
            "page-0001.svg": ("Export Production SVG", "page.svg", "SVG (*.svg)"),
            "page-0001.preview.svg": ("Export Diagnostic SVG", "page.preview.svg", "SVG (*.svg)"),
            "page-0001.png": ("Export Page Image", "page.png", "PNG image (*.png)"),
            "page-0001.gcode": ("Export Virtual G-code — Simulation Only", "page.virtual.gcode", "G-code (*.gcode *.nc)"),
            "report.json": ("Export Validation Report", "validation-report.json", "JSON (*.json)"),
        }
        title, suggestion, file_filter = specifications[artifact]
        filename, _ = QFileDialog.getSaveFileName(self, title, suggestion, file_filter)
        if not filename:
            return
        try:
            if artifact == "page-0001.png":
                export_page_png(self.generated_result, Path(filename))
            else:
                export_artifact(self.generated_result, artifact, Path(filename))
            self._show_status(f"Exported {filename}", "success", 5000)
            self.console.appendPlainText(f"Exported {artifact} to {filename}")
        except Exception as exc:
            self._show_status(str(exc), "error", 7000)
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
        docks = self._document_docks()
        visibility_keys = {
            dock.objectName(): f"main/document_docks/{dock.objectName()}/visible"
            for dock in docks
        }
        has_explicit_visibility = any(self.settings.contains(key) for key in visibility_keys.values())
        if has_explicit_visibility:
            for dock in docks:
                key = visibility_keys[dock.objectName()]
                visible = self.settings.value(
                    key,
                    dock.toggleViewAction().isChecked(),
                    type=bool,
                )
                dock.setVisible(visible)
        elif state is not None and not any(
            dock.toggleViewAction().isChecked()
            for dock in (self.project_dock, self.properties_dock, self.output_dock)
        ):
            # Older builds saved Studio's temporary all-hidden state as the
            # Document layout. Recover that state once without overriding a
            # user's explicitly persisted per-dock choices in newer builds.
            for dock in docks:
                dock.show()
        self._document_dock_visibility = {
            dock.objectName(): dock.toggleViewAction().isChecked() for dock in docks
        }
        show_travel = self.settings.value("canvas/show_travel", False, type=bool)
        show_markers = self.settings.value("canvas/show_markers", False, type=bool)
        self.travel_action.setChecked(show_travel)
        self.markers_action.setChecked(show_markers)
        self.canvas.set_show_travel(show_travel)
        self.canvas.set_show_markers(show_markers)

    def _save_window_state(self) -> None:
        docks = self._document_docks()
        if self._workspace != "document":
            visibility = self._document_dock_visibility
        else:
            visibility = {
                dock.objectName(): dock.toggleViewAction().isChecked() for dock in docks
            }
        for dock in docks:
            self.settings.setValue(
                f"main/document_docks/{dock.objectName()}/visible",
                visibility.get(dock.objectName(), True),
            )
        self.settings.setValue("main/geometry", self.saveGeometry())
        self.settings.setValue("main/state", self.saveState(1))
        self.settings.setValue("canvas/show_travel", self.travel_action.isChecked())
        self.settings.setValue("canvas/show_markers", self.markers_action.isChecked())
        self.settings.sync()

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802 - Qt API
        if not self._confirm_project_replacement("closing"):
            event.ignore()
            return
        self._save_window_state()
        event.accept()

    def _confirm_project_replacement(self, action: str) -> bool:
        """Offer to save a dirty project before an action replaces it."""

        if not self.controller.dirty:
            return True
        choice = QMessageBox.question(
            self,
            "Unsaved project",
            f"Save changes before {action}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            self.save_project()
            return not self.controller.dirty
        return True

    def _action(self, text: str, callback, shortcut=None) -> QAction:  # noqa: ANN001
        action = QAction(text, self)
        action.triggered.connect(callback)
        if shortcut is not None:
            action.setShortcut(shortcut)
        return action

    def _configure_shortcuts(self) -> None:
        specifications = (
            ("new", self.new_action, "Ctrl+N"),
            ("open", self.open_action, "Ctrl+O"),
            ("import_artwork", self.import_artwork_action, "Ctrl+Shift+I"),
            ("save", self.save_action, "Ctrl+S"),
            ("save_as", self.save_as_action, "Ctrl+Shift+S"),
            ("undo", self.undo_action, "Ctrl+Z"),
            ("redo", self.redo_action, "Ctrl+Shift+Z"),
            ("add_text", self.add_text_action, "Insert"),
            ("delete", self.delete_action, "Delete"),
            ("generate", self.generate_action, "Ctrl+Return"),
            ("fit_page", self.fit_page_action, "F"),
        )
        self._shortcut_specs = specifications
        for identifier, action, default in specifications:
            stored = self.settings.value(f"shortcuts/{identifier}", None)
            action.setShortcut(QKeySequence(str(stored) if stored is not None else default))

    def _shortcut_bindings(self) -> tuple[ShortcutBinding, ...]:
        return tuple(
            ShortcutBinding(identifier, action.text(), action, default)
            for identifier, action, default in self._shortcut_specs
        )

    def _show_controls(self) -> None:
        dialog = ControlsDialog(self._shortcut_bindings(), language=self.language, parent=self)
        dialog.exec()

    def _show_program_settings(self) -> None:
        dialog = ProgramSettingsDialog(
            self._shortcut_bindings(), language=self.language, parent=self
        )
        if dialog.exec() != ProgramSettingsDialog.DialogCode.Accepted:
            return
        for identifier, sequence in dialog.shortcut_values().items():
            action = next(action for key, action, _default in self._shortcut_specs if key == identifier)
            action.setShortcut(sequence)
            self.settings.setValue(
                f"shortcuts/{identifier}",
                sequence.toString(QKeySequence.SequenceFormat.PortableText),
            )
        if dialog.reset_layout_requested:
            self._reset_dock_layout()
        self.settings.sync()
        self.set_language(dialog.selected_language)

    def _reset_dock_layout(self) -> None:
        self.set_workspace("document")
        for dock in self._document_docks():
            dock.setFloating(False)
            dock.show()
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.project_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.project_tools_dock)
        self.splitDockWidget(self.project_dock, self.project_tools_dock, Qt.Orientation.Vertical)
        self.splitDockWidget(self.project_tools_dock, self.editing_tools_dock, Qt.Orientation.Vertical)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.properties_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, self.modes_dock)
        self.splitDockWidget(self.modes_dock, self.view_tools_dock, Qt.Orientation.Horizontal)
        self.resizeDocks(
            [self.project_dock, self.properties_dock], [275, 340], Qt.Orientation.Horizontal
        )
        self.resizeDocks([self.output_dock], [200], Qt.Orientation.Vertical)
        self._document_dock_visibility = {
            dock.objectName(): True for dock in self._document_docks()
        }
        self.settings.remove("main/state")
        self.settings.remove("main/geometry")
        self.settings.remove("main/document_docks")

    def _about(self) -> None:
        QMessageBox.about(
            self,
            self._t("about.title"),
            self._t("about.body").format(
                version=__version__,
                styles=len(tuple(style for style in self.styles if style.valid)),
            ),
        )
