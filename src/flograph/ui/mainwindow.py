from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QEventLoop, QPoint, QPointF, QRectF, QSettings, Qt, QThreadPool, QTimer,
)
from PySide6.QtGui import QAction, QColor, QKeySequence, QUndoStack
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QDockWidget, QFileDialog,
    QInputDialog, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QProgressDialog, QStackedWidget, QTextEdit,
    QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from flograph.core import (
    Graph, GraphError, NodeInstance, NodeRegistry, NodeStatus, Page, Tile,
    parse_spec,
)
from flograph.core import serialization
from flograph.core import user_nodes
from flograph.engine import (
    CacheLoadRunnable, CacheLoadSignals, ExecutionEngine, cache_persistence,
)
from flograph.paths import user_nodes_dir

from .commands import (
    AddNodeCommand, AddPageCommand, AddTileCommand, ConnectCommand,
    DuplicatePageCommand, RemovePageCommand, RenamePageCommand,
    ReorderPagesCommand, SetPageColorCommand,
    SetLabelCommand, SetParamCommand, SetPreviewEnabledCommand,
)
from .canvas import ConnectionItem, NodeGraphScene, NodeGraphView
from .canvas.file_drop import resolve_dropped_file
from .canvas import grid
from .canvas.node_item import (
    DEFAULT_LOD_THRESHOLD, PREVIEW_TOGGLABLE_KINDS, card_kind,
)
from .canvas.palette import LibraryPanel, NodePalettePopup
from .dashboard import (
    DashboardPage, PageTabBar, default_tile_port, default_tile_size,
    is_tile_able,
)
from .console.log_dock import LogConsole
from .editor.editor_dock import EditorPanel
from .editor.save_user_node_dialog import SaveUserNodeDialog
from .inspector.inspector_dock import InspectorPanel
from .properties.params_panel import ParamsPanel
from .resource_monitor import ResourceMonitorWidget
from .settings_dialog import SettingsDialog
from . import theme

MAX_RECENT = 8
PASTE_OFFSET = 30.0
_CLIPBOARD_KEY = "flograph_clipboard"


class MainWindow(QMainWindow):
    def __init__(self, registry: NodeRegistry) -> None:
        super().__init__()
        self.registry = registry
        self.graph = Graph()
        self.undo_stack = QUndoStack(self)
        self.scene = NodeGraphScene(self.graph, self.undo_stack,
                                    registry=registry, parent=self)
        self.view = NodeGraphView(self.scene)
        self._canvas_stack = QStackedWidget()
        self._canvas_stack.addWidget(self.view)
        self.page_bar = PageTabBar()
        # docks/toolbars need a real QMainWindow, but the page bar has to
        # live outside that dock system entirely (see _apply_page_bar_position)
        # -- so the docks+canvas live in this nested QMainWindow, and it plus
        # the page bar are arranged in the outer window's central widget.
        self._dock_host = QMainWindow(self)
        self._dock_host.setDockOptions(
            QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks)
        self._dock_host.setCentralWidget(self._canvas_stack)
        self._dashboard_pages: dict[str, DashboardPage] = {}
        self._restoring_pages = False
        self.engine = ExecutionEngine(self.graph, parent=self)
        self.settings = QSettings("flograph", "flograph")
        self._project_path: Optional[str] = None
        self._cache_load_signals: Optional[CacheLoadSignals] = None
        # set False to close without the unsaved-changes prompt (tests, scripts)
        self.confirm_close = True
        self._gpu_viewport_checked_on_show = False
        self._settings_dialog: Optional[SettingsDialog] = None

        self.lod_enabled = self.settings.value("canvas/lod_enabled", True, type=bool)
        self.lod_threshold = self.settings.value(
            "canvas/lod_threshold", DEFAULT_LOD_THRESHOLD, type=float)
        self._apply_lod_settings()
        self.page_bar_position = self.settings.value(
            "canvas/page_bar_position", "top", type=str)
        if self.page_bar_position not in ("top", "bottom"):
            self.page_bar_position = "top"
        self.snap_enabled = self.settings.value("snap/enabled", True, type=bool)
        self.grid_step = float(
            self.settings.value("snap/step", grid.DEFAULT_STEP))
        self._apply_snap_settings()
        self.minimap_enabled = self.settings.value(
            "canvas/minimap_enabled", True, type=bool)
        self.view.minimap.setVisible(self.minimap_enabled)
        self.tint_soft = self.settings.value(
            "canvas/tint_soft", theme.DEFAULT_TINT_SOFT, type=float)
        self.tint_strong = self.settings.value(
            "canvas/tint_strong", theme.DEFAULT_TINT_STRONG, type=float)
        theme.set_tints(self.tint_soft, self.tint_strong)

        self._palette_popup = NodePalettePopup(registry, self)
        self._palette_scene_pos = QPointF()
        self._pending_wire = None
        self._palette_popup.chosen.connect(self._add_node_from_palette)

        self._build_docks()
        self._build_actions()
        self._wire_engine()
        self._wire_canvas()
        self._wire_pages()
        # bound method (not a lambda): Qt auto-disconnects it on deletion
        self.undo_stack.cleanChanged.connect(self._on_clean_changed)
        self._zoom_indicator = QToolButton(self)
        self._zoom_indicator.setAutoRaise(True)
        self._zoom_indicator.setText("100%")
        self._zoom_indicator.setToolTip(
            "Canvas zoom — click to reset to 100%")
        self._zoom_indicator.clicked.connect(
            lambda: self._active_canvas_view().set_zoom(1.0))
        self.view.zoom_changed.connect(self._on_canvas_zoom_changed)
        self.statusBar().addPermanentWidget(self._zoom_indicator)
        self._update_title()
        self._restore_window_state()
        self._on_current_page_changed(self.page_bar.current_page_id())
        self.resource_monitor = ResourceMonitorWidget(self.engine, self)
        self.statusBar().addPermanentWidget(self.resource_monitor)
        self.statusBar().showMessage("Ready")

    def _active_canvas_view(self):
        """The zoom-pan view of whatever page is showing: the model canvas,
        or the active dashboard page's view."""
        widget = self._canvas_stack.currentWidget()
        return getattr(widget, "view", None) or self.view

    def _on_canvas_zoom_changed(self, zoom: float) -> None:
        # every page's view reports here; only the visible one drives the label
        if self.sender() is self._active_canvas_view():
            self._zoom_indicator.setText(f"{round(zoom * 100)}%")

    def _refresh_zoom_indicator(self) -> None:
        self._zoom_indicator.setText(
            f"{round(self._active_canvas_view().zoom * 100)}%")

    # ---------------------------------------------------------------- docks

    def _build_docks(self) -> None:
        host = self._dock_host
        self.library_panel = LibraryPanel(self.registry)
        # a floor, not just a fresh-install default: restoreState() below
        # can only shrink a dock down to its widget's minimum, so this also
        # rescues anyone whose saved layout already pinned it thin.
        self.library_panel.setMinimumWidth(180)
        self.library_tree = self.library_panel.tree
        self.library_dock = QDockWidget("Node Library", host)
        self.library_dock.setObjectName("dock_library")
        self.library_dock.setWidget(self.library_panel)
        host.addDockWidget(Qt.LeftDockWidgetArea, self.library_dock)
        self.library_tree.add_requested.connect(self._add_node_at_view_center)
        self.library_tree.new_group_requested.connect(self._new_user_group)
        self.library_tree.rename_user_node_requested.connect(
            self._rename_user_node)
        self.library_tree.move_user_node_requested.connect(self._move_user_node)
        self.library_tree.delete_user_node_requested.connect(
            self._delete_user_node)

        self.params_panel = ParamsPanel(self.graph, self.undo_stack,
                                        cache=self.engine.cache)
        self.properties_dock = QDockWidget("Properties", host)
        self.properties_dock.setObjectName("dock_properties")
        self.properties_dock.setWidget(self.params_panel)
        host.addDockWidget(Qt.RightDockWidgetArea, self.properties_dock)

        self.editor_panel = EditorPanel(self.graph, self.undo_stack, self.registry)
        self.editor_panel.save_as_user_node_requested.connect(
            self._save_as_user_node)
        self.editor_dock = QDockWidget("Code", host)
        self.editor_dock.setObjectName("dock_editor")
        self.editor_dock.setWidget(self.editor_panel)
        host.addDockWidget(Qt.RightDockWidgetArea, self.editor_dock)
        host.tabifyDockWidget(self.properties_dock, self.editor_dock)
        self.properties_dock.raise_()
        host.resizeDocks([self.properties_dock], [420], Qt.Horizontal)

        self.inspector_panel = InspectorPanel(self.graph, self.engine)
        self.inspector_dock = QDockWidget("Inspector", host)
        self.inspector_dock.setObjectName("dock_inspector")
        self.inspector_dock.setWidget(self.inspector_panel)
        host.addDockWidget(Qt.BottomDockWidgetArea, self.inspector_dock)

        self.log_console = LogConsole(self.graph, self.engine)
        self.log_dock = QDockWidget("Log", host)
        self.log_dock.setObjectName("dock_log")
        self.log_dock.setWidget(self.log_console)
        host.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
        host.tabifyDockWidget(self.inspector_dock, self.log_dock)
        self.inspector_dock.raise_()
        host.resizeDocks([self.inspector_dock], [260], Qt.Vertical)

        self._apply_page_bar_position(self.page_bar_position)

    def set_page_bar_position(self, position: str) -> None:
        if position not in ("top", "bottom"):
            return
        if position == self.page_bar_position:
            return
        self.page_bar_position = position
        self.settings.setValue("canvas/page_bar_position", position)
        self._apply_page_bar_position(position)

    def _apply_page_bar_position(self, position: str) -> None:
        """Arrange the page bar (the page switcher -- stays put and
        full-size even when every other dock is hidden, e.g. on a dashboard
        page) against the given edge of the *window*, with the dock host
        (canvas + every other dock) filling the rest.

        This is deliberately a plain QBoxLayout, not another dock: a
        QDockWidget here would need to sit in the *same* dock area as
        Inspector/Log or Properties/Code to reach the window edge, and
        splitDockWidget() against an anchor that already has a tab group
        reliably corrupts that group the first time it's called more than
        once on the same anchor (verified empirically -- not a timing or
        ordering issue, a real limitation). A plain layout has no such
        failure mode, and also has no resize handle to fight with -- a
        boxed-in widget with a stretch-0 layout slot just can't be dragged.

        Only top/bottom are supported -- left/right (vertical, rotated-label)
        was pulled after the rotated text couldn't be made to render reliably
        centered on real screens (offscreen pixel-grab tests kept passing
        while the user still saw it broken, so trust the user's eyes over
        that harness here)."""
        old_container = self.centralWidget()
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        ordered = ([self.page_bar, self._dock_host] if position == "top"
                  else [self._dock_host, self.page_bar])
        for widget in ordered:
            layout.addWidget(widget, 1 if widget is self._dock_host else 0)
        self.setCentralWidget(container)
        if old_container is not None:
            old_container.deleteLater()

    # -------------------------------------------------------------- actions

    def _build_actions(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setObjectName("toolbar_main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        def act(text: str, shortcut, slot, menu_only: bool = True) -> QAction:
            action = QAction(text, self)
            if shortcut is not None:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            return action

        # --- file
        self.action_new = act("&New", QKeySequence.New, self._new_project)
        self.action_open = act("&Open…", QKeySequence.Open, self._open_dialog)
        self.action_save = act("&Save", QKeySequence.Save, self._save)
        self.action_save_as = act("Save &As…", QKeySequence("Ctrl+Shift+S"),
                                  self._save_as)
        self.action_quit = act("&Quit", QKeySequence.Quit, self.close)

        # --- edit (focus-aware so the code editor keeps its own undo/copy)
        self.action_undo = act("Undo", QKeySequence.Undo,
                               lambda: self._smart_edit("undo", self.undo_stack.undo))
        self.action_redo = act("Redo", QKeySequence.Redo,
                               lambda: self._smart_edit("redo", self.undo_stack.redo))
        self.action_cut = act("Cut", QKeySequence.Cut,
                              lambda: self._smart_edit("cut", self._cut_selection))
        self.action_copy = act("Copy", QKeySequence.Copy,
                               lambda: self._smart_edit("copy", self._copy_selection))
        self.action_paste = act("Paste", QKeySequence.Paste,
                                lambda: self._smart_edit("paste", self._paste))
        self.action_duplicate = act("Duplicate", QKeySequence("Ctrl+D"),
                                    self._duplicate)
        self.action_rename = act("Rename Node", Qt.Key_F2, self._rename_selected)
        self.action_select_all = act(
            "Select All", None,
            lambda: [i.setSelected(True) for i in self.scene.node_items.values()])
        self.action_add_frame = act("Add Frame", QKeySequence("Ctrl+G"),
                                    self._add_frame)
        self.action_align_left = act("Align Left", None,
                                     lambda: self._align("left"))
        self.action_align_top = act("Align Top", None,
                                    lambda: self._align("top"))
        self.action_dist_h = act("Distribute Horizontally", None,
                                 lambda: self._align("dist_h"))
        self.action_dist_v = act("Distribute Vertically", None,
                                 lambda: self._align("dist_v"))

        # --- run
        self.action_run = act("Run All", Qt.Key_F5, self.engine.run_all)
        self.action_run_selected = act("Run Selected", Qt.Key_F6,
                                       self._run_selected)
        self.action_cancel = act("Cancel", Qt.Key_Escape, self.engine.cancel)
        self.action_cancel.setEnabled(False)
        self.action_reset_caches = act("Reset Caches", None, self._reset_caches)

        # --- tools
        self.action_settings = act("&Settings…", QKeySequence("Ctrl+,"),
                                   self._show_settings)
        self.action_packages = act("Manage &Packages…", None,
                                   self._show_packages)
        self.action_ai_settings = act("AI Assistant &Settings…", None,
                                      self._show_ai_settings)

        for action in (self.action_run, self.action_run_selected,
                       self.action_cancel):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self.action_undo)
        toolbar.addAction(self.action_redo)

        file_menu = self.menuBar().addMenu("&File")
        for action in (self.action_new, self.action_open, self.action_save,
                       self.action_save_as):
            file_menu.addAction(action)
        self._recent_menu = file_menu.addMenu("Open &Recent")
        self._rebuild_recent_menu()
        self._build_examples_menu(file_menu)
        file_menu.addSeparator()
        file_menu.addAction(self.action_quit)

        edit_menu = self.menuBar().addMenu("&Edit")
        for action in (self.action_undo, self.action_redo):
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        for action in (self.action_cut, self.action_copy, self.action_paste,
                       self.action_duplicate, self.action_rename,
                       self.action_select_all):
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_add_frame)
        align_menu = edit_menu.addMenu("Align")
        for action in (self.action_align_left, self.action_align_top,
                       self.action_dist_h, self.action_dist_v):
            align_menu.addAction(action)

        run_menu = self.menuBar().addMenu("&Run")
        for action in (self.action_run, self.action_run_selected,
                       self.action_cancel, self.action_reset_caches):
            run_menu.addAction(action)

        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.addAction(self.action_settings)
        tools_menu.addSeparator()
        tools_menu.addAction(self.action_packages)
        tools_menu.addAction(self.action_ai_settings)

        view_menu = self.menuBar().addMenu("&View")
        for dock in self.findChildren(QDockWidget):
            view_menu.addAction(dock.toggleViewAction())

        # GPU-Accelerated Canvas lives in Tools > Settings… (SettingsDialog),
        # not directly in a menu — this QAction is just its state/signal
        # holder, reused as-is by the dialog's checkbox.
        self.action_gpu_viewport = QAction("GPU-Accelerated Canvas (experimental)", self)
        self.action_gpu_viewport.setCheckable(True)
        self.action_gpu_viewport.setToolTip(
            "Render the canvas through an OpenGL viewport instead of "
            "software rasterizing — off by default. If a card (figure, "
            "table, webview) looks wrong after enabling, switch it back "
            "off here; it also falls back on its own if this machine "
            "can't actually provide GL.")
        self.action_gpu_viewport.setChecked(
            self.settings.value("canvas/gpu_viewport", False, type=bool))
        self.action_gpu_viewport.toggled.connect(self._on_gpu_viewport_toggled)
        self._apply_gpu_viewport_setting()

    def set_snap_enabled(self, enabled: bool) -> None:
        self.snap_enabled = enabled
        self.settings.setValue("snap/enabled", enabled)
        self._apply_snap_settings()

    def set_grid_step(self, step: float) -> None:
        self.grid_step = step
        self.settings.setValue("snap/step", step)
        self._apply_snap_settings()

    def set_minimap_enabled(self, enabled: bool) -> None:
        self.minimap_enabled = enabled
        self.settings.setValue("canvas/minimap_enabled", enabled)
        self.view.minimap.setVisible(enabled)

    def set_tints(self, soft: float, strong: float) -> None:
        """Retune how strongly user-picked colours are muted against the
        theme, and repaint everything that renders one."""
        self.tint_soft, self.tint_strong = soft, strong
        self.settings.setValue("canvas/tint_soft", soft)
        self.settings.setValue("canvas/tint_strong", strong)
        theme.set_tints(soft, strong)
        self._repaint_tinted()

    def _repaint_tinted(self) -> None:
        """Node cards and the minimap live on the canvas; the page tabs are a
        plain widget. Both have to be told, or half the window keeps the old
        muting until something else happens to invalidate it."""
        views = [self.view] + [page.view for page in self._dashboard_pages.values()]
        for view in views:
            view.viewport().update()
        self.view.minimap.update()
        self.page_bar.update()

    def _apply_snap_settings(self) -> None:
        """Push the current snap toggle/step onto every scene and repaint so
        the grid redraws at the new resolution. Applies to node/frame moves
        and resizes on the canvas and dashboard tiles."""
        views = [self.view]
        scenes = [self.scene]
        for page in self._dashboard_pages.values():
            scenes.append(page.scene)
            views.append(page.view)
        for scene in scenes:
            scene.snap_enabled = self.snap_enabled
            scene.grid_step = self.grid_step
        for view in views:
            view.viewport().update()

    @staticmethod
    def _set_canvas_viewport(view, use_gl: bool) -> None:
        view.setViewport(QOpenGLWidget() if use_gl else QWidget())

    def _on_gpu_viewport_toggled(self, checked: bool) -> None:
        self.settings.setValue("canvas/gpu_viewport", checked)
        self._apply_gpu_viewport_setting()
        # the window is already on screen by the time a user can click this
        # menu action, so a real paint (and thus a GL context, if any) is
        # only ever a repaint() away — safe to verify right now.
        if checked and self.isVisible():
            self._verify_gpu_viewport_soon()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # A GL context is only created on first paint, so verifying a
        # persisted-on setting has to wait for the window to actually be
        # shown — checking during __init__ would see no context yet on a
        # perfectly capable machine and wrongly conclude GL is unavailable.
        if not self._gpu_viewport_checked_on_show:
            self._gpu_viewport_checked_on_show = True
            if self.action_gpu_viewport.isChecked():
                self._verify_gpu_viewport_soon()

    def _apply_gpu_viewport_setting(self) -> None:
        """Push the GPU-viewport toggle onto every canvas view (modeling
        canvas + dashboard pages). Swaps the viewport widget only — whether
        it actually took effect is confirmed separately, see
        _verify_gpu_viewport_soon, since that requires the window to be
        visible. If setViewport itself raises, revert immediately: an
        environment that can't even construct a GL widget should never get
        stuck with a broken canvas just because the setting was on from a
        previous session."""
        enabled = self.action_gpu_viewport.isChecked()
        views = [self.view] + [page.view for page in self._dashboard_pages.values()]
        try:
            for view in views:
                self._set_canvas_viewport(view, enabled)
        except Exception:
            self.action_gpu_viewport.blockSignals(True)
            self.action_gpu_viewport.setChecked(False)
            self.action_gpu_viewport.blockSignals(False)
            self.settings.setValue("canvas/gpu_viewport", False)
            for view in views:
                self._set_canvas_viewport(view, False)
        # setViewport() installs a brand new viewport widget, which lands on
        # top of the minimap (a sibling overlay, not a viewport child) in
        # stacking order — without this it's invisible behind the viewport
        # every time this runs, including the unconditional startup call.
        self.view.minimap.raise_()

    def _verify_gpu_viewport_soon(self) -> None:
        """Force a synchronous paint (so a QOpenGLWidget viewport actually
        gets the chance to create its context via initializeGL) before
        checking it a tick later."""
        self.view.viewport().repaint()
        QTimer.singleShot(0, self._verify_gpu_viewport)

    def _verify_gpu_viewport(self) -> None:
        """Confirms the main view actually got a working GL context
        (headless/software-only setups silently fail to, without raising)
        and falls back to the raster viewport if not. This only catches
        "no GL at all" — visual glitches from a GL viewport compositing the
        embedded proxy widgets (figure/table/webview cards) incorrectly, if
        any, aren't detectable this way; that's why the setting stays opt-in
        rather than a guarantee nothing can go wrong."""
        if not self.action_gpu_viewport.isChecked():
            return  # toggled off again before this fired
        viewport = self.view.viewport()
        context = viewport.context() if isinstance(viewport, QOpenGLWidget) else None
        if context is not None and context.isValid():
            return
        self.action_gpu_viewport.setChecked(False)  # -> reverts + persists off
        self.statusBar().showMessage(
            "GPU acceleration isn't available here — reverted to standard "
            "rendering.", 6000)

    # -------------------------------------------------------- zoom-out LOD

    def set_lod_enabled(self, enabled: bool) -> None:
        self.lod_enabled = enabled
        self.settings.setValue("canvas/lod_enabled", enabled)
        self._apply_lod_settings()

    def set_lod_threshold(self, threshold: float) -> None:
        self.lod_threshold = threshold
        self.settings.setValue("canvas/lod_threshold", threshold)
        self._apply_lod_settings()

    def _apply_lod_settings(self) -> None:
        """Push lod_enabled/lod_threshold onto every scene that supports the
        LOD protocol and re-apply immediately against the current zoom, so a
        Settings-dialog change takes effect without needing to zoom. Only
        NodeGraphScene (the modeling canvas) implements it — DashboardScene
        (report pages) shows tiles, not nodes, and has no LOD concept."""
        scenes = [self.scene] + [page.scene for page in self._dashboard_pages.values()]
        for scene in scenes:
            if not hasattr(scene, "refresh_lod_settings"):
                continue
            scene.lod_enabled = self.lod_enabled
            scene.lod_threshold = self.lod_threshold
            scene.refresh_lod_settings()

    def _smart_edit(self, text_method: str, canvas_fn) -> None:
        """Route Ctrl+Z/X/C/V to the focused text widget when there is one,
        to a focused spreadsheet grid for cut/copy/paste, and to the canvas
        otherwise."""
        widget = QApplication.focusWidget()
        if isinstance(widget, (QPlainTextEdit, QTextEdit, QLineEdit)):
            getattr(widget, text_method)()
            return
        grid = self._focused_spreadsheet()
        if grid is not None and text_method in ("cut", "copy", "paste"):
            {"cut": grid.cut_selection, "copy": grid.copy_selection,
             "paste": grid.paste_clipboard}[text_method]()
            return
        canvas_fn()

    @staticmethod
    def _focused_spreadsheet():
        """The SpreadsheetView owning focus (itself or an ancestor of the
        focus widget), or None."""
        from .spreadsheet import SpreadsheetView
        widget = QApplication.focusWidget()
        while widget is not None:
            if isinstance(widget, SpreadsheetView):
                return widget
            widget = widget.parentWidget()
        return None

    # --------------------------------------------------------------- wiring

    def _wire_engine(self) -> None:
        engine = self.engine

        def on_started() -> None:
            self.action_cancel.setEnabled(True)
            self.action_run.setEnabled(False)
            self.action_run_selected.setEnabled(False)
            self.statusBar().showMessage("Running…")

        def on_finished(ok: bool) -> None:
            self.action_cancel.setEnabled(False)
            self.action_run.setEnabled(True)
            self.action_run_selected.setEnabled(True)
            self.statusBar().showMessage(
                "Run finished" if ok else "Run finished with errors", 5000)

        engine.run_started.connect(on_started)
        engine.run_finished.connect(on_finished)
        engine.node_failed.connect(self._on_node_failed)
        engine.node_succeeded.connect(self.editor_panel.on_node_succeeded)
        engine.node_succeeded.connect(self._on_figure_node_succeeded)
        engine.node_succeeded.connect(self._on_plotly_node_succeeded)
        engine.node_succeeded.connect(self._on_table_viewer_node_succeeded)
        engine.node_succeeded.connect(self._on_grid_node_succeeded)
        engine.node_succeeded.connect(self._on_kpi_node_succeeded)
        engine.node_succeeded.connect(self._on_slicer_node_succeeded)
        self.graph.events.preview_enabled_changed.connect(
            self._on_preview_enabled_changed)

    def _wire_canvas(self) -> None:
        self.view.add_node_requested.connect(self._show_add_node_menu)
        self.view.palette_requested.connect(self._show_palette)
        self.view.node_dropped.connect(self._add_node_at)
        self.view.files_dropped.connect(self._add_reader_nodes_for_files)
        self.view.node_context_requested.connect(self._show_node_menu)
        self.view.frame_context_requested.connect(self._show_frame_menu)
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.scene.node_double_clicked.connect(self._on_node_double_clicked)
        self.scene.node_rename_requested.connect(self._rename_node)
        self.scene.wire_dropped.connect(self._on_wire_dropped)
        self.scene.button_fired.connect(self._on_button_fired)
        self.scene.slicer_changed.connect(self._on_slicer_changed)
        self.scene.frame_run_requested.connect(self._on_frame_run_requested)

    def _on_figure_node_succeeded(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "figure":
            return
        if not node.canvas_preview_enabled:
            return
        item = self.scene.node_items.get(node_id)
        if item is None:
            return
        entry = self.engine.cache.get(node_id)
        item.set_figure(entry.outputs.get("figure") if entry else None)

    def _on_plotly_node_succeeded(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "webview":
            return
        if not node.canvas_preview_enabled:
            return
        item = self.scene.node_items.get(node_id)
        if item is None:
            return
        entry = self.engine.cache.get(node_id)
        # a webview node's rendered output is its first declared output port
        port = node.spec.outputs[0].name if node.spec.outputs else "figure"
        item.set_plotly_figure(entry.outputs.get(port) if entry else None)

    def _on_table_viewer_node_succeeded(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "table_viewer":
            return
        if not node.canvas_preview_enabled:
            return
        item = self.scene.node_items.get(node_id)
        if item is None:
            return
        entry = self.engine.cache.get(node_id)
        # first output holds the displayed frame: "table" for Show Table,
        # "spec" for Table Spec
        port = node.spec.outputs[0].name if node.spec.outputs else "table"
        item.set_table_data(entry.outputs.get(port) if entry else None)

    def _on_grid_node_succeeded(self, node_id: str) -> None:
        """After a linked Table run, show the merged sheet on the card:
        input-owned columns refreshed, the user's own columns (formula
        sources intact) carried over."""
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "grid":
            return
        item = self.scene.node_items.get(node_id)
        merged = self._merged_linked_sheet(node_id)
        if item is not None and merged is not None:
            item.show_linked_sheet(merged)

    def _merged_linked_sheet(self, node_id: str):
        """The linked-refresh merge of a Table node's cached input with its
        stored sheet, as a sheet dict — None when there's no usable input."""
        from flograph.core.sheet import (merge_linked_sheet, parse_sheet,
                                         sheet_from_dataframe, sheet_to_dict)
        frame = self._table_import_source(node_id)
        if frame is None:
            return None
        node = self.graph.nodes[node_id]
        merged = merge_linked_sheet(sheet_from_dataframe(frame),
                                    parse_sheet(node.params.get("data")))
        return sheet_to_dict(merged)

    def _table_import_source(self, node_id: str):
        """The cached upstream DataFrame feeding a Table node's input, or
        None when unconnected / not run / not a frame."""
        conn = self.graph.input_connection(node_id, "table")
        if conn is None:
            return None
        entry = self.engine.cache.get(conn.src_node)
        value = entry.outputs.get(conn.src_port) if entry else None
        return value if hasattr(value, "itertuples") else None

    def _import_input_into_table(self, node_id: str) -> None:
        """Snapshot the linked data into the node's stored sheet (keeping
        the user's own columns), one undoable step."""
        import json as _json
        merged = self._merged_linked_sheet(node_id)
        if merged is None:
            return
        self.undo_stack.push(SetParamCommand(
            self.graph, node_id, "data", _json.dumps(merged), merge=False))
        self.statusBar().showMessage(
            "Input copied into the table — disconnect the input to make "
            "this snapshot fully yours", 5000)

    def _on_kpi_node_succeeded(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "kpi":
            return
        item = self.scene.node_items.get(node_id)
        if item is None:
            return
        entry = self.engine.cache.get(node_id)
        if entry is None:
            item.set_card_value(None, has_value=False)
        else:
            item.set_card_value(entry.outputs.get("value"))

    def _on_slicer_node_succeeded(self, node_id: str) -> None:
        """Populate the slicer's checkbox list with the column's unique
        values, read from the *upstream* cache — the slicer's own output is
        already filtered, so it can't be the source of the options."""
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "slicer":
            return
        if not node.canvas_preview_enabled:
            return
        item = self.scene.node_items.get(node_id)
        if item is None:
            return
        from flograph.engine.introspect import slicer_options
        item.set_slicer_options(
            slicer_options(self.graph, self.engine.cache, node_id))

    def _on_preview_enabled_changed(self, node_id: str, enabled: bool) -> None:
        if enabled:
            self._refresh_node_card(node_id)  # repopulate from cache, no re-run

    def _refresh_node_card(self, node_id: str) -> None:
        """Push the last-known cached output into this node's embedded
        preview widget — shared by the *_node_succeeded handlers (via
        engine.node_succeeded) and by re-enabling a disabled preview, so
        re-enable never forces a re-run."""
        node = self.graph.nodes.get(node_id)
        if node is None:
            return
        kind = card_kind(node)
        if kind == "figure":
            self._on_figure_node_succeeded(node_id)
        elif kind == "webview":
            self._on_plotly_node_succeeded(node_id)
        elif kind == "table_viewer":
            self._on_table_viewer_node_succeeded(node_id)
        elif kind == "slicer":
            self._on_slicer_node_succeeded(node_id)

    # ------------------------------------------------------ dashboard pages

    def _wire_pages(self) -> None:
        events = self.graph.events
        events.page_added.connect(self._on_page_added)
        events.page_removed.connect(self._on_page_removed)
        events.page_changed.connect(self._on_page_changed)
        events.pages_reordered.connect(self._on_pages_reordered)
        self.page_bar.add_page_requested.connect(self._add_page)
        self.page_bar.rename_page_requested.connect(self._rename_page)
        self.page_bar.delete_page_requested.connect(self._delete_page)
        self.page_bar.duplicate_page_requested.connect(self._duplicate_page)
        self.page_bar.reorder_pages_requested.connect(self._reorder_pages)
        self.page_bar.recolor_page_requested.connect(self._recolor_page)
        self.page_bar.current_page_changed.connect(
            self._on_current_page_changed)

    def _on_page_added(self, page: Page) -> None:
        widget = DashboardPage(self.graph, self.engine, self.undo_stack,
                               page.id)
        widget.scene.button_fired.connect(self._on_button_fired)
        widget.scene.slicer_changed.connect(self._on_slicer_changed)
        widget.view.tile_dropped.connect(
            lambda node_id, pos, page_id=page.id:
            self._on_tile_dropped(page_id, node_id, pos))
        self._dashboard_pages[page.id] = widget
        widget.view.zoom_changed.connect(self._on_canvas_zoom_changed)
        widget.scene.snap_enabled = self.snap_enabled
        widget.scene.grid_step = self.grid_step
        self._set_canvas_viewport(widget.view, self.action_gpu_viewport.isChecked())
        self._canvas_stack.addWidget(widget)
        self.page_bar.add_page_tab(page)

    def _on_page_removed(self, page_id: str) -> None:
        widget = self._dashboard_pages.pop(page_id, None)
        if widget is not None:
            widget.dispose()  # before deletion: core events hold strong refs
            self._canvas_stack.removeWidget(widget)
            widget.deleteLater()
        self.page_bar.remove_page_tab(page_id)

    def _on_page_changed(self, page: Page) -> None:
        self.page_bar.set_page_title(page.id, page.title)
        self.page_bar.set_page_color(page.id, page.color)

    def _on_pages_reordered(self, order: list[str]) -> None:
        self.page_bar.set_page_order(order)

    def _on_current_page_changed(self, page_id) -> None:
        widget = self._dashboard_pages.get(page_id) if page_id else None
        self._canvas_stack.setCurrentWidget(
            widget if widget is not None else self.view)
        # dashboard/report pages have no node selection to configure, so free
        # up the screen by hiding the model-only docks
        is_model_page = page_id is None
        self.library_dock.setVisible(is_model_page)
        self.properties_dock.setVisible(is_model_page)
        self.editor_dock.setVisible(is_model_page)
        self.inspector_dock.setVisible(is_model_page)
        self.log_dock.setVisible(is_model_page)
        self._refresh_zoom_indicator()
        if self._project_path and not self._restoring_pages:
            self.settings.setValue(f"active_page/{self._project_path}",
                                   page_id or "")

    def _add_page(self) -> None:
        page = Page(id=uuid.uuid4().hex, title=self._next_page_title())
        self.undo_stack.push(AddPageCommand(self.graph, page))
        self.page_bar.select_page(page.id)

    def _next_page_title(self) -> str:
        titles = {p.title for p in self.graph.pages.values()}
        n = len(self.graph.pages) + 1
        while f"Page {n}" in titles:
            n += 1
        return f"Page {n}"

    def _rename_page(self, page_id: str, title: str) -> None:
        page = self.graph.pages.get(page_id)
        if page is not None and title != page.title:
            self.undo_stack.push(RenamePageCommand(self.graph, page_id, title))

    def _recolor_page(self, page_id: str, color) -> None:
        page = self.graph.pages.get(page_id)
        if page is not None and page.color != color:
            self.undo_stack.push(SetPageColorCommand(self.graph, page_id, color))

    def _reorder_pages(self, order: list[str]) -> None:
        current = list(self.graph.pages)
        if sorted(order) != sorted(current):
            self.page_bar.set_page_order(current)  # bar drifted; re-sync from graph
            return
        if order != current:
            self.undo_stack.push(ReorderPagesCommand(self.graph, order))

    def _duplicate_page(self, page_id: str) -> None:
        self.undo_stack.push(DuplicatePageCommand(self.graph, page_id))
        dup = self.graph.pages[self._last_duped_id]
        self.page_bar.select_page(dup.id)

    @property
    def _last_duped_id(self) -> str:
        return list(self.graph.pages.keys())[-1]

    def _delete_page(self, page_id: str) -> None:
        page = self.graph.pages.get(page_id)
        if page is None:
            return
        if page.tiles:
            answer = QMessageBox.question(
                self, "Delete page",
                f"Delete page “{page.title}” and its {len(page.tiles)} "
                f"tile(s)?")
            if answer != QMessageBox.Yes:
                return
        self.undo_stack.push(RemovePageCommand(self.graph, page_id))

    def _on_tile_dropped(self, page_id: str, node_id: str,
                         scene_pos: QPointF) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None or page_id not in self.graph.pages:
            return
        width, height = default_tile_size(node)
        tile = Tile(id=uuid.uuid4().hex, node_id=node_id,
                    port=default_tile_port(node),
                    rect=(scene_pos.x(), scene_pos.y(), width, height))
        self.undo_stack.push(AddTileCommand(self.graph, page_id, tile))

    def _add_tile_to_page(self, page_id: str, node_id: str) -> None:
        """Context-menu path: place the tile near the page's visible center,
        cascading a little so stacked adds don't hide each other."""
        widget = self._dashboard_pages.get(page_id)
        if widget is not None:
            center = widget.view.mapToScene(
                widget.view.viewport().rect().center())
        else:
            center = QPointF(0, 0)
        count = len(self.graph.pages[page_id].tiles)
        offset = 24.0 * (count % 8)
        self._on_tile_dropped(page_id, node_id,
                              QPointF(center.x() - 210 + offset,
                                      center.y() - 160 + offset))
        self.page_bar.select_page(page_id)

    def _add_tile_on_new_page(self, node_id: str) -> None:
        self.undo_stack.beginMacro("add to new page")
        page = Page(id=uuid.uuid4().hex, title=self._next_page_title())
        self.undo_stack.push(AddPageCommand(self.graph, page))
        self._add_tile_to_page(page.id, node_id)
        self.undo_stack.endMacro()

    def _on_node_failed(self, node_id: str, error) -> None:
        if node_id in self.graph.nodes:
            self.statusBar().showMessage(
                f"{self.graph.nodes[node_id].label}: {error.message}", 8000)
        self.editor_panel.on_node_failed(node_id, error)

    def _on_selection_changed(self) -> None:
        items = self.scene.selected_node_items()
        node_id = items[0].node.id if len(items) == 1 else None
        self.params_panel.set_node(node_id)
        self.editor_panel.set_node(node_id)
        self.resource_monitor.set_node(node_id)
        if node_id is not None:
            self.inspector_panel.show_node(node_id)
            return
        wires = [i for i in self.scene.selectedItems()
                 if isinstance(i, ConnectionItem)]
        if len(wires) == 1:
            self.inspector_panel.show_wire(wires[0].conn)
        else:
            self.inspector_panel.show_node(None)

    def _on_node_double_clicked(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is not None and card_kind(node) in ("note", "button"):
            # notes and buttons are edited through their params, not their code
            self.params_panel.set_node(node_id)
            self.properties_dock.show()
            self.properties_dock.raise_()
            return
        self.editor_panel.set_node(node_id)
        self.editor_dock.show()
        self.editor_dock.raise_()
        self.editor_panel.editor.setFocus()

    def _rename_node(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None:
            return
        text, ok = QInputDialog.getText(
            self, "Rename node", "Label:", text=node.label)
        if ok:
            new = text.strip() or None
            if new == node.spec.label:
                # dialog pre-fills with the resolved label (falls back to the
                # spec default when unset) — clicking OK unedited must not
                # turn that default into an explicit override
                new = None
            if new != node.label_override:
                self.undo_stack.push(SetLabelCommand(self.graph, node_id, new))

    def _rename_selected(self) -> None:
        grid = self._focused_spreadsheet()
        if grid is not None:   # F2 inside a table card edits the cell
            grid.edit_current()
            return
        items = self.scene.selected_node_items()
        if len(items) == 1:
            self._rename_node(items[0].node.id)

    def _run_selected(self) -> None:
        targets = [item.node.id for item in self.scene.selected_node_items()]
        if targets:
            self.engine.run_targets(targets)

    def _reset_caches(self) -> None:
        for node_id in self.graph.nodes:
            self.graph.mark_dirty(node_id)
        self.engine.cache.clear()
        self.statusBar().showMessage("Caches cleared — everything is stale", 4000)

    def _show_packages(self) -> None:
        from .packages_dialog import PackagesDialog
        dialog = getattr(self, "_packages_dialog", None)
        if dialog is None:
            dialog = PackagesDialog(self)
            self._packages_dialog = dialog
        dialog.show()
        dialog.raise_()

    def _show_ai_settings(self) -> None:
        from .ai_settings_dialog import AiSettingsDialog
        AiSettingsDialog(self).exec()

    def _show_settings(self) -> None:
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(self, self)
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    # ------------------------------------------------------- action button

    def _on_button_fired(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "button":
            return
        action = node.params.get("action", "Run nodes")
        if action == "Show message":
            self._show_button_message(node)
            return
        if action == "Run whole flow":
            targets = list(self.graph.nodes)
        elif action == "Run frame":
            targets = self._frame_node_ids(node.params.get("frame_title", ""))
        else:
            targets = self._named_node_ids(node.params.get("targets", ""))
        if not targets:
            self.statusBar().showMessage(f"{node.label}: nothing to run", 5000)
            return
        if node.params.get("clear_cache", True):
            for target_id in targets:
                self.graph.mark_dirty(target_id)
        self.engine.run_targets(targets)

    def _on_slicer_changed(self, node_id: str) -> None:
        """A Slicer's ticks changed: re-run it and the visuals that follow.
        The SetParamCommand already dirtied the subgraph; if a run is in
        flight this is a no-op and the affected nodes just stay stale."""
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "slicer":
            return
        self.engine.run_targets([node_id, *self.graph.downstream(node_id)])

    def _named_node_ids(self, text: str) -> list[str]:
        wanted = {line.strip().lower() for line in text.splitlines()
                  if line.strip()}
        if not wanted:
            return []
        return [nid for nid, n in self.graph.nodes.items()
                if n.label.lower() in wanted or nid in wanted]

    def _nodes_in_rect(self, rect: QRectF) -> list[str]:
        return [nid for nid, item in self.scene.node_items.items()
                if rect.contains(item.sceneBoundingRect().center())]

    def _frame_node_ids(self, title: str) -> list[str]:
        title = title.strip().lower()
        if not title:
            return []
        frame = next((f for f in self.graph.frames.values()
                      if f.title.strip().lower() == title), None)
        if frame is None:
            return []
        return self._nodes_in_rect(QRectF(*frame.rect))

    def _frame_node_ids_by_id(self, frame_id: str) -> list[str]:
        frame = self.graph.frames.get(frame_id)
        if frame is None:
            return []
        return self._nodes_in_rect(QRectF(*frame.rect))

    def _on_frame_run_requested(self, frame_id: str) -> None:
        targets = self._frame_node_ids_by_id(frame_id)
        if not targets:
            self.statusBar().showMessage("Frame is empty — nothing to run", 4000)
            return
        self.engine.run_targets(targets)

    def _show_button_message(self, node) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(node.label)
        box.setTextFormat(Qt.MarkdownText)
        box.setText(node.params.get("message", "") or "*(no message set)*")
        box.exec()

    # ------------------------------------------------------------- add node

    def _add_node_at(self, type_id: str, scene_pos: QPointF) -> None:
        node = self.registry.instantiate(
            type_id, pos=(scene_pos.x(), scene_pos.y()))
        self.undo_stack.push(AddNodeCommand(self.graph, node))

    def _add_node_at_view_center(self, type_id: str) -> None:
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self._add_node_at(type_id, center)

    def _add_reader_nodes_for_files(
            self, paths: list[str], scene_pos: QPointF) -> None:
        targets = [(p, resolve_dropped_file(p)) for p in paths]
        targets = [(p, t) for p, t in targets if t is not None]
        if not targets:
            return
        self.undo_stack.beginMacro(
            "drop file" if len(targets) == 1 else "drop files")
        new_ids = []
        for i, (path, (type_id, param_name)) in enumerate(targets):
            node = self.registry.instantiate(
                type_id,
                pos=(scene_pos.x() + i * PASTE_OFFSET,
                     scene_pos.y() + i * PASTE_OFFSET))
            self.undo_stack.push(AddNodeCommand(self.graph, node))
            self.undo_stack.push(SetParamCommand(
                self.graph, node.id, param_name, path))
            new_ids.append(node.id)
        self.undo_stack.endMacro()
        self.scene.clearSelection()
        for node_id in new_ids:
            item = self.scene.node_items.get(node_id)
            if item is not None:
                item.setSelected(True)

    # ---------------------------------------------------------- user nodes

    def _reload_user_nodes(self) -> None:
        errors = self.registry.reload_user_nodes(user_nodes_dir())
        self.library_tree.reload()
        if errors:
            skipped = ", ".join(p.name for p, _ in errors)
            self.statusBar().showMessage(
                f"Some user nodes were skipped: {skipped}", 6000)

    def _save_as_user_node(self, node_id: str) -> None:
        if node_id not in self.graph.nodes:
            return
        node = self.graph.node(node_id)
        nodes_dir = user_nodes_dir()
        dialog = SaveUserNodeDialog(
            node.label, user_nodes.list_groups(nodes_dir), self)
        if dialog.exec() != SaveUserNodeDialog.Accepted:
            return
        name, group = dialog.values()
        try:
            type_id = user_nodes.write_user_node(
                nodes_dir, group, name, node.source)
        except user_nodes.UserNodeError:
            if QMessageBox.question(
                    self, "Overwrite user node?",
                    f"A user node named {name!r} already exists in this "
                    f"group. Overwrite it?") != QMessageBox.Yes:
                return
            type_id = user_nodes.write_user_node(
                nodes_dir, group, name, node.source, overwrite=True)
        self._reload_user_nodes()
        self.statusBar().showMessage(f"Saved user node {type_id}", 4000)

    def _new_user_group(self) -> None:
        name, ok = QInputDialog.getText(self, "New group", "Group name:")
        if ok and name.strip():
            user_nodes.create_group(user_nodes_dir(), name.strip())
            self._reload_user_nodes()

    def _rename_user_node(self, type_id: str) -> None:
        spec = self.registry.maybe_get(type_id)
        current = spec.label if spec else ""
        name, ok = QInputDialog.getText(
            self, "Rename user node", "Name:", QLineEdit.Normal, current)
        if not (ok and name.strip()):
            return
        try:
            user_nodes.rename_user_node(user_nodes_dir(), type_id, name.strip())
        except user_nodes.UserNodeError as exc:
            QMessageBox.warning(self, "Rename failed", str(exc))
            return
        self._reload_user_nodes()

    def _move_user_node(self, type_id: str) -> None:
        nodes_dir = user_nodes_dir()
        groups = user_nodes.list_groups(nodes_dir)
        choices = ["(no group)", *groups, "New group…"]
        choice, ok = QInputDialog.getItem(
            self, "Move to group", "Group:", choices, 0, False)
        if not ok:
            return
        if choice == "New group…":
            new_name, ok = QInputDialog.getText(self, "New group", "Group name:")
            if not (ok and new_name.strip()):
                return
            target: Optional[str] = user_nodes.slugify(new_name.strip())
        elif choice == "(no group)":
            target = None
        else:
            target = choice
        try:
            user_nodes.move_user_node(nodes_dir, type_id, target)
        except user_nodes.UserNodeError as exc:
            QMessageBox.warning(self, "Move failed", str(exc))
            return
        self._reload_user_nodes()

    def _delete_user_node(self, type_id: str) -> None:
        spec = self.registry.maybe_get(type_id)
        label = spec.label if spec else type_id
        if QMessageBox.question(
                self, "Delete user node?",
                f"Delete user node {label!r}? Nodes already placed on the "
                f"canvas keep working; new placements won't be available."
                ) != QMessageBox.Yes:
            return
        try:
            user_nodes.delete_user_node(user_nodes_dir(), type_id)
        except user_nodes.UserNodeError as exc:
            QMessageBox.warning(self, "Delete failed", str(exc))
            return
        self._reload_user_nodes()

    def _show_palette(self, scene_pos: QPointF, global_pos: QPoint) -> None:
        self._palette_scene_pos = scene_pos
        self._pending_wire = None
        self._palette_popup.popup_at(global_pos)

    def _add_node_from_palette(self, type_id: str) -> None:
        pending = getattr(self, "_pending_wire", None)
        if pending is None:
            self._add_node_at(type_id, self._palette_scene_pos)
            return
        # wire-drop flow: add the node and connect it to the dragged wire
        self._pending_wire = None
        src_node_id, port_name, from_output, port_type = pending
        node = self.registry.instantiate(
            type_id, pos=(self._palette_scene_pos.x(),
                          self._palette_scene_pos.y()))
        from flograph.core import can_connect
        if from_output:
            match = next((p for p in node.spec.inputs
                          if can_connect(port_type, p.type)), None)
        else:
            match = next((p for p in node.spec.outputs
                          if can_connect(p.type, port_type)), None)
        self.undo_stack.beginMacro("add connected node")
        self.undo_stack.push(AddNodeCommand(self.graph, node))
        if match is not None:
            if from_output:
                self.undo_stack.push(ConnectCommand(
                    self.graph, src_node_id, port_name, node.id, match.name))
            else:
                self.undo_stack.push(ConnectCommand(
                    self.graph, node.id, match.name, src_node_id, port_name))
        self.undo_stack.endMacro()

    def _on_wire_dropped(self, port_item, scene_pos: QPointF) -> None:
        """Blueprint behavior: dropping a fresh wire on empty canvas opens the
        palette filtered to nodes that can accept it."""
        from flograph.core import can_connect
        from_output = port_item.spec.direction.value == "output"
        port_type = port_item.spec.type
        self._palette_scene_pos = scene_pos
        self._pending_wire = (port_item.node_id, port_item.spec.name,
                              from_output, port_type)

        def compatible(spec) -> bool:
            ports = spec.inputs if from_output else spec.outputs
            return any(
                can_connect(port_type, p.type) if from_output
                else can_connect(p.type, port_type)
                for p in ports)

        self._palette_popup.popup_at(
            self.view.mapToGlobal(self.view.mapFromScene(scene_pos)),
            predicate=compatible)

    def _show_add_node_menu(self, scene_pos: QPointF, global_pos: QPoint) -> None:
        menu = QMenu(self)
        for category, specs in self.registry.categories().items():
            submenu = menu.addMenu(category)
            for spec in specs:
                action = submenu.addAction(spec.label)
                action.setData(spec.type_id)
        menu.addSeparator()
        frame_action = menu.addAction("Add Frame Here")
        paste_action = None
        if self._clipboard_payload() is not None:
            menu.addSeparator()
            paste_action = menu.addAction("Paste")
        chosen = menu.exec(global_pos)
        if chosen is frame_action:
            self._add_frame_at(scene_pos)
        elif paste_action is not None and chosen is paste_action:
            self._paste()
        elif chosen is not None and chosen.data():
            self._add_node_at(chosen.data(), scene_pos)

    def _show_frame_menu(self, frame_id: str, global_pos: QPoint) -> None:
        if frame_id not in self.graph.frames:
            return
        item = self.scene.frame_items.get(frame_id)
        if item is not None and not item.isSelected():
            self.scene.clearSelection()
            item.setSelected(True)
        menu = QMenu(self)
        copy_action = menu.addAction("Copy")
        change_color = menu.addAction("Change colour…")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        chosen = menu.exec(global_pos)
        if chosen is copy_action:
            self._copy_selection()
        elif chosen is change_color:
            self._pick_frame_color(frame_id)
        elif chosen is delete_action:
            from .commands import RemoveFrameCommand
            self.undo_stack.push(RemoveFrameCommand(self.graph, frame_id))

    def _pick_frame_color(self, frame_id: str) -> None:
        if frame_id not in self.graph.frames:
            return
        current = QColor(self.graph.frames[frame_id].color)
        color = QColorDialog.getColor(current, self, "Frame colour")
        if color.isValid():
            self.scene.push_frame_color(frame_id, color.name())

    def _pick_node_color(self, node_id: str) -> None:
        if node_id not in self.graph.nodes:
            return
        node = self.graph.nodes[node_id]
        from . import theme
        current = QColor(node.color) if node.color else theme.NODE_HEADER
        color = QColorDialog.getColor(current, self, "Node colour")
        if color.isValid():
            self.scene.push_node_color(node_id, color.name())

    def _show_node_menu(self, node_id: str, global_pos: QPoint) -> None:
        if node_id not in self.graph.nodes:
            return
        item = self.scene.node_items.get(node_id)
        if item is not None and not item.isSelected():
            self.scene.clearSelection()
            item.setSelected(True)
        node = self.graph.nodes[node_id]
        menu = QMenu(self)
        run_to = menu.addAction("Run To This Node")
        menu.addSeparator()
        edit_code = menu.addAction("Edit Code")
        rename = menu.addAction("Rename")
        colour = menu.addAction("Change colour…")
        reset_colour = menu.addAction("Reset colour") if node.color else None
        rerun = menu.addAction("Mark Dirty")
        preview_action = None
        if card_kind(node) in PREVIEW_TOGGLABLE_KINDS:
            preview_action = menu.addAction(
                "Disable Canvas Preview" if node.canvas_preview_enabled
                else "Enable Canvas Preview")
        import_action = None
        if (card_kind(node) == "grid"
                and self._table_import_source(node_id) is not None):
            import_action = menu.addAction("Import input into table")
        view_actions = self._add_view_actions(menu, node_id)
        page_actions: list = []
        new_page_action = None
        if is_tile_able(self.graph.nodes[node_id]):
            submenu = menu.addMenu("Add to Page")
            for page in self.graph.pages.values():
                page_actions.append((submenu.addAction(page.title), page.id))
            if page_actions:
                submenu.addSeparator()
            new_page_action = submenu.addAction("New Page…")
        menu.addSeparator()
        copy_action = menu.addAction("Copy")
        delete = menu.addAction("Delete")
        chosen = menu.exec(global_pos)
        if chosen is run_to:
            self.engine.run_to(node_id)
        elif chosen is edit_code:
            self._on_node_double_clicked(node_id)
        elif chosen is rename:
            self._rename_node(node_id)
        elif chosen is colour:
            self._pick_node_color(node_id)
        elif reset_colour is not None and chosen is reset_colour:
            self.scene.push_node_color(node_id, None)
        elif chosen is rerun:
            self.graph.mark_dirty(node_id)
        elif preview_action is not None and chosen is preview_action:
            self.undo_stack.push(SetPreviewEnabledCommand(
                self.graph, node_id, not node.canvas_preview_enabled))
        elif import_action is not None and chosen is import_action:
            self._import_input_into_table(node_id)
        elif chosen is copy_action:
            self._copy_selection()
        elif chosen is delete:
            self.scene.delete_selection()
        elif new_page_action is not None and chosen is new_page_action:
            self._add_tile_on_new_page(node_id)
        else:
            page_id = next((p for a, p in page_actions if a is chosen), None)
            if page_id is not None:
                self._add_tile_to_page(page_id, node_id)
                return
            port_name = next((p for a, p in view_actions if a is chosen), None)
            if port_name is not None:
                from .inspector.popup_view import PopupView
                PopupView(self.graph, self.engine, node_id, port_name,
                          parent=self).show()

    def _add_view_actions(self, menu: QMenu, node_id: str) -> list:
        """Add 'View Table (port)'/'View Visual (port)' entries for any
        cached output that's a DataFrame/Series or a matplotlib Figure.
        Omitted (not grayed out) when nothing is cached yet."""
        import sys
        entry = self.engine.cache.get(node_id)
        if entry is None:
            return []
        node = self.graph.nodes.get(node_id)
        if node is None:
            return []
        pd = sys.modules.get("pandas")
        figure_cls = getattr(sys.modules.get("matplotlib.figure"), "Figure", None)
        actions = []
        for port in node.spec.outputs:
            value = entry.outputs.get(port.name)
            if pd is not None and isinstance(value, (pd.DataFrame, pd.Series)):
                actions.append((menu.addAction(f"View Table ({port.name})"),
                                port.name))
            elif figure_cls is not None and isinstance(value, figure_cls):
                actions.append((menu.addAction(f"View Visual ({port.name})"),
                                port.name))
        return actions

    # ------------------------------------------------------ frames & align

    def _add_frame(self) -> None:
        from flograph.core import Frame
        from .commands import AddFrameCommand
        selected = self.scene.selected_node_items()
        if selected:
            rect = None
            for item in selected:
                bounds = item.sceneBoundingRect()
                rect = bounds if rect is None else rect.united(bounds)
            rect.adjust(-30, -50, 30, 30)
            frame = Frame(id=uuid.uuid4().hex,
                          rect=(rect.x(), rect.y(), rect.width(), rect.height()))
        else:
            center = self.view.mapToScene(self.view.viewport().rect().center())
            frame = Frame(id=uuid.uuid4().hex,
                          rect=(center.x() - 200, center.y() - 130, 400, 260))
        self.undo_stack.push(AddFrameCommand(self.graph, frame))

    def _add_frame_at(self, scene_pos: QPointF) -> None:
        from flograph.core import Frame
        from .commands import AddFrameCommand
        frame = Frame(id=uuid.uuid4().hex,
                      rect=(scene_pos.x(), scene_pos.y(), 400, 260))
        self.undo_stack.push(AddFrameCommand(self.graph, frame))

    def _align(self, mode: str) -> None:
        items = self.scene.selected_node_items()
        if len(items) < 2:
            return
        moves = {}
        if mode in ("left", "top"):
            anchor = min(i.pos().x() if mode == "left" else i.pos().y()
                         for i in items)
            for item in items:
                old = (item.pos().x(), item.pos().y())
                new = (anchor, old[1]) if mode == "left" else (old[0], anchor)
                if new != old:
                    moves[item.node.id] = (old, new)
        else:
            horizontal = mode == "dist_h"
            key = (lambda i: i.pos().x()) if horizontal else (lambda i: i.pos().y())
            ordered = sorted(items, key=key)
            first, last = key(ordered[0]), key(ordered[-1])
            step = (last - first) / (len(ordered) - 1)
            for index, item in enumerate(ordered):
                old = (item.pos().x(), item.pos().y())
                coord = first + step * index
                new = (coord, old[1]) if horizontal else (old[0], coord)
                if new != old:
                    moves[item.node.id] = (old, new)
        if moves:
            self.scene.push_move_command(moves)

    # -------------------------------------------------------- window state

    def _restore_window_state(self) -> None:
        geometry = self.settings.value("window_geometry")
        state = self.settings.value("dock_state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self._dock_host.restoreState(state)

    def _save_window_state(self) -> None:
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("dock_state", self._dock_host.saveState())

    # ----------------------------------------------------------- copy/paste

    def _selection_payload(self) -> Optional[dict]:
        frame_items = self.scene.selected_frame_items()
        node_ids = {item.node.id for item in self.scene.selected_node_items()}
        for item in frame_items:
            # a frame carries the nodes sitting inside it, same as a drag
            node_ids.update(self._frame_node_ids_by_id(item.frame.id))
        nodes = [self.graph.nodes[nid] for nid in node_ids
                if nid in self.graph.nodes]
        frames = [item.frame for item in frame_items]
        if not nodes and not frames:
            return None
        ids = {n.id for n in nodes}
        return {
            _CLIPBOARD_KEY: 1,
            "nodes": [{
                "id": n.id, "type": n.type_id, "pos": list(n.pos),
                "params": dict(n.params), "code": n.code_override,
                "label": n.label_override, "color": n.color,
                "description": n.description,
            } for n in nodes],
            "connections": [{
                "src": [c.src_node, c.src_port], "dst": [c.dst_node, c.dst_port],
            } for c in self.graph.connections.values()
                if c.src_node in ids and c.dst_node in ids],
            "frames": [{
                "title": f.title, "rect": list(f.rect), "color": f.color,
            } for f in frames],
        }

    def _copy_selection(self) -> None:
        payload = self._selection_payload()
        if payload is not None:
            QApplication.clipboard().setText(json.dumps(payload))

    def _cut_selection(self) -> None:
        payload = self._selection_payload()
        if payload is not None:
            QApplication.clipboard().setText(json.dumps(payload))
            self.scene.delete_selection()

    def _clipboard_payload(self) -> Optional[dict]:
        try:
            payload = json.loads(QApplication.clipboard().text())
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(payload, dict) or _CLIPBOARD_KEY not in payload:
            return None
        return payload

    def _paste(self) -> None:
        payload = self._clipboard_payload()
        if payload is not None:
            self._insert_payload(payload)

    def _duplicate(self) -> None:
        grid = self._focused_spreadsheet()
        if grid is not None:   # Ctrl+D inside a table card fills down
            grid.fill_down_selection()
            return
        payload = self._selection_payload()
        if payload is not None:
            self._insert_payload(payload)

    @staticmethod
    def _remap_node_refs(params: dict, spec, id_map: dict[str, str]) -> dict:
        """Point pasted node references at the pasted copies.

        A reference to a node that wasn't part of the payload is left alone —
        copying a lone From keeps it reading the same Goto, while copying the
        pair rewires the copies to each other.
        """
        for param in spec.params:
            if param.type != "node_ref":
                continue
            target = params.get(param.name)
            if isinstance(target, str) and target in id_map:
                params[param.name] = id_map[target]
        return params

    def _insert_payload(self, payload: dict) -> None:
        from flograph.core import Frame
        from .commands import AddFrameCommand
        # ids are assigned up front, before any node is built: a param that
        # references another node (a From's Goto) may name an entry that comes
        # later in the payload
        id_map: dict[str, str] = {entry["id"]: uuid.uuid4().hex
                                  for entry in payload.get("nodes", [])}
        new_nodes: list[NodeInstance] = []
        for entry in payload.get("nodes", []):
            code = entry.get("code")
            if code is not None:
                try:
                    spec = parse_spec(code, entry["type"])
                except Exception:
                    id_map.pop(entry["id"], None)
                    continue
            else:
                spec = self.registry.maybe_get(entry["type"])
                if spec is None:
                    id_map.pop(entry["id"], None)
                    continue
            new_id = id_map[entry["id"]]
            new_nodes.append(NodeInstance(
                id=new_id, spec=spec, code_override=code,
                params=self._remap_node_refs(
                    {**spec.default_params(), **entry.get("params", {})},
                    spec, id_map),
                pos=(entry["pos"][0] + PASTE_OFFSET,
                     entry["pos"][1] + PASTE_OFFSET),
                label_override=entry.get("label"),
                color=entry.get("color"),
                description=entry.get("description", ""),
            ))
        new_frames: list[Frame] = []
        for entry in payload.get("frames", []):
            rect = entry.get("rect", [0.0, 0.0, 300.0, 200.0])
            new_frames.append(Frame(
                id=uuid.uuid4().hex, title=entry.get("title", "Frame"),
                rect=(rect[0] + PASTE_OFFSET, rect[1] + PASTE_OFFSET,
                     rect[2], rect[3]),
                color=entry.get("color") or "#33415c",
            ))
        if not new_nodes and not new_frames:
            return
        self.undo_stack.beginMacro("paste")
        for node in new_nodes:
            self.undo_stack.push(AddNodeCommand(self.graph, node))
        for frame in new_frames:
            self.undo_stack.push(AddFrameCommand(self.graph, frame))
        for conn in payload.get("connections", []):
            src_node, src_port = conn["src"]
            dst_node, dst_port = conn["dst"]
            if src_node in id_map and dst_node in id_map:
                self.undo_stack.push(ConnectCommand(
                    self.graph, id_map[src_node], src_port,
                    id_map[dst_node], dst_port))
        self.undo_stack.endMacro()
        self.scene.clearSelection()
        for node in new_nodes:
            item = self.scene.node_items.get(node.id)
            if item is not None:
                item.setSelected(True)
        for frame in new_frames:
            item = self.scene.frame_items.get(frame.id)
            if item is not None:
                item.setSelected(True)

    # ------------------------------------------------------ project files

    def _on_clean_changed(self, clean: bool) -> None:
        self._update_title()

    def _update_title(self) -> None:
        name = Path(self._project_path).name if self._project_path else "untitled"
        self.setWindowTitle(f"{name}[*] — flograph")
        self.setWindowModified(not self.undo_stack.isClean())

    def _confirm_discard(self) -> bool:
        if self.undo_stack.isClean():
            return True
        answer = QMessageBox.question(
            self, "Unsaved changes",
            "The project has unsaved changes. Save them first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if answer == QMessageBox.Save:
            return self._save()
        return answer == QMessageBox.Discard

    def closeEvent(self, event) -> None:
        if not self.confirm_close or self._confirm_discard():
            self._wait_for_cache_load()
            self._save_window_state()
            event.accept()
        else:
            event.ignore()

    _CACHE_LOAD_CLOSE_TIMEOUT_S = 120  # generous: matches large-blob load times

    def _wait_for_cache_load(self) -> None:
        """Pump events (not a hard freeze — other events still process)
        until a pending cache-restore runnable's `finished` is delivered.
        Without this, closing mid-load can tear down the signals QObject
        while the pool thread is still emitting into it. Polling
        `_cache_load_signals` rather than connecting a fresh `loop.quit` to
        `finished` avoids missing an emit that was already queued (and thus
        has no listener yet) before this method runs.

        Bounded: the runnable shares QThreadPool.globalInstance() with node
        execution, so in principle it could sit queued behind a long-running
        script indefinitely. Give up after the timeout rather than hanging
        the close forever — the risk that accepting the close race hits the
        one-in-a-blue-moon in-flight emit is far better than never closing."""
        if self._cache_load_signals is None:
            return
        deadline = time.monotonic() + self._CACHE_LOAD_CLOSE_TIMEOUT_S
        while self._cache_load_signals is not None and time.monotonic() < deadline:
            QApplication.processEvents(QEventLoop.WaitForMoreEvents, 500)
        # timed out: the runnable is still out there and will still emit
        # into `signals` eventually — disconnect so that lands as a no-op
        # instead of touching this (possibly torn-down) window later
        signals, self._cache_load_signals = self._cache_load_signals, None
        if signals is not None:
            signals.entry_loaded.disconnect()
            signals.finished.disconnect()

    def _cache_still_loading(self) -> bool:
        if self._cache_load_signals is None:
            return False
        self.statusBar().showMessage(
            "Still restoring cached results from the previous project — try again in a moment",
            4000)
        return True

    def _new_project(self) -> None:
        if self._cache_still_loading():
            return
        if not self._confirm_discard():
            return
        self._replace_graph(Graph())
        self._project_path = None
        self._update_title()

    def _open_dialog(self) -> None:
        if self._cache_still_loading():
            return
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "flograph projects (*.flograph)")
        if path:
            self.open_path(path, confirm=False)

    def _build_examples_menu(self, file_menu: QMenu) -> None:
        import importlib.resources

        self._examples_menu = file_menu.addMenu("Open &Example")
        try:
            root = importlib.resources.files("flograph.templates")
            paths = sorted(
                (entry for entry in root.iterdir()
                 if entry.name.endswith(".flograph")),
                key=lambda entry: entry.name,
            )
        except (ModuleNotFoundError, FileNotFoundError):
            paths = []
        self._examples_menu.setEnabled(bool(paths))
        for entry in paths:
            title = entry.name[:-len(".flograph")]
            if title[:2].isdigit() and "_" in title:
                title = title.split("_", 1)[1]
            title = title.replace("_", " ").title()
            action = self._examples_menu.addAction(title)
            action.triggered.connect(
                lambda checked=False, p=Path(str(entry)): self._open_example(p))

    def _open_example(self, path: Path) -> None:
        if self._cache_still_loading():
            return
        if not self._confirm_discard():
            return
        try:
            loaded = serialization.load(path, self.registry)
        except (GraphError, OSError, KeyError) as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self._replace_graph(loaded)
        self._project_path = None
        self._update_title()
        self.statusBar().showMessage(
            f"Loaded example '{path.stem}' — use Save As to keep it", 4000)

    def open_path(self, path: str, confirm: bool = True) -> bool:
        if self._cache_still_loading():
            return False
        if confirm and not self._confirm_discard():
            return False
        try:
            loaded = serialization.load(path, self.registry)
        except (GraphError, OSError, KeyError) as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return False
        self._replace_graph(loaded)
        self._project_path = path
        self._push_recent(path)
        self._update_title()
        saved_page = self.settings.value(f"active_page/{path}", "")
        if saved_page and saved_page in self.graph.pages:
            self.page_bar.select_page(saved_page)
        broken = sum(1 for n in loaded.nodes.values() if n.spec.broken)
        if broken:
            self.statusBar().showMessage(
                f"Opened {path} — {broken} node(s) couldn't be resolved and "
                f"were loaded as broken placeholders", 6000)
        else:
            self.statusBar().showMessage(f"Opened {path}", 4000)
        self._restore_cache(path, quiet=bool(broken))
        return True

    def _restore_cache(self, path: str, quiet: bool = False) -> None:
        """Restore cached node outputs for the just-opened project. Resolving
        which entries are still valid is cheap and happens here; unpickling
        each blob can be slow for large cached DataFrames/figures, so that
        part runs on a pool thread (flograph.engine.cache_worker) with a
        progress dialog rather than freezing the window."""
        entries = cache_persistence.resolve_entries(self.graph, path)
        if not entries:
            return

        dialog = QProgressDialog(
            "Restoring cached results…", "", 0, len(entries), self)
        dialog.setWindowTitle("Loading")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(400)
        dialog.setValue(0)

        signals = CacheLoadSignals()  # created on the GUI thread, before pool.start
        restored: list[str] = []

        def on_entry(node_id: str, outputs: dict, wall_time: float) -> None:
            self.engine.cache.set(node_id, outputs, wall_time)
            self.graph.mark_clean(node_id)
            self.graph.set_status(node_id, NodeStatus.DONE)
            self.engine.node_succeeded.emit(node_id)
            restored.append(node_id)
            dialog.setValue(len(restored))

        def on_finished() -> None:
            dialog.close()
            self._cache_load_signals = None
            if not quiet:
                self.statusBar().showMessage(
                    f"Opened {path} — {len(restored)} node(s) restored from cache", 4000)

        signals.entry_loaded.connect(on_entry)
        signals.finished.connect(on_finished)
        self._cache_load_signals = signals  # keep alive until finished
        QThreadPool.globalInstance().start(CacheLoadRunnable(path, entries, signals))

    def _replace_graph(self, loaded: Graph) -> None:
        self._restoring_pages = True
        for page_id in list(self.graph.pages):
            self.graph.remove_page(page_id)
        for frame_id in list(self.graph.frames):
            self.graph.remove_frame(frame_id)
        for node_id in list(self.graph.nodes):
            self.graph.remove_node(node_id)
        for node in loaded.nodes.values():
            self.graph.add_node(node)
        for conn in loaded.connections.values():
            self.graph.connect(conn.src_node, conn.src_port,
                               conn.dst_node, conn.dst_port, conn_id=conn.id)
        for frame in loaded.frames.values():
            self.graph.add_frame(frame)
        for page in loaded.pages.values():
            self.graph.add_page(page)
        self._restoring_pages = False
        self.undo_stack.clear()
        self.undo_stack.setClean()
        if loaded.nodes:
            self.view.frame_content()

    def _save(self) -> bool:
        if self._project_path is None:
            return self._save_as()
        serialization.save(self.graph, self._project_path)
        if not self.engine.active:
            cache_persistence.save_cache(
                self.graph, self.engine.cache, self._project_path)
        self.undo_stack.setClean()
        self._push_recent(self._project_path)
        self.statusBar().showMessage(f"Saved {self._project_path}", 4000)
        return True

    def _save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", "untitled.flograph", "flograph projects (*.flograph)")
        if not path:
            return False
        if not path.endswith(".flograph"):
            path += ".flograph"
        self._project_path = path
        return self._save()

    # --------------------------------------------------------------- recent

    def _recent_files(self) -> list[str]:
        value = self.settings.value("recent_files", [])
        if isinstance(value, str):
            value = [value]
        return [p for p in (value or []) if p]

    def _push_recent(self, path: str) -> None:
        recent = self._recent_files()
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        self.settings.setValue("recent_files", recent[:MAX_RECENT])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        recent = [p for p in self._recent_files() if Path(p).exists()]
        self._recent_menu.setEnabled(bool(recent))
        for path in recent:
            action = self._recent_menu.addAction(Path(path).name)
            action.setToolTip(path)
            action.triggered.connect(
                lambda checked=False, p=path: self.open_path(p))
