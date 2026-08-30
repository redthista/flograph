from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QEventLoop, QPoint, QPointF, QRectF, QSettings, Qt, QThreadPool, QTimer, QUrl,
)
from PySide6.QtGui import (
    QAction, QColor, QDesktopServices, QKeySequence, QUndoStack,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QDockWidget, QFileDialog,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QProgressBar, QProgressDialog,
    QSizePolicy, QStackedWidget, QTextEdit,
    QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from flograph.core import (
    Graph, GraphError, NodeInstance, NodeRegistry, NodeStatus, Page, Tile,
    parse_spec,
)
from flograph.core import dotenv
from flograph.core import serialization
from flograph.core import user_nodes
from flograph.engine import (
    CacheLoadSignals, CacheSaveRunnable, CacheSaveSignals, ExecutionEngine,
    cache_persistence, is_exclusive,
)
from flograph.engine.cache_persistence import save_failure_text
from flograph.paths import user_nodes_dir

from .commands import (
    AddNodeCommand, AddPageCommand, AddTileCommand, ConnectCommand,
    DuplicatePageCommand, RemovePageCommand, RenamePageCommand,
    ReorderPagesCommand, SetPageColorCommand,
    SetActiveCommand, SetExclusiveCommand, SetFrameFlagCommand,
    SetFrameSourceCommand, SetManualCommand,
    SetFrozenCommand, SetLabelCommand, SetLockedCommand, SetParamCommand,
)
from .canvas import ConnectionItem, NodeGraphScene, NodeGraphView
from .canvas.file_drop import resolve_dropped_path
from .canvas import grid
from .canvas import view as canvas_view
from .canvas.stacking import add_layer_menu
from .canvas.node_item import DEFAULT_LOD_THRESHOLD, IMAGE_TYPE, card_kind
from .canvas.palette import LibraryPanel, NodePalettePopup
from .favorites import Favorites
from .dashboard import (
    DashboardPage, PageTabBar, default_tile_port, default_tile_size,
    is_tile_able,
)
from . import dock_edges
from .shortcuts import ShortcutRegistry
from .console.log_dock import LogConsole
from .editor.editor_dock import EditorPanel
from .editor.save_user_node_dialog import SaveUserNodeDialog
from .inspector.inspector_dock import InspectorPanel
from .properties.params_panel import ParamsPanel
from .resource_monitor import ResourceMonitorWidget, format_seconds
from flograph.engine.runstats import HISTORY_LIMIT

# How often the run status line re-reads the clock. The interesting cases —
# a slow node, a stuck one — send no events at all, so the line has to be
# driven by something other than the run itself.
RUN_TICK_MS = 500
# Silence longer than this earns a mention. A node reporting progress or
# writing to the log is never called quiet, however slow it is.
QUIET_NODE_AFTER_S = 10.0

from .stats_window import StatsWindow
from .settings_dialog import SettingsDialog
from .docs import DocsWindow
from . import theme
from . import toolbar as toolbar_style
from . import window_frame

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
        self.scene.confirm_collapsed_delete = self._confirm_collapsed_delete
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
        # which page the docks were last arranged for; None is the model
        # canvas. Tracked so a page switch can tell "leaving the model page"
        # from "already on a dashboard page", which look identical by dock
        # visibility alone once every panel is collapsed.
        self._current_page_id = None
        self.engine = ExecutionEngine(self.graph, parent=self)
        # A frame's run flags apply to whatever it holds *now*, and only the
        # canvas can answer that — so the engine asks, once per run, rather
        # than being told whenever something is dragged. Through a lambda
        # because opening a project can replace the scene underneath us.
        self.engine.frame_membership = lambda: self.scene.flagged_frame_members()
        # the scene predates the engine, so it gets the cache handed to it
        self.scene.output_cache = self.engine.cache
        # Late-arriving cache data. Opening registers spilled entries, so
        # every data-bearing card builds from its placeholder until the
        # value it shows comes back off disk — and until now nothing told a
        # card when that had happened. One event, one batched refresh.
        self._resident_batch: set[str] = set()
        self._resident_timer = QTimer(self)
        self._resident_timer.setSingleShot(True)
        self._resident_timer.setInterval(120)
        self._resident_timer.timeout.connect(self._flush_resident_batch)
        self.engine.cache.became_resident.connect(self._on_cache_became_resident)
        # A warm that never lands (an unreadable blob that also never fails
        # cleanly) must not leave the restore busy-bar spinning forever.
        self._warm_watch_timer = QTimer(self)
        self._warm_watch_timer.setSingleShot(True)
        self._warm_watch_timer.timeout.connect(
            lambda: self._finish_warm_watch(completed=True))
        self.engine.cache_load_failed.connect(
            lambda _nid: self._tick_warm_watch())
        self.settings = QSettings("flograph", "flograph")
        # Our own title bar instead of the OS one. Read here, applied in
        # _build_actions (menus fold into a hamburger, run actions and the
        # window buttons go on the bar); a change needs a restart. The flag
        # has to be set before the window is shown.
        self._custom_frame = self.settings.value(
            "window/custom_frame", True, type=bool)
        self.setWindowIcon(window_frame.app_icon())
        if self._custom_frame:
            self.setWindowFlag(Qt.FramelessWindowHint, True)
        # built before _build_actions(): every action registers itself as
        # it is created, and a saved rebind has to be in force from then on
        self.shortcuts = ShortcutRegistry(self.settings, self)
        self.favorites = Favorites(self.settings, parent=self)
        self._project_path: Optional[str] = None
        self._cache_load_signals: Optional[CacheLoadSignals] = None
        # The background half of a save: writing the cache side-car. None
        # when idle; while up, Save/Open-a-second-save and starting a run
        # wait for it (see _cache_still_writing) rather than racing it.
        self._cache_save_signals: Optional[CacheSaveSignals] = None
        # Set at the start of a bundled save: the undo index the archive
        # snapshot was taken at (clean is marked only if editing has not
        # moved past it by the time the write lands), and whether a legacy
        # side-car folder was there to fold in (for the status message).
        self._save_clean_index = 0
        self._folded_sidecar = False
        # Nodes whose cached value a just-opened project is still warming for
        # its cards; while the watch is active the restore busy-bar is up.
        # The message to show once it drains.
        self._warm_watch: set[str] = set()
        self._warm_watch_active = False
        self._warm_done_message = ""
        # set False to close without the unsaved-changes prompt (tests, scripts)
        self.confirm_close = True
        self._gpu_viewport_checked_on_show = False
        self._settings_dialog: Optional[SettingsDialog] = None
        self._stats_window: Optional[StatsWindow] = None
        self._docs_window: Optional[DocsWindow] = None
        # Floating per-node Properties/Code windows, keyed by node id — one
        # per node, several nodes at once. See ui.node_window.
        self._node_windows: dict = {}

        self.stats_bar_enabled = self.settings.value(
            "stats/bar_enabled", True, type=bool)
        self.stats_sampling_enabled = self.settings.value(
            "stats/sampling_enabled", True, type=bool)
        self.stats_history_limit = self.settings.value(
            "stats/history_limit", HISTORY_LIMIT, type=int)
        # 0 = automatic; see engine.scheduler.default_workers.
        self.engine_max_workers = self.settings.value(
            "engine/max_workers", 0, type=int)
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
        self.grid_visible = self.settings.value("grid/visible", True, type=bool)
        self._apply_snap_settings()
        self.minimap_enabled = self.settings.value(
            "canvas/minimap_enabled", True, type=bool)
        self.view.minimap.setVisible(self.minimap_enabled)
        self.port_labels_enabled = self.settings.value(
            "canvas/port_labels", False, type=bool)
        self.scene.set_port_labels_enabled(self.port_labels_enabled)
        self.flow_pins_enabled = self.settings.value(
            "canvas/flow_pins", False, type=bool)
        self.scene.set_flow_pins_enabled(self.flow_pins_enabled)
        self.compact_nodes = self.settings.value(
            "canvas/compact_nodes", True, type=bool)
        self.scene.set_compact_nodes(self.compact_nodes)
        self.reveal_ports_key = int(self.settings.value(
            "canvas/reveal_ports_key", canvas_view.DEFAULT_REVEAL_PORTS_KEY,
            type=int))
        self.view.set_reveal_ports_key(self.reveal_ports_key)
        self.scrollbars_enabled = self.settings.value(
            "canvas/scrollbars", False, type=bool)
        self.view.set_scrollbars_enabled(self.scrollbars_enabled)
        # zlib on the cache side-car trades a little save-time CPU for a lot
        # of disk (ideas_archived.md #16). Off writes raw pickles; both eras
        # read forever either way — load_blob sniffs each blob.
        self.cache_compression_enabled = self.settings.value(
            "saving/compress_cache", True, type=bool)
        self.double_click_action = str(self.settings.value(
            "canvas/double_click_action", "properties"))
        self.tint_soft = self.settings.value(
            "canvas/tint_soft", theme.DEFAULT_TINT_SOFT, type=float)
        self.tint_strong = self.settings.value(
            "canvas/tint_strong", theme.DEFAULT_TINT_STRONG, type=float)
        theme.set_tints(self.tint_soft, self.tint_strong)
        # dashboard pages open with the visuals panel closed; the last thing
        # the user did with the toggle becomes the start state for new pages
        self.visuals_visible = self.settings.value(
            "dashboard/visuals_visible", False, type=bool)

        self._palette_popup = NodePalettePopup(registry, self.favorites, self)
        self._palette_scene_pos = QPointF()
        self._pending_wire = None
        self._palette_popup.chosen.connect(self._add_node_from_palette)
        self._palette_popup.extra_chosen.connect(self._palette_extra_chosen)

        # Run status: what is running, how far in, how long it has been, and
        # whether it has gone quiet. Driven by a tick rather than only by
        # events, because the interesting cases — a slow node, a stuck one —
        # are exactly the ones that send nothing.
        self._run_index = 0
        self._run_total = 0
        self._run_fraction = 0.0
        self._run_node_label = ""
        self._run_node_started = 0.0
        # node_id -> when it started, for every node in flight. Several can be,
        # so the line has to be composed from the set rather than from whichever
        # node started most recently; the per-node detail below is kept for the
        # common case where there is only one, which is the case where naming a
        # node is useful.
        self._run_inflight: dict[str, float] = {}
        self._run_last_output = 0.0
        # Whether the running node has said anything at all yet — a node that
        # has never spoken gets different wording from one that fell silent.
        self._run_had_output = False
        # Carried on the run line while memory is tight. Set and cleared by
        # the resource monitor's pressure signal, not by the run — the
        # machine does not stop being full because a run ended.
        self._run_pressure_note = ""
        # The same treatment for disk space, from the monitor's other signal.
        self._disk_note = ""
        self._run_prior: Optional[float] = None
        self._run_tick = QTimer(self)
        self._run_tick.setInterval(RUN_TICK_MS)
        self._run_tick.timeout.connect(self._update_run_status)

        # Coalesces a burst of param edits into one report re-render — see
        # _refresh_report_cards. Before _wire_engine, which connects to it.
        self._report_refresh = QTimer(self)
        self._report_refresh.setSingleShot(True)
        self._report_refresh.setInterval(120)
        self._report_refresh.timeout.connect(self._refresh_report_cards)

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
        # Progress across the plan, shown only while a run is on. Narrow,
        # thin and text-free: the message beside it already says what is
        # running, and this only has to answer "how much is left". The fixed
        # height keeps it a hairline track rather than the chunky default,
        # which otherwise sets the height of the whole status bar.
        self._run_bar = QProgressBar(self)
        self._run_bar.setRange(0, 100)
        self._run_bar.setTextVisible(False)
        self._run_bar.setFixedSize(80, 8)
        self._run_bar.hide()
        # The bar reads as the head of the run's own message, so the two sit
        # together at the bottom left: [====----]  Running: Group By · 3 of 8.
        # That is why the message is a label of ours rather than QStatusBar's
        # showMessage() -- a temporary message is painted from the left edge
        # of the bar, straight through any widget parked there, and it hides
        # the left-hand widgets while it is up. Owning the text is what lets
        # the bar live next to it. Everything goes through show_status().
        self.statusBar().addWidget(self._run_bar)
        # Its twin for saving: how far through writing the cache side-car a
        # save is. Same shape and parking place, so "the app is doing
        # something long" always looks the same in this window.
        self._save_bar = QProgressBar(self)
        self._save_bar.setRange(0, 100)
        self._save_bar.setTextVisible(False)
        self._save_bar.setFixedSize(80, 8)
        self._save_bar.hide()
        self.statusBar().addWidget(self._save_bar)
        # And a third: the busy bar shown while a just-opened project's
        # cached results rehydrate behind the window (opening is instant, a
        # large cached frame filling its cards is not — see _restore_cache).
        self._restore_bar = QProgressBar(self)
        self._restore_bar.setRange(0, 0)          # indeterminate
        self._restore_bar.setTextVisible(False)
        self._restore_bar.setFixedSize(80, 8)
        self._restore_bar.hide()
        self.statusBar().addWidget(self._restore_bar)
        self._status_label = QLabel(self)
        # Ignored, so a long message clips instead of widening the window's
        # minimum -- the behaviour showMessage() had.
        self._status_label.setSizePolicy(QSizePolicy.Ignored,
                                         QSizePolicy.Preferred)
        self.statusBar().addWidget(self._status_label, 1)
        # one timer, restarted per message: a timed message clears itself,
        # and a newer message always outlives an older one's countdown
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._status_label.clear)
        self._update_title()
        # captured before any saved layout is applied, so "reset window
        # layout" has a real default to go back to rather than a guess
        self._default_dock_state = self._dock_host.saveState()
        self._restore_window_state()
        # restoreState() carries dock visibility, so a dock closed last
        # session comes back closed -- and its reveal arrow with it
        self._docks_open_on_model_page = [
            dock for dock in self._model_docks if not dock.isHidden()]
        self._on_current_page_changed(self.page_bar.current_page_id())
        self.resource_monitor = ResourceMonitorWidget(self.engine, self)
        self.resource_monitor.clicked.connect(self._show_stats)
        self.resource_monitor.pressure_changed.connect(self._on_memory_pressure)
        self.resource_monitor.disk_changed.connect(self._on_disk_pressure)
        self.statusBar().addPermanentWidget(self.resource_monitor)
        self._apply_stats_settings()
        self.show_status("Ready")

    def show_status(self, message: str, timeout: int = 0) -> None:
        """Say something on the status line, optionally for `timeout` ms.

        Stands in for QStatusBar.showMessage() -- same contract, including
        "a timed message leaves the line blank when it lapses" -- but as a
        widget, so the run bar can sit beside the text instead of being
        painted over by it. A new message always wins, and cancels any
        countdown the last one was running on.
        """
        self._status_timer.stop()
        self._status_label.setText(message)
        if timeout > 0:
            self._status_timer.start(timeout)

    def status_message(self) -> str:
        """What the status line currently reads. The counterpart of
        QStatusBar.currentMessage(), which no longer sees our text."""
        return self._status_label.text()

    def _canvas_pages(self) -> list:
        """Pages that actually have a scene and a view. Report pages are
        documents, so every window-wide *canvas* setting — snap, LOD, the
        GPU viewport, colour muting — has nothing on them to apply to."""
        return [page for page in self._dashboard_pages.values()
                if hasattr(page, "view") and hasattr(page, "scene")]

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
        view = self._active_canvas_view()
        self._zoom_indicator.setText(f"{round(view.zoom * 100)}%")
        # A locked page has no zoom to set, so the one control that would
        # set it says so rather than sitting there doing nothing when
        # clicked.
        locked = bool(getattr(view, "navigation_locked", False))
        self._zoom_indicator.setEnabled(not locked)
        self._zoom_indicator.setToolTip(
            "This page is locked — unlock it to zoom or pan"
            if locked else "Canvas zoom — click to reset to 100%")

    # ---------------------------------------------------------------- docks

    def _build_docks(self) -> None:
        """Plain QDockWidgets: drag, float, tab and close all come from Qt.

        Collapsing is closing (dock.setVisible(False)), not shrinking -- a
        tabified dock cannot be shrunk narrower than its own tab bar, which
        is what made an earlier custom-rail attempt bottom out at a ~26px
        strip of rotated labels. Closed is 0px and needs no custom layout
        code at all. dock_edges' strips are the per-edge collapse control;
        a dock's own X still closes just that one panel.
        """
        host = self._dock_host

        # -------------------------------------------------------- library
        self.library_panel = LibraryPanel(self.registry, self.favorites)
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
        self.library_tree.insert_frame_requested.connect(
            self._insert_component_at_view_center)
        self.library_tree.rename_user_frame_requested.connect(
            self._rename_user_frame)
        self.library_tree.move_user_frame_requested.connect(
            self._move_user_frame)
        self.library_tree.delete_user_frame_requested.connect(
            self._delete_user_frame)

        # ----------------------------------------------- properties/code/log
        # one tab group: all three answer "what is this node doing", and the
        # right-hand column is the only place tall enough for a code editor
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

        self.log_console = LogConsole(self.graph, self.engine)
        self.log_dock = QDockWidget("Log", host)
        self.log_dock.setObjectName("dock_log")
        self.log_dock.setWidget(self.log_console)
        host.addDockWidget(Qt.RightDockWidgetArea, self.log_dock)

        host.tabifyDockWidget(self.properties_dock, self.editor_dock)
        host.tabifyDockWidget(self.editor_dock, self.log_dock)
        self.properties_dock.raise_()
        host.resizeDocks([self.properties_dock], [420], Qt.Horizontal)

        # ------------------------------------------------------ inspector
        # on its own at the bottom: it is a wide, table-shaped panel, so it
        # wants the window's full width rather than a 420px column
        self.inspector_panel = InspectorPanel(self.graph, self.engine)
        self.inspector_dock = QDockWidget("Inspector", host)
        self.inspector_dock.setObjectName("dock_inspector")
        self.inspector_dock.setWidget(self.inspector_panel)
        host.addDockWidget(Qt.BottomDockWidgetArea, self.inspector_dock)
        host.resizeDocks([self.inspector_dock], [260], Qt.Vertical)

        # every dock that belongs to the model canvas alone, in the order a
        # reset should put them back
        self._model_docks = [
            self.library_dock, self.properties_dock, self.editor_dock,
            self.log_dock, self.inspector_dock,
        ]
        # which of them to restore on the way back from a dashboard page --
        # switching pages must not reopen what someone deliberately closed
        self._docks_open_on_model_page = list(self._model_docks)

        # the edge strips go inside the dock ring, so takeCentralWidget()
        # first: setCentralWidget() deletes whatever it replaces, and the
        # canvas stack is about to be a child of the replacement
        host.takeCentralWidget()
        container, self._edge_strips = dock_edges.install(
            self._canvas_stack, host, self._model_docks)
        host.setCentralWidget(container)

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
        # a fresh central widget stacks above the resize grips — put them back
        frameless = getattr(self, "_frameless", None)
        if frameless is not None:
            frameless.raise_grips()

    # -------------------------------------------------------------- actions

    def _build_actions(self) -> None:
        # The menus hang off the real menu bar with a native frame, or off a
        # plain QMenu (shown from the title bar's hamburger) with ours. Both
        # answer addMenu()/actions() the same way, so the building code below
        # does not care which it got — see self._menu_root.
        self._menu_root = QMenu(self) if self._custom_frame else self.menuBar()

        # the group each act() below lands in on the Keyboard Shortcuts page;
        # rebound as the sections go by, so no call has to name its own
        section = {"name": "File"}

        def act(text: str, shortcut, slot, menu_only: bool = True) -> QAction:
            action = QAction(text, self)
            if shortcut is not None:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            # registering applies any saved rebind, so it has to happen
            # before the action is ever reachable from a menu
            self.shortcuts.register(action, section["name"])
            return action

        # --- file
        self.action_new = act("&New", QKeySequence.New, self._new_project)
        self.action_open = act("&Open…", QKeySequence.Open, self._open_dialog)
        self.action_save = act("&Save", QKeySequence.Save, self._save)
        self.action_save_as = act("Save &As…", QKeySequence("Ctrl+Shift+S"),
                                  self._save_as)
        self.action_export_workflow = act(
            "&Export Workflow…", None, self._export_workflow)
        self.action_desktop_shortcut = act(
            "Create &Desktop Shortcut…", None, self._create_desktop_shortcut)
        self.action_quit = act("&Quit", QKeySequence.Quit, self.close)

        section["name"] = "Edit"
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
        self.action_find_node = act("Find Node…", QKeySequence("Ctrl+F"),
                                    self._find_node)
        # scoped to the canvas, the same way the code editor scopes its own
        # Ctrl+F: two window-wide Ctrl+Fs would be an ambiguous overload and
        # neither would fire. Focus decides which find you get.
        self.action_find_node.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.view.addAction(self.action_find_node)
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

        section["name"] = "Run"
        # --- run
        self.action_run = act("Run All", Qt.Key_F5, self._run_all)
        self.action_run_selected = act("Run Selected", Qt.Key_F6,
                                       self._run_selected)
        self.action_cancel = act("Cancel", Qt.Key_Escape, self.engine.cancel)
        self.action_cancel.setEnabled(False)
        self.action_reset_caches = act("Reset Caches", QKeySequence("Ctrl+Shift+R"),
                                       self._reset_caches)
        self.action_reset_selected_caches = act(
            "Reset Selected Caches", QKeySequence("Ctrl+R"),
            self._reset_caches_for_selection)

        self.action_run.setIcon(toolbar_style.toolbar_icon("run_all"))
        self.action_run_selected.setIcon(
            toolbar_style.toolbar_icon("run_selected"))
        self.action_cancel.setIcon(toolbar_style.toolbar_icon("cancel"))
        self.action_reset_caches.setIcon(
            toolbar_style.toolbar_icon("reset_caches"))
        self.action_reset_selected_caches.setIcon(
            toolbar_style.toolbar_icon("reset_caches"))

        section["name"] = "Tools"
        # --- tools
        self.action_settings = act("&Settings…", QKeySequence("Ctrl+,"),
                                   self._show_settings)
        self.action_stats = act("&Statistics…", QKeySequence("Ctrl+Shift+I"),
                                self._show_stats)
        self.action_packages = act("Manage &Packages…", None,
                                   self._show_packages)
        self.action_ai_settings = act("AI Assistant &Settings…", None,
                                      self._show_ai_settings)
        self.action_secrets = act("Sec&rets…", None, self._show_secrets)

        file_menu = self._menu_root.addMenu("&File")
        for action in (self.action_new, self.action_open, self.action_save,
                       self.action_save_as, self.action_export_workflow):
            file_menu.addAction(action)
        self._recent_menu = file_menu.addMenu("Open &Recent")
        self._rebuild_recent_menu()
        self._build_examples_menu(file_menu)
        file_menu.addSeparator()
        file_menu.addAction(self.action_desktop_shortcut)
        file_menu.addSeparator()
        file_menu.addAction(self.action_quit)

        edit_menu = self._menu_root.addMenu("&Edit")
        for action in (self.action_undo, self.action_redo):
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        for action in (self.action_cut, self.action_copy, self.action_paste,
                       self.action_duplicate, self.action_rename,
                       self.action_select_all):
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.action_find_node)
        edit_menu.addAction(self.action_add_frame)
        align_menu = edit_menu.addMenu("Align")
        for action in (self.action_align_left, self.action_align_top,
                       self.action_dist_h, self.action_dist_v):
            align_menu.addAction(action)

        run_menu = self._menu_root.addMenu("&Run")
        for action in (self.action_run, self.action_run_selected,
                       self.action_cancel):
            run_menu.addAction(action)
        run_menu.addSeparator()
        for action in (self.action_reset_selected_caches,
                       self.action_reset_caches):
            run_menu.addAction(action)

        tools_menu = self._menu_root.addMenu("&Tools")
        tools_menu.addAction(self.action_stats)
        tools_menu.addAction(self.action_settings)
        tools_menu.addSeparator()
        tools_menu.addAction(self.action_packages)
        tools_menu.addAction(self.action_ai_settings)
        tools_menu.addAction(self.action_secrets)

        section["name"] = "View"
        view_menu = self._menu_root.addMenu("&View")
        self.action_toggle_panels = act(
            "Hide All Panels", QKeySequence("Ctrl+Shift+H"),
            self.toggle_all_panels)
        view_menu.addAction(self.action_toggle_panels)
        # the label has to say which way the toggle goes, and the panels can
        # be collapsed from their own edge arrows without this ever firing
        view_menu.aboutToShow.connect(self._sync_toggle_panels_action)
        if self._custom_frame:
            self.action_titlebar_shortcuts = QAction(
                "Shortcuts on Title-Bar Buttons", self)
            self.action_titlebar_shortcuts.setCheckable(True)
            self.action_titlebar_shortcuts.setChecked(self.settings.value(
                "window/titlebar_shortcuts", True, type=bool))
            self.action_titlebar_shortcuts.toggled.connect(
                self._set_titlebar_shortcuts)
            view_menu.addAction(self.action_titlebar_shortcuts)
        view_menu.addSeparator()
        for dock in self.findChildren(QDockWidget):
            view_menu.addAction(dock.toggleViewAction())

        section["name"] = "Help"
        self.action_docs = act("&Documentation", Qt.Key_F1, self._show_docs)
        self.action_github = act("flograph on &GitHub", None, self._open_github)
        help_menu = self._menu_root.addMenu("&Help")
        help_menu.addAction(self.action_docs)
        help_menu.addSeparator()
        help_menu.addAction(self.action_github)

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

        self._build_window_chrome()

    def _build_window_chrome(self) -> None:
        """The run actions plus (with a custom frame) our title bar. Native
        frame: a plain toolbar carries the run actions, exactly as before."""
        if self._custom_frame:
            self._title_bar = window_frame.TitleBar(self, self._menu_root)
            self.setMenuWidget(self._title_bar)
            self._frameless = window_frame.FramelessResizer(
                self, self._title_bar)
            self._title_bar.set_compact(self.settings.value(
                "window/titlebar_compact", False, type=bool))
            self._title_bar.set_show_shortcuts(self.settings.value(
                "window/titlebar_shortcuts", True, type=bool))
            self._title_bar.refresh_title()
        else:
            toolbar = QToolBar("Main", self)
            toolbar_style.style_toolbar(toolbar)
            self.addToolBar(toolbar)
            for action in (self.action_run, self.action_run_selected,
                           self.action_cancel):
                toolbar.addAction(action)
            toolbar.addSeparator()
            toolbar.addAction(self.action_reset_selected_caches)
            toolbar.addAction(self.action_reset_caches)

    def _recent_files_existing(self) -> list[str]:
        """Recent workflow paths that still exist — for the title bar's
        project switcher and the Open Recent menu."""
        return [p for p in self._recent_files() if Path(p).exists()][:MAX_RECENT]

    def set_custom_frame(self, enabled: bool) -> None:
        """Stored now, applied at next launch — swapping the window flags and
        re-parenting the whole menu tree live is not worth the fragility."""
        self.settings.setValue("window/custom_frame", bool(enabled))
        self.show_status(
            "Custom window frame — restart flograph to apply", 5000)

    def set_titlebar_compact(self, compact: bool) -> None:
        """Icon-only title-bar buttons. Applies at once — no restart.
        Reached from Settings and the title bar's right-click menu."""
        self.settings.setValue("window/titlebar_compact", bool(compact))
        title_bar = getattr(self, "_title_bar", None)
        if title_bar is not None:
            title_bar.set_compact(bool(compact))
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            QTimer.singleShot(
                0, lambda: self._settings_dialog.refresh_from(self))

    def _set_titlebar_shortcuts(self, show: bool) -> None:
        """Show/hide the (F5)/(F6)/(Esc) suffixes on the title-bar run
        buttons. Reached from the View menu and the title bar's own
        right-click menu, so it keeps the View action's tick in step."""
        self.settings.setValue("window/titlebar_shortcuts", bool(show))
        action = getattr(self, "action_titlebar_shortcuts", None)
        if action is not None and action.isChecked() != bool(show):
            action.blockSignals(True)
            action.setChecked(bool(show))
            action.blockSignals(False)
        title_bar = getattr(self, "_title_bar", None)
        if title_bar is not None:
            title_bar.set_show_shortcuts(bool(show))

    def set_snap_enabled(self, enabled: bool) -> None:
        self.snap_enabled = enabled
        self.settings.setValue("snap/enabled", enabled)
        self._apply_snap_settings()

    def set_grid_step(self, step: float) -> None:
        self.grid_step = step
        self.settings.setValue("snap/step", step)
        self._apply_snap_settings()

    def set_grid_visible(self, visible: bool) -> None:
        """Draw (or hide) the background grid on the canvas and every
        dashboard page. Snapping is a separate setting and is left alone."""
        self.grid_visible = visible
        self.settings.setValue("grid/visible", visible)
        self._apply_snap_settings()

    def set_minimap_enabled(self, enabled: bool) -> None:
        self.minimap_enabled = enabled
        self.settings.setValue("canvas/minimap_enabled", enabled)
        self.view.minimap.setVisible(enabled)

    def set_port_labels_enabled(self, enabled: bool) -> None:
        """Canvas-wide: float every port's name beside its pin. Nodes that
        have been toggled on their own keep their own setting."""
        self.port_labels_enabled = enabled
        self.settings.setValue("canvas/port_labels", enabled)
        self.scene.set_port_labels_enabled(enabled)

    def set_flow_pins_enabled(self, enabled: bool) -> None:
        """Canvas-wide: show every node's flow pins, the ones an order edge
        joins. Nodes that have been set on their own keep their own setting,
        and a pin with a wire on it is drawn either way."""
        self.flow_pins_enabled = enabled
        self.settings.setValue("canvas/flow_pins", enabled)
        self.scene.set_flow_pins_enabled(enabled)

    def set_double_click_action(self, action: str) -> None:
        """What a plain double-click on a node's body opens: "properties",
        "code" or "rename"."""
        self.double_click_action = action
        self.settings.setValue("canvas/double_click_action", action)

    def set_reveal_ports_key(self, key: int) -> None:
        """Which key, held over the canvas, floats every port's name."""
        self.reveal_ports_key = int(key)
        self.settings.setValue("canvas/reveal_ports_key", int(key))
        self.view.set_reveal_ports_key(int(key))

    def set_scrollbars_enabled(self, enabled: bool) -> None:
        """Show the canvas scroll bars, on the main view and every
        dashboard page's view."""
        self.scrollbars_enabled = enabled
        self.settings.setValue("canvas/scrollbars", enabled)
        views = [self.view] + [page.view for page in self._canvas_pages()]
        for view in views:
            view.set_scrollbars_enabled(enabled)

    def set_cache_compression_enabled(self, enabled: bool) -> None:
        """Whether saving zlib-compresses the cache side-car's blobs.

        Read at the moment a save starts, so flipping it mid-session applies
        to the next save; blobs already on disk keep whatever era wrote them,
        and load_blob sniffs each one, so nothing needs migrating."""
        self.cache_compression_enabled = bool(enabled)
        self.settings.setValue("saving/compress_cache", bool(enabled))

    def set_compact_nodes(self, enabled: bool) -> None:
        """Canvas-wide: draw plain nodes as a fixed square with the name
        above, rather than the wide labelled box. Cards keep their size —
        their content is the point of them."""
        self.compact_nodes = enabled
        self.settings.setValue("canvas/compact_nodes", enabled)
        self.scene.set_compact_nodes(enabled)

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
        views = [self.view] + [page.view for page in self._canvas_pages()]
        for view in views:
            view.viewport().update()
        self.view.minimap.update()
        self.page_bar.update()

    def _apply_snap_settings(self) -> None:
        """Push the current snap toggle/step and grid visibility onto every
        scene and repaint so the grid redraws at the new resolution. Applies
        to node/frame moves and resizes on the canvas and dashboard tiles."""
        views = [self.view]
        scenes = [self.scene]
        for page in self._canvas_pages():
            scenes.append(page.scene)
            views.append(page.view)
        for scene in scenes:
            scene.snap_enabled = self.snap_enabled
            scene.grid_step = self.grid_step
            scene.grid_visible = self.grid_visible
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
        views = [self.view] + [page.view for page in self._canvas_pages()]
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
        self.show_status(
            "GPU acceleration isn't available here — reverted to standard "
            "rendering.", 6000)

    # ------------------------------------------------------------ statistics

    def set_stats_bar_enabled(self, enabled: bool) -> None:
        self.stats_bar_enabled = enabled
        self.settings.setValue("stats/bar_enabled", enabled)
        self.resource_monitor.bar.setVisible(enabled)

    def set_stats_sampling_enabled(self, enabled: bool) -> None:
        self.stats_sampling_enabled = enabled
        self.settings.setValue("stats/sampling_enabled", enabled)
        self.engine.sampling_enabled = enabled

    def set_stats_history_limit(self, limit: int) -> None:
        self.stats_history_limit = limit
        self.settings.setValue("stats/history_limit", limit)
        self.engine.history.set_limit(limit)

    def set_engine_max_workers(self, workers: int) -> None:
        """How many nodes may run at once; 0 means let the engine decide.

        Takes effect on the next run rather than the one in flight — the plan
        a run is working through was built and seeded against a limit, and
        moving it underneath would be changing the rules mid-game for no gain
        the user can see.
        """
        self.engine_max_workers = workers
        self.settings.setValue("engine/max_workers", workers)
        self.engine.max_workers = workers

    def _apply_stats_settings(self) -> None:
        self.resource_monitor.bar.setVisible(self.stats_bar_enabled)
        self.engine.sampling_enabled = self.stats_sampling_enabled
        self.engine.history.set_limit(self.stats_history_limit)
        self.engine.max_workers = self.engine_max_workers

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
        scenes = [self.scene] + [page.scene for page in self._canvas_pages()]
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
        # A param edit still waiting on the typing timer has not reached the
        # undo stack yet, so undoing now would step over it and revert
        # whatever came before instead.
        self.params_panel.flush_pending()
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

    def _flush_pending_edits(self) -> None:
        """Force a still-open grid cell editor to commit before a run reads
        node.params. Qt only commits a cell's editor on Tab/click-away/
        FocusOut, so a value just typed and not yet closed off is invisible
        to node.params — and so to the very run meant to pick it up. F5/F6
        and the run-node menu actions don't touch focus on their own, so
        without this a run can silently execute against stale data."""
        if self._focused_spreadsheet() is not None:
            QApplication.focusWidget().clearFocus()
        # Same hazard, different editor: a text param is held back until
        # typing pauses, so hitting F5 mid-word would otherwise run against
        # the value as it was one keystroke ago. Floating node windows carry
        # their own params panel and the same debounce, so they get the same
        # treatment — a run started from the main window must see what was
        # typed in one of them.
        self.params_panel.flush_pending()
        for window in list(self._node_windows.values()):
            window.flush_pending()

    def _on_memory_pressure(self, message: str) -> None:
        """Said once, when the project becomes the reason memory is tight.

        A run is when this matters most and it used to be when it was
        dropped: the status line is busy saying what is running, so the
        message was thrown away rather than shown. It is carried into the run
        line instead — the one moment the user is watching that line is the
        moment the flow is filling the machine up.
        """
        self._run_pressure_note = message
        self._mark_heavy_nodes(bool(message))
        if self.engine.active:
            self._update_run_status()
            return
        if message:
            self.show_status(message, 15000)

    def _on_disk_pressure(self, message: str) -> None:
        """Said once when the project's drive is running out of room.

        Same plumbing as memory pressure — carried on the run line during a
        run rather than dropped — but with no canvas marks: memory names the
        nodes to act on, disk has no per-node answer."""
        self._disk_note = message
        if self.engine.active:
            self._update_run_status()
            return
        if message:
            self.show_status(message, 15000)

    def _mark_heavy_nodes(self, under_pressure: bool) -> None:
        """Amber the few steps holding the most, or clear every mark.

        The status bar can say memory is short; only the canvas can say
        *which step*, and that is the part somebody can act on without
        knowing how the app works — it is the node to put a Max rows on, or
        to filter earlier. Marks are cleared wholesale rather than tracked,
        because the heaviest set changes as the flow runs and a stale badge
        on a node that is no longer heavy is worse than no badge.
        """
        heavy = set()
        if under_pressure:
            heavy = {nid for nid, _ in self.engine.cache.heaviest(3)}
        for node_id, item in self.scene.node_items.items():
            item.set_heavy(node_id in heavy)

    # ----------------------------------------------------------- run status

    def _run_begin(self) -> None:
        """A run started. Stands until the first node claims the floor,
        which is a moment away — the plan is already built by now."""
        self._run_index = 0
        self._run_total = 0
        self._run_fraction = 0.0
        self._run_node_label = ""
        self._run_node_started = time.monotonic()
        self._run_inflight.clear()
        self._run_last_output = time.monotonic()
        self._run_had_output = False
        self._run_prior = None
        self._run_bar.setValue(0)
        self._run_bar.show()
        self._run_tick.start()
        self.show_status("Running…")

    def _run_node_begin(self, node_id: str, label: str,
                        index: int, total: int) -> None:
        self._run_node_label = label
        self._run_index = index
        self._run_total = total
        self._run_fraction = 0.0
        self._run_node_started = time.monotonic()
        self._run_inflight[node_id] = self._run_node_started
        self._run_last_output = self._run_node_started
        self._run_had_output = False
        # What it cost last time it finished, if it has this session. Turns
        # "this is taking a while" into "this is taking longer than usual".
        self._run_prior = self.engine.history.last_wall_time(node_id)
        self._update_run_status()

    def _run_node_end(self, node_id: str) -> None:
        """A node left the floor. Whoever is still on it keeps the line."""
        self._run_inflight.pop(node_id, None)
        if len(self._run_inflight) == 1:
            # Back to a single node: name it again, and start its stopwatch
            # from when *it* started rather than from now.
            remaining = next(iter(self._run_inflight))
            node = self.graph.nodes.get(remaining)
            if node is not None:
                self._run_node_label = node.label
                self._run_node_started = self._run_inflight[remaining]
                self._run_prior = self.engine.history.last_wall_time(remaining)
                self._run_fraction = node.progress
        self._update_run_status()

    def _run_end(self) -> None:
        self._run_tick.stop()
        self._run_bar.hide()
        self._run_node_label = ""
        self._run_inflight.clear()

    def _update_run_status(self) -> None:
        """Compose the one line that says what the run is doing.

        Nodes can run several at a time, and a line naming one of them would
        be picking a favourite — so it names a node only while that is
        unambiguous, and counts them otherwise. The per-node detail (its
        fraction, what it usually costs) goes with the name: attached to a
        count it would be describing something the line has not identified.
        """
        if not self._run_node_label and not self._run_pressure_note \
                and not self._disk_note:
            return
        concurrent = len(self._run_inflight)
        if concurrent > 1:
            # Elapsed for the run's oldest node, not the newest: with several
            # in flight, the one worth timing is the one that has been going
            # longest — it is the one that might be stuck.
            elapsed = time.monotonic() - min(self._run_inflight.values())
            parts = [f"Running {concurrent} nodes"]
        elif self._run_node_label:
            elapsed = time.monotonic() - self._run_node_started
            parts = [f"Running {self._run_node_label}"]
        else:
            # Nothing has claimed the floor yet, but there is a pressure note
            # to carry — the line exists for that alone rather than saying
            # "Running" and naming nobody.
            elapsed = 0.0
            parts = []
        if self._run_total:
            parts.append(f"node {self._run_index} of {self._run_total}")
        if self._run_fraction and concurrent <= 1:
            parts.append(f"{self._run_fraction:.0%}")
        # Only once it has been going long enough to be worth timing —
        # a stopwatch on a step that takes 200ms is noise.
        if elapsed >= 1.0:
            timing = format_seconds(elapsed)
            if self._run_prior and concurrent <= 1:
                timing += f" (usually {format_seconds(self._run_prior)})"
            parts.append(timing)
        quiet = time.monotonic() - self._run_last_output
        if quiet >= QUIET_NODE_AFTER_S:
            # issues.md #4: a node that hangs looks exactly like a node that
            # is merely slow. Saying it has gone silent, and that Cancel
            # exists, is the difference between the two.
            if not self._run_had_output:
                # never said anything, so the elapsed time above already is
                # the silence — printing the same number twice reads badly
                parts.append("no output yet — Cancel to stop it")
            else:
                parts.append(f"quiet for {format_seconds(quiet)} — "
                             f"Cancel to stop it")
        if self._run_pressure_note:
            # Last, so it never pushes the thing the user asked for off the
            # front of the line, but present — this used to be dropped during
            # a run, which is the one time it is worth saying.
            parts.append(self._run_pressure_note)
        if self._disk_note:
            parts.append(self._disk_note)
        self.show_status("  ·  ".join(parts))
        self._run_bar.setValue(int(100 * self._run_completion()))

    def _run_completion(self) -> float:
        """How far through the plan the run is, 0..1.

        Nodes already finished, plus however far the current one says it
        is. The total is the plan as built, so a run that prunes a failed
        branch can finish ahead of the bar rather than behind it.

        Finished is "started minus still running", which with one node in
        flight is the index behind it and with several is the only honest
        count — the highest index started says nothing about how many of
        them are done.
        """
        if not self._run_total:
            return 0.0
        finished = max(0, self._run_index - max(1, len(self._run_inflight)))
        fraction = self._run_fraction if len(self._run_inflight) <= 1 else 0.0
        return min(1.0, (finished + fraction) / self._run_total)

    # --------------------------------------------------------------- wiring

    def _wire_engine(self) -> None:
        engine = self.engine

        def on_started() -> None:
            self.action_cancel.setEnabled(True)
            self.action_run.setEnabled(False)
            self.action_run_selected.setEnabled(False)
            self._run_begin()

        def on_node_started(node_id: str, index: int, total: int) -> None:
            node = self.graph.nodes.get(node_id)
            label = node.label if node is not None else node_id
            self._run_node_begin(node_id, label, index, total)

        def on_node_progress(node_id: str, fraction: float) -> None:
            self._run_fraction = fraction
            self._run_last_output = time.monotonic()
            self._run_had_output = True
            self._update_run_status()

        def on_node_logged(node_id: str, line: str, stream: str) -> None:
            # A node writing to the log is alive even if it reports no
            # fraction, so it should not be called quiet — see _run_status.
            self._run_last_output = time.monotonic()
            self._run_had_output = True

        def on_finished(ok: bool) -> None:
            self.action_cancel.setEnabled(False)
            self.action_run.setEnabled(True)
            self.action_run_selected.setEnabled(True)
            self._run_end()
            message = "Run finished" if ok else "Run finished with errors"            # Only pins the graph has moved on from get a mention. A frozen
            # source node — which is most of them — never appears here, so
            # this stays a warning worth reading rather than noise.
            stale = self._refresh_stale_pins()
            if stale:
                names = ", ".join(sorted(self.graph.node(n).label
                                         for n in stale)[:3])
                more = f" (+{len(stale) - 3})" if len(stale) > 3 else ""
                message += (f" — {len(stale)} frozen node"
                            f"{'s' if len(stale) > 1 else ''} did not "
                            f"refresh and no longer match their inputs: "
                            f"{names}{more}")
            self.show_status(message, 5000 if not stale else 15000)

        def on_joined(additions: list) -> None:
            if not additions:
                return
            n = len(additions)
            self.show_status(
                f"{n} node{'s' if n > 1 else ''} joined the running "
                "plan", 5000)

        engine.run_started.connect(on_started)
        engine.run_joined.connect(on_joined)
        engine.node_started.connect(on_node_started)
        # Both outcomes take the node off the floor, so the line can go back
        # to naming whoever is left.
        engine.node_succeeded.connect(self._run_node_end)
        engine.node_failed.connect(
            lambda node_id, _error: self._run_node_end(node_id))
        engine.node_progress.connect(on_node_progress)
        engine.node_log.connect(on_node_logged)
        engine.run_finished.connect(on_finished)
        engine.node_failed.connect(self._on_node_failed)
        engine.node_succeeded.connect(self.editor_panel.on_node_succeeded)
        engine.node_succeeded.connect(self._on_figure_node_succeeded)
        engine.node_succeeded.connect(self._on_plotly_node_succeeded)
        engine.node_succeeded.connect(self._on_table_viewer_node_succeeded)
        engine.node_succeeded.connect(self._on_grid_node_succeeded)
        engine.node_succeeded.connect(self._on_kpi_node_succeeded)
        engine.node_succeeded.connect(self._on_image_node_succeeded)
        engine.node_succeeded.connect(self._on_slicer_node_succeeded)
        engine.node_succeeded.connect(self._on_control_node_succeeded)
        engine.node_succeeded.connect(self._on_browser_node_succeeded)
        # cards fade their output previews while a re-run for them is queued;
        # the engine owns that set, the scene paints from a copy of it
        engine.request_changed.connect(
            lambda: self.scene.set_requested_nodes(engine.requested_nodes))
        # every run: a report card's content lives upstream of it, so the
        # cards that changed are not the ones that ran
        engine.run_finished.connect(lambda *_: self._refresh_report_cards())
        # ...and on a param change, because a *cosmetic* one (chart layout)
        # deliberately never runs anything
        self.graph.events.param_changed.connect(
            lambda *_: self._report_refresh.start())
        self.graph.events.preview_enabled_changed.connect(
            self._on_preview_enabled_changed)

    def _wire_canvas(self) -> None:
        self.view.add_node_requested.connect(self._show_add_node_menu)
        self.view.palette_requested.connect(self._show_palette)
        self.view.node_dropped.connect(self._add_node_at)
        self.view.frame_dropped.connect(self._insert_component_at)
        self.view.files_dropped.connect(self._add_reader_nodes_for_files)
        self.view.node_context_requested.connect(self._show_node_menu)
        self.view.frame_context_requested.connect(self._show_frame_menu)
        self.view.order_context_requested.connect(self._show_order_edge_menu)
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.scene.node_double_clicked.connect(self._on_node_double_clicked)
        self.scene.node_window_requested.connect(self.open_node_window)
        self.scene.node_rename_requested.connect(self._rename_node)
        self.scene.wire_dropped.connect(self._on_wire_dropped)
        self.scene.button_fired.connect(self._on_button_fired)
        self.scene.slicer_changed.connect(self._on_slicer_changed)
        self.scene.control_changed.connect(self._on_control_changed)
        self.scene.frame_run_requested.connect(self._on_frame_run_requested)
        self.scene.tables_kept.connect(self._on_tables_kept)

    def _on_tables_kept(self, node_ids: list) -> None:
        """Say when cutting a wire wrote the linked data into a Table — it
        is the one disconnect that also edits a node, and undo takes both
        back together."""
        labels = ", ".join(self.graph.nodes[n].label for n in node_ids
                           if n in self.graph.nodes)
        if labels:
            self.show_status(
                f"{labels}: kept the linked contents in the table", 5000)

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
        # the node's own first output, not a hardcoded "figure": a figure
        # card is free to name its port anything (Chart per Value emits
        # "figures"), and every other card kind already reads it this way
        port = node.spec.outputs[0].name if node.spec.outputs else "figure"
        item.set_figure(entry.outputs.get(port) if entry else None)

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

    # ------------------------------------------------------ open in browser

    def _can_open_in_browser(self, node_id: str) -> bool:
        """Whether this node has HTML worth handing to a browser.

        Restricted to webview cards rather than "anything that coerces" —
        a raw string always coerces, so the looser rule would offer the
        action on every node that happens to output text."""
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "webview":
            return False
        from .browser import can_open
        return can_open(node, self.engine.cache.get(node_id))

    def _on_browser_node_succeeded(self, node_id: str) -> None:
        """Keep an open browser tab level with the canvas.

        The page is rewritten in place on every run of a node that has been
        opened, so refreshing the tab shows what the card is showing. Without
        this the file was written once and the tab quietly went stale — the
        one failure mode where the user is looking at an old chart with
        nothing on screen to say so."""
        from .browser import refresh_node
        node = self.graph.nodes.get(node_id)
        if node is not None:
            refresh_node(node, self.engine.cache.get(node_id))

    def _open_in_browser(self, node_id: str) -> Optional[str]:
        """Open a webview node's current output in the desktop browser."""
        from .browser import open_node_from
        node = self.graph.nodes.get(node_id)
        if node is None:
            return None
        # Load it back if the project was opened without reading its cache:
        # the user asked for this one node's output, which is exactly when
        # paying for the read is right.
        self.engine.cache.outputs_for(node_id)
        return open_node_from(self, node, self.engine.cache.get(node_id))

    def _refresh_report_cards(self) -> None:
        """Re-render every report card on the canvas. Blunt on purpose:
        working out which cards embed which upstream node would duplicate
        the embed parser for no gain.

        Blunt is not the same as free, though — each card re-renders its
        markdown and re-reads its embeds — so the param-change path goes
        through `_report_refresh` to coalesce a burst of edits into one
        pass. A finished run calls this directly; there is only one of those.
        """
        self._report_refresh.stop()
        for item in self.scene.node_items.values():
            if getattr(item, "report_card", False):
                item.refresh_report()
        # Same trigger, same coalescing: a card whose page is open in a
        # browser has that page rewritten here too.
        self._refresh_open_report_cards()

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
        if not node.canvas_preview_enabled:
            return
        item = self.scene.node_items.get(node_id)
        merged = self._merged_linked_sheet(node_id)
        if item is not None and merged is not None:
            item.show_linked_sheet(merged)

    def _merged_linked_sheet(self, node_id: str):
        """The linked-refresh merge of a Table node's cached input with its
        stored sheet, as a sheet dict — None when there's no usable input."""
        from flograph.engine.introspect import merged_linked_sheet
        return merged_linked_sheet(self.graph, self.engine.cache, node_id)

    def _table_import_source(self, node_id: str):
        """The cached upstream DataFrame feeding a Table node's input, or
        None when unconnected / not run / not a frame."""
        from flograph.engine.introspect import linked_table_source
        return linked_table_source(self.graph, self.engine.cache, node_id)

    def _import_input_into_table(self, node_id: str) -> None:
        """Snapshot the linked data into the node's stored sheet (keeping
        the user's own columns), one undoable step."""
        import json as _json
        merged = self._merged_linked_sheet(node_id)
        if merged is None:
            return
        self.undo_stack.push(SetParamCommand(
            self.graph, node_id, "data", _json.dumps(merged), merge=False))
        self.show_status(
            "Input copied into the table — the cells are yours to edit now, "
            "though a run will refresh the input's columns again", 5000)

    def _on_image_node_succeeded(self, node_id: str) -> None:
        """Show what the run actually loaded. Only matters when the source
        came in on the wire — one set in the node's own params is already on
        the card, drawn without any run at all."""
        node = self.graph.nodes.get(node_id)
        # A PDF card resolves its source exactly as an image card does — a
        # path, a data: URI or base64 — so one handler serves both.
        if node is None or card_kind(node) not in ("image", "pdf"):
            return
        item = self.scene.node_items.get(node_id)
        if item is None:
            return
        entry = self.engine.cache.get(node_id)
        port = node.spec.outputs[0].name if node.spec.outputs else "image"
        payload = entry.outputs.get(port) if entry else None
        # "source" is what the card can re-resolve: a path, a data: URI or a
        # base64 blob. "path" is None whenever the image never was a file.
        source = payload.get("source") if isinstance(payload, dict) else None
        item.set_image_result(source)

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
        engine.node_succeeded), by re-enabling a disabled preview, and by
        the resident-batch refresh, so a card heals no matter who brought
        its value back."""
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
        elif kind == "control":
            self._on_control_node_succeeded(node_id)
        elif kind == "grid":
            self._on_grid_node_succeeded(node_id)
        elif kind == "kpi":
            self._on_kpi_node_succeeded(node_id)

    # ------------------------------------------- cache data arriving late

    def _on_cache_became_resident(self, node_id: str) -> None:
        """One spilled entry is readable again. Batched: an open warms the
        cards' worth of entries in one breath, and each arrival rebuilding
        a web view or a table model on its own would thrash."""
        self._resident_batch.add(node_id)
        self._resident_timer.start()
        self._tick_warm_watch()

    def _flush_resident_batch(self) -> None:
        batch, self._resident_batch = self._resident_batch, set()
        if not batch:
            return
        # A slicer or control shows what its UPSTREAM entry says, so data
        # arriving upstream has to refresh the readers below it too.
        extra = set()
        for node_id in batch:
            for downstream_id in self.graph.downstream(node_id):
                node = self.graph.nodes.get(downstream_id)
                if node is not None and card_kind(node) in ("slicer",
                                                            "control"):
                    extra.add(downstream_id)
        for node_id in batch | extra:
            self._refresh_node_card(node_id)
            for page in self._dashboard_pages.values():
                scene = getattr(page, "scene", None)
                if scene is not None:
                    scene.refresh_node_tiles(node_id)

    def _on_control_node_succeeded(self, node_id: str) -> None:
        """Re-read whatever this control's own inputs supplied on that run —
        a Choice's options, a Slider's bounds, a Date's calendar range. What
        makes a control configure itself from the data instead of from
        constants somebody typed."""
        node = self.graph.nodes.get(node_id)
        item = self.scene.node_items.get(node_id)
        if node is None or item is None or card_kind(node) != "control":
            return
        from flograph.engine.introspect import control_upstream
        item.set_control_upstream(
            control_upstream(self.graph, self.engine.cache, node_id))

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
        self.page_bar.set_view_mode_requested.connect(self._set_page_view_mode)
        self.page_bar.set_fit_to_window_requested.connect(
            self._set_page_fit_to_window)
        self.page_bar.export_page_requested.connect(self._export_report_pdf)
        self.page_bar.page_setup_requested.connect(self._edit_page_setup)
        self.page_bar.export_html_requested.connect(self._export_report_html)
        self.page_bar.current_page_changed.connect(
            self._on_current_page_changed)
        self.page_bar.model_tab_double_clicked.connect(self.toggle_all_panels)

    def _on_page_added(self, page: Page) -> None:
        if page.kind == "report":
            self._add_report_page(page)
            return
        widget = DashboardPage(self.graph, self.engine, self.undo_stack,
                               page.id, visuals_visible=self.visuals_visible)
        widget.visuals_visibility_changed.connect(self._set_visuals_visible)
        widget.scene.button_fired.connect(self._on_button_fired)
        widget.scene.slicer_changed.connect(self._on_slicer_changed)
        widget.scene.control_changed.connect(self._on_control_changed)
        widget.scene.sheet_edited.connect(self._on_dashboard_sheet_edited)
        widget.view.tile_dropped.connect(
            lambda node_id, pos, page_id=page.id:
            self._on_tile_dropped(page_id, node_id, pos))
        self._dashboard_pages[page.id] = widget
        widget.view.zoom_changed.connect(self._on_canvas_zoom_changed)
        widget.scene.snap_enabled = self.snap_enabled
        widget.scene.grid_step = self.grid_step
        widget.scene.grid_visible = self.grid_visible
        widget.view.set_scrollbars_enabled(self.scrollbars_enabled)
        self._set_canvas_viewport(widget.view, self.action_gpu_viewport.isChecked())
        self._canvas_stack.addWidget(widget)
        self.page_bar.add_page_tab(page)

    def _add_report_page(self, page: Page) -> None:
        from .report import ReportPage
        widget = ReportPage(self.graph, self.engine, self.undo_stack, page.id)
        widget.export_requested.connect(self._export_report_pdf)
        widget.page_setup_requested.connect(self._edit_page_setup)
        widget.export_html_requested.connect(self._export_report_html)
        # kept in the same dict as dashboards: everything the window does
        # with a page — switching, removing, disposing — is the same for
        # both, and only the two places that need the difference ask
        self._dashboard_pages[page.id] = widget
        self._canvas_stack.addWidget(widget)
        self.page_bar.add_page_tab(page)

    # ------------------------------------------------- a report card's own
    #
    # A report card is a report that never became a page: same markdown,
    # same embeds, same renderer — but it lives on the canvas, so it has no
    # toolbar to carry Export PDF or Open in Browser. These put both on the
    # one surface it does have, its right-click menu.

    def _render_report_card(self, node_id: str, for_print: bool):
        """A report card rendered at page width rather than card width.

        Card width is a canvas layout choice — how much room the node takes
        up next to its neighbours — and has nothing to do with the paper it
        is being printed onto. Rendering at the page's own body width is
        what stops a narrow card exporting a narrow column of text down the
        middle of an A4 sheet.
        """
        from flograph.core.page_setup import PageSetup
        from .report import render_card
        node = self.graph.nodes.get(node_id)
        if node is None:
            return None
        body = str(node.params.get("text", "") or "")
        return render_card(body, self.graph, self.engine.cache, node_id,
                           width=PageSetup().body_width_points(),
                           image_scale=2.0 if for_print else 1.0)

    def _export_report_card_pdf(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        rendered = self._render_report_card(node_id, for_print=True)
        if node is None or rendered is None:
            return
        path = self._save_path_for(node.label, ".pdf", "Export report as PDF",
                                   "PDF documents (*.pdf)")
        if path is None:
            return
        from .report import export_pdf
        try:
            export_pdf(rendered.document, path, title=node.label)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        if rendered.problems:
            QMessageBox.warning(
                self, "Exported with problems",
                f"Exported to {path}, but some embeds didn't resolve:\n\n• "
                + "\n• ".join(dict.fromkeys(rendered.problems)))
        else:
            self.show_status(f"Exported {path}", 6000)

    def _export_report_card_html(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        rendered = self._render_report_card(node_id, for_print=True)
        if node is None or rendered is None:
            return
        path = self._save_path_for(node.label, ".html",
                                   "Save report as HTML",
                                   "HTML documents (*.html)")
        if path is None:
            return
        from flograph.core.page_setup import PageSetup
        self._write_html(rendered, path, node.label, setup=PageSetup())

    def _open_report_card_in_browser(self, node_id: str) -> None:
        """The card as one self-contained HTML file, handed to the desktop.

        Deliberately the same session temp directory and the same stable
        per-node path as a webview node's Open in Browser, so a tab left
        open on a report card behaves like every other tab this app opens.
        """
        from .browser import open_html, remember, status_message
        node = self.graph.nodes.get(node_id)
        rendered = self._render_report_card(node_id, for_print=False)
        if node is None or rendered is None:
            return
        path = open_html(self._card_html(rendered, node), node.label,
                         token=node.id[:8])
        # Registered, so editing the card afterwards rewrites this file and
        # the open tab shows the new version on a refresh — without it the
        # page was written once and quietly went stale.
        remember(node_id, path)
        self.show_status(status_message(node, path), 8000)

    def _refresh_open_report_cards(self) -> None:
        """Keep an open browser tab level with the report cards on canvas.

        A report card is not like a webview node: it re-renders when its
        *text* changes, not only when it runs, so hooking this to
        node_succeeded alone would miss every edit made to the prose. It
        rides along with the canvas re-render instead, which already fires
        for both.
        """
        from .browser import is_open, rewrite
        for node_id, node in self.graph.nodes.items():
            if not is_open(node_id) or card_kind(node) != "report":
                continue
            rendered = self._render_report_card(node_id, for_print=False)
            if rendered is not None:
                rewrite(node_id, self._card_html(rendered, node))

    def _card_html(self, rendered, node) -> str:
        """The HTML behind a card's browser tab.

        Auto-refreshing, unlike the copy Save HTML writes: this one lives in
        a temp dir for as long as the app does, and the whole reason to have
        it open is to watch the report change. A file someone asked to keep
        must not reload itself in their face.
        """
        from flograph.core.page_setup import PageSetup
        from .report import report_html
        return report_html(rendered, node.label, setup=PageSetup(),
                           auto_refresh=True)

    def _edit_page_setup(self, page_id: str) -> None:
        """Page Setup… for a report page — from its toolbar, or from the tab
        menu when the page is locked and has no toolbar left."""
        page = self.graph.pages.get(page_id)
        if page is None or page.kind != "report":
            return
        from PySide6.QtWidgets import QDialog

        from .commands import SetPageSetupCommand
        from .report import PageSetupDialog
        dialog = PageSetupDialog(page.setup, page.title, self)

        # Live preview: the page behind shows the paper being described
        # while the dialog is open, and goes back to its own on any exit.
        # Waiting for OK to find out what a margin did is the slow way to
        # set a margin.
        widget = self._dashboard_pages.get(page_id)
        preview = getattr(widget, "preview_setup", None)
        if callable(preview):
            dialog.setup_changed.connect(preview)
        try:
            accepted = dialog.exec() == QDialog.Accepted
        finally:
            if callable(preview):
                dialog.setup_changed.disconnect(preview)
                preview(None)
        if not accepted:
            return
        setup = dialog.result_setup()
        if setup == page.setup:
            return   # nothing to record, and an undo step that did nothing
        self.undo_stack.push(SetPageSetupCommand(self.graph, page_id, setup))

    def _save_path_for(self, name: str, suffix: str, caption: str,
                       filter_text: str) -> Optional[str]:
        """Ask where to write an export of `name`.

        Next to the project and named after the thing being exported — the
        two things anyone exporting has just been looking at.
        """
        folder = (Path(self._project_path).parent if self._project_path
                  else Path.home())
        safe = "".join(c for c in name
                       if c.isalnum() or c in " -_").strip() or "report"
        path, _ = QFileDialog.getSaveFileName(
            self, caption, str(folder / f"{safe}{suffix}"), filter_text)
        if not path:
            return None
        return path if path.lower().endswith(suffix) else path + suffix

    def _write_html(self, rendered, path: str, title: str,
                    setup=None) -> None:
        """Shared by the page's Save HTML and the card's."""
        from .report import report_html
        try:
            Path(path).write_text(report_html(rendered, title, setup=setup),
                                  encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        if rendered.problems:
            QMessageBox.warning(
                self, "Saved with problems",
                f"Saved to {path}, but some embeds didn't resolve:\n\n• "
                + "\n• ".join(dict.fromkeys(rendered.problems)))
        else:
            self.show_status(f"Saved {path}", 6000)

    def _export_report_html(self, page_id: str) -> None:
        """The report as one self-contained HTML file.

        Not the same thing as Open in Browser, which writes to a session
        temp directory that is deleted on exit — this is the copy you keep,
        mail, or put somewhere a colleague can open it.
        """
        page = self.graph.pages.get(page_id)
        widget = self._dashboard_pages.get(page_id)
        if page is None or widget is None:
            return
        path = self._save_path_for(page.title, ".html", "Save report as HTML",
                                   "HTML documents (*.html)")
        if path is None:
            return
        self._write_html(widget.rendered(for_print=True), path, page.title,
                         setup=page.setup)

    def _export_report_pdf(self, page_id: str) -> None:
        page = self.graph.pages.get(page_id)
        widget = self._dashboard_pages.get(page_id)
        if page is None or widget is None:
            return
        path = self._save_path_for(page.title, ".pdf", "Export report as PDF",
                                   "PDF documents (*.pdf)")
        if path is None:
            return
        from .report import export_pdf
        rendered = widget.rendered(for_print=True)
        try:
            export_pdf(rendered.document, path, title=page.title,
                       setup=page.setup)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        # exported anyway — a report with a hole in it is still worth
        # having, but nobody should find out about the hole from the PDF
        if rendered.problems:
            QMessageBox.warning(
                self, "Exported with problems",
                f"Exported to {path}, but some embeds didn't resolve:\n\n• "
                + "\n• ".join(dict.fromkeys(rendered.problems)))
        else:
            self.show_status(f"Exported {path}", 6000)

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
        self.page_bar.set_page_view_mode(page.id, page.view_mode)
        self.page_bar.set_page_fit_to_window(page.id, page.fit_to_window)
        # the model is the source of truth for the mode, so undo/redo and a
        # project load drive the widget through here rather than separately
        widget = self._dashboard_pages.get(page.id)
        if widget is not None and hasattr(widget, "set_view_mode") \
                and widget.view_mode() != page.view_mode:
            widget.set_view_mode(page.view_mode)
            # locking a page locks its zoom, and the indicator is the one
            # place that says so
            self._refresh_zoom_indicator()
        if widget is not None and hasattr(widget, "set_fit_to_window") \
                and widget.fit_to_window() != page.fit_to_window:
            widget.set_fit_to_window(page.fit_to_window)
            self._refresh_zoom_indicator()   # scaling holds the zoom too

    def _set_page_view_mode(self, page_id: str, view_mode: bool) -> None:
        page = self.graph.pages.get(page_id)
        if page is None or page.view_mode == bool(view_mode):
            return
        from .commands import SetPageViewModeCommand
        self.undo_stack.push(
            SetPageViewModeCommand(self.graph, page_id, bool(view_mode)))

    def _set_page_fit_to_window(self, page_id: str, fit: bool) -> None:
        page = self.graph.pages.get(page_id)
        if page is None or page.fit_to_window == bool(fit):
            return
        from .commands import SetPageFitToWindowCommand
        self.undo_stack.push(
            SetPageFitToWindowCommand(self.graph, page_id, bool(fit)))

    def _set_visuals_visible(self, visible: bool) -> None:
        """Remember the toggle as the start state for pages made later. Pages
        already open keep theirs -- the panel is per page, this is the default
        it starts from."""
        self.visuals_visible = visible
        self.settings.setValue("dashboard/visuals_visible", visible)

    def _on_pages_reordered(self, order: list[str]) -> None:
        self.page_bar.set_page_order(order)

    def _on_current_page_changed(self, page_id) -> None:
        widget = self._dashboard_pages.get(page_id) if page_id else None
        self._canvas_stack.setCurrentWidget(
            widget if widget is not None else self.view)
        # dashboard/report pages have no node selection to configure, so free
        # up the screen by hiding the model-only docks
        is_model_page = page_id is None
        was_model_page = self._current_page_id is None
        if is_model_page:
            # only what was open before, so a round trip through a dashboard
            # page doesn't reopen a dock someone deliberately closed
            for dock in self._model_docks:
                dock.setVisible(dock in self._docks_open_on_model_page)
        else:
            # snapshot only when actually leaving the model page: between two
            # dashboard pages everything is already hidden, and "all hidden"
            # is also what Hide All Panels leaves behind, so dock visibility
            # can't tell the two apart on its own
            if was_model_page:
                self._docks_open_on_model_page = [
                    dock for dock in self._model_docks if not dock.isHidden()]
            for dock in self._model_docks:
                dock.setVisible(False)
        self._current_page_id = page_id
        for strip in self._edge_strips.values():
            strip.set_enabled(is_model_page)
        self._refresh_zoom_indicator()
        if self._project_path and not self._restoring_pages:
            self.settings.setValue(f"active_page/{self._project_path}",
                                   page_id or "")

    def _add_page(self, kind: str = "dashboard") -> None:
        from .report import STARTER_BODY
        page = Page(id=uuid.uuid4().hex, title=self._next_page_title(kind),
                    kind=kind,
                    # a blank report page is a blank text box with no clue
                    # that ![[...]] is a thing, so it starts with the syntax
                    body=STARTER_BODY if kind == "report" else "")
        self.undo_stack.push(AddPageCommand(self.graph, page))
        self.page_bar.select_page(page.id)

    def _next_page_title(self, kind: str = "dashboard") -> str:
        stem = "Report" if kind == "report" else "Page"
        titles = {p.title for p in self.graph.pages.values()}
        n = len(self.graph.pages) + 1
        while f"{stem} {n}" in titles:
            n += 1
        return f"{stem} {n}"

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

    def _add_tiles_to_page(self, page_id: str, node_ids: list) -> None:
        """The same, for a selection — one undo step for the lot. Each tile
        still goes through _add_tile_to_page, so they cascade off each other
        instead of landing in one pile."""
        if not node_ids:
            return
        if len(node_ids) == 1:
            self._add_tile_to_page(page_id, node_ids[0])
            return
        self.undo_stack.beginMacro(f"add {len(node_ids)} tiles")
        for node_id in node_ids:
            self._add_tile_to_page(page_id, node_id)
        self.undo_stack.endMacro()

    def _add_tile_on_new_page(self, node_ids) -> None:
        """A page made for whatever was selected. Takes one id or a list."""
        if isinstance(node_ids, str):
            node_ids = [node_ids]
        if not node_ids:
            return
        self.undo_stack.beginMacro("add to new page")
        page = Page(id=uuid.uuid4().hex, title=self._next_page_title())
        self.undo_stack.push(AddPageCommand(self.graph, page))
        for node_id in node_ids:
            self._add_tile_to_page(page.id, node_id)
        self.undo_stack.endMacro()

    def _on_node_failed(self, node_id: str, error) -> None:
        if node_id in self.graph.nodes:
            self.show_status(
                f"{self.graph.nodes[node_id].label}: {error.message}", 8000)
        self.editor_panel.on_node_failed(node_id, error)

    def _on_selection_changed(self) -> None:
        items = self.scene.selected_node_items()
        title_bar = getattr(self, "_title_bar", None)
        if title_bar is not None:
            title_bar.on_selection(len(items))
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
        """Plain double-click on a node's body. What it opens is the user's
        choice (Settings > Canvas), defaulting to Properties — which is what
        you want nine times out of ten, code being the rarer errand."""
        node = self.graph.nodes.get(node_id)
        if node is None:
            return
        action = self.double_click_action
        if action == "rename":
            self._rename_node(node_id)
            return
        # Notes and buttons are edited through their params whatever the
        # setting says: their "code" is boilerplate nobody wants, and their
        # text *is* a param.
        if action == "code" and card_kind(node) not in ("note", "button"):
            self.editor_panel.set_node(node_id)
            self._reveal_dock(self.editor_dock)
            self.editor_panel.editor.setFocus()
            return
        self.params_panel.set_node(node_id)
        self._reveal_dock(self.properties_dock)

    def open_node_window(self, node_id: str, tab: str = "properties") -> None:
        """Ctrl+double-click: this node's Properties and Code in a window of
        their own, so it can sit beside another node's. One window per node —
        see NodeWindow on why the same node twice is not offered."""
        if node_id not in self.graph.nodes:
            return
        window = self._node_windows.get(node_id)
        if window is None:
            from .node_window import NodeWindow
            window = NodeWindow(self.graph, self.undo_stack, self.registry,
                                node_id, cache=self.engine.cache, parent=self)
            window.save_as_user_node_requested.connect(self._save_as_user_node)
            window.closed.connect(
                lambda nid: self._node_windows.pop(nid, None))
            self._node_windows[node_id] = window
        window.show_tab(tab)
        window.show()
        window.raise_()
        window.activateWindow()

    def _reveal_dock(self, dock: QDockWidget) -> None:
        """Open `dock` and bring it to the front of its tab group. show()
        alone isn't enough for a dock the user closed: it also has to be put
        back in the set a dashboard round trip restores, or the next page
        switch would close it again."""
        dock.show()
        dock.raise_()
        if dock not in self._docks_open_on_model_page:
            self._docks_open_on_model_page.append(dock)

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

    def _run_all(self) -> None:
        if self._cache_still_writing():
            return
        self._flush_pending_edits()
        self.engine.run_all()

    def _run_selected(self) -> None:
        if self._cache_still_writing():
            return
        self._flush_pending_edits()
        targets = [item.node.id for item in self.scene.selected_node_items()]
        if targets:
            self.engine.run_targets(targets)

    def _reset_caches(self) -> None:
        self._flush_pending_edits()
        for node_id in self.graph.nodes:
            self.graph.mark_dirty(node_id)
        self.engine.cache.clear()
        # Reset is "discard everything", not "pretend nothing happened": the
        # cards were displaying values that just got thrown away, and every
        # one still on show is pinning it — a table's model holds its frame,
        # a webview's renderer keeps the last chart it rendered. Clear the
        # canvas cards, refresh dashboard tiles (they re-read the now-empty
        # cache and fall back to their placeholder) and re-read the
        # inspector, so the memory Reset Caches is meant to free is actually
        # released instead of waiting for the user to scroll away.
        for item in self.scene.node_items.values():
            item.clear_output()
        for page in self._dashboard_pages.values():
            scene = getattr(page, "scene", None)
            if scene is not None:
                for item in scene.tile_items.values():
                    item.refresh_content()
        self.inspector_panel.on_cache_cleared()
        self.show_status("Caches cleared — everything is stale", 4000)

    def _reset_caches_for_selection(self) -> None:
        """The same as Reset Caches, but only the selected nodes — for
        freeing the memory a few heavy steps are holding, or forcing just
        them to recompute, without throwing away the whole run."""
        ids = [item.node.id for item in self.scene.selected_node_items()]
        if not ids:
            return
        self._flush_pending_edits()
        for node_id in ids:
            self.graph.mark_dirty(node_id)
            self.engine.cache.evict(node_id)
            item = self.scene.node_items.get(node_id)
            if item is not None:
                item.clear_output()
        wanted = set(ids)
        for page in self._dashboard_pages.values():
            scene = getattr(page, "scene", None)
            if scene is not None:
                for tile in scene.tile_items.values():
                    if tile.tile.node_id in wanted:
                        tile.refresh_content()
        self.inspector_panel.on_cache_cleared()
        self.show_status(
            f"Cleared the cache for {len(ids)} "
            f"node{'s' if len(ids) > 1 else ''}", 3000)

    def _show_packages(self) -> None:
        from .packages_dialog import PackagesDialog
        dialog = getattr(self, "_packages_dialog", None)
        if dialog is None:
            dialog = PackagesDialog(self)
            self._packages_dialog = dialog
        dialog.show()
        dialog.raise_()

    def _create_desktop_shortcut(self) -> None:
        from .desktop_shortcut import ShortcutDialog
        ShortcutDialog(self, self._project_path).exec()

    def _show_ai_settings(self) -> None:
        from .ai_settings_dialog import AiSettingsDialog
        AiSettingsDialog(self).exec()

    def _show_secrets(self) -> None:
        from .env_dialog import EnvDialog
        EnvDialog(self.graph, self._project_path, self.undo_stack, self).exec()

    def _show_stats(self) -> None:
        if self._stats_window is None:
            self._stats_window = StatsWindow(self, self)
            self._stats_window.reveal_requested.connect(self._go_to_node)
        self._stats_window.show()
        self._stats_window.raise_()
        self._stats_window.activateWindow()

    def _show_settings(self) -> None:
        if self._settings_dialog is None:
            self._settings_dialog = SettingsDialog(self, self)
        self._settings_dialog.show()
        self._settings_dialog.raise_()
        self._settings_dialog.activateWindow()

    def _show_docs(self) -> None:
        """The handbook window — one instance, raised again on repeat opens."""
        if self._docs_window is None:
            self._docs_window = DocsWindow(self)
        self._docs_window.show()
        self._docs_window.raise_()
        self._docs_window.activateWindow()

    def _open_github(self) -> None:
        QDesktopServices.openUrl(QUrl("https://github.com/redthista/flograph"))

    # ------------------------------------------------------- action button

    def _on_button_fired(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "button":
            return
        action = node.params.get("action", "Run nodes")
        if action != "Show message" and self._cache_still_writing():
            return
        self._flush_pending_edits()
        if action == "Show message":
            self._show_button_message(node)
            return
        # "the whole flow" is Run All under another name, so a manual node
        # sits it out; a button that names a frame or a list of nodes is
        # somebody aiming, and fires them.
        asked = None
        if action == "Run whole flow":
            targets = list(self.graph.nodes)
            asked = ()
        elif action == "Run frame":
            targets = self._frame_node_ids(node.params.get("frame_title", ""))
        else:
            targets = self._named_node_ids(node.params.get("targets", ""))
        if not targets:
            self.show_status(f"{node.label}: nothing to run", 5000)
            return
        if node.params.get("clear_cache", True):
            for target_id in targets:
                self.graph.mark_dirty(target_id)
        self.engine.run_targets(targets, asked)

    def _on_slicer_changed(self, node_id: str) -> None:
        """A Slicer's ticks changed: re-run it and the visuals that follow.
        The SetParamCommand already dirtied the subgraph; request_run
        coalesces a burst of ticks into one run and holds the request until
        any run already in flight is done."""
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "slicer":
            return
        self.engine.request_run([node_id, *self.graph.downstream(node_id)])

    def _on_control_changed(self, node_id: str) -> None:
        """A slider moved, a date was picked, a box was typed into: re-run
        that control and everything it feeds, so the charts answer straight
        away. Same contract as a Slicer tick — the SetParamCommand already
        dirtied the subgraph, and request_run turns a drag's worth of values
        into one run of the final one."""
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "control":
            return
        self.engine.request_run([node_id, *self.graph.downstream(node_id)])

    def _on_dashboard_sheet_edited(self, node_id: str) -> None:
        """A cell changed in a Table tile: re-run it and everything it feeds,
        so the charts and KPIs on the page follow the number that was just
        typed. Same deal as a Slicer — the SetParamCommand already dirtied
        the subgraph, and request_run means typing across a row is one run
        of the finished row rather than a queue of obsolete ones."""
        node = self.graph.nodes.get(node_id)
        if node is None or card_kind(node) != "grid":
            return
        self.engine.request_run([node_id, *self.graph.downstream(node_id)])

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
        return self._nodes_of(frame)

    def _frame_node_ids_by_id(self, frame_id: str) -> list[str]:
        frame = self.graph.frames.get(frame_id)
        if frame is None:
            return []
        return self._nodes_of(frame)

    def _nodes_of(self, frame) -> list[str]:
        """The nodes a frame holds — the one answer everything asks for.

        The canvas's own containment rule, so "Run frame" reaches exactly what
        dragging the frame would carry and what folding it would take in. Two
        things a plain sweep of the rectangle gets wrong, both of which showed
        up as running the wrong set:

        A folded frame inside this one is a 60px box, and the nodes it stands
        for are still recorded wherever they were before it folded — which can
        be outside this frame entirely. Sweeping the rectangle misses them, so
        running a frame quietly skipped part of what was in it.

        And the sweep has to be blind to visibility, or it would miss those
        nodes altogether — but blind means it also picks up nodes belonging to
        some *other* folded frame that happens to have left them lying under
        this rectangle. Running a frame would then run somebody else's nodes.
        """
        item = self.scene.frame_items.get(frame.id)
        if item is None:        # mirrored before the canvas caught up
            return [nid for nid in frame.members if nid in self.graph.nodes]
        node_ids, _frames = self.scene.frame_contents(item)
        return [nid for nid in node_ids if nid in self.graph.nodes]

    def _on_frame_run_requested(self, frame_id: str) -> None:
        if self._cache_still_writing():
            return
        self._flush_pending_edits()
        targets = self._frame_node_ids_by_id(frame_id)
        if not targets:
            self.show_status("Frame is empty — nothing to run", 4000)
            return
        frame = self.graph.frames.get(frame_id)
        if frame is not None and not frame.active:
            # the plan would come back empty and the click would look
            # broken; a disabled frame is a deliberate state, so say so
            self.show_status(
                "Frame is disabled — right-click ▸ Enable frame to run it",
                5000)
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
        targets = [(p, resolve_dropped_path(p)) for p in paths]
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
            # naming the file without saying why left the only clue in a
            # message that had already timed out
            path, reason = errors[0]
            more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
            self.show_status(
                f"User node {path.name} was skipped{more}: {reason}", 10000)

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
        except user_nodes.UserNodeExistsError:
            if QMessageBox.question(
                    self, "Overwrite user node?",
                    f"A user node named {name!r} already exists in this "
                    f"group. Overwrite it?") != QMessageBox.Yes:
                return
            try:
                type_id = user_nodes.write_user_node(
                    nodes_dir, group, name, node.source, overwrite=True)
            except user_nodes.UserNodeError as exc:
                QMessageBox.warning(self, "Save failed", str(exc))
                return
        except user_nodes.UserNodeError as exc:
            # said out loud rather than written to disk: a node that can't be
            # loaded back would save happily and never reach the library
            QMessageBox.warning(self, "Save failed", str(exc))
            return
        self._reload_user_nodes()
        self.show_status(f"Saved user node {type_id}", 4000)

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
        from flograph.core import PortType, can_connect
        if port_item.spec.type == PortType.FLOW:
            # An order edge is drawn between two nodes that already exist —
            # "run after" needs something to run after. The palette would
            # offer the whole library, since every node has a flow port, and
            # every entry would mean the same thing. Say so rather than
            # letting the drag end in nothing at all.
            self.show_status(
                "Drop an order edge on another node's flow pin — it orders "
                "two nodes that already exist. Right-click one for what "
                "they do.", 6000)
            return
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

    def _show_add_node_menu(self, scene_pos: QPointF,
                            global_pos: QPoint) -> None:
        """Right-clicking empty canvas: the same searchable popup a dropped
        wire opens, rather than a menu of nested category submenus.

        The submenus held every node in the library behind a category you had
        to guess first, and they were the one place in the app where finding
        a node meant reading rather than typing. This is the popup people
        already like — with the two things on that menu that are not nodes
        kept as rows of their own, so nothing is lost by the swap.
        """
        extras = [("Frame", "frame")]
        if self._clipboard_payload() is not None:
            extras.append(("Paste", "paste"))
        elif self._clipboard_has_image():
            extras.append(("Paste Image", "paste"))
        self._palette_scene_pos = scene_pos
        self._pending_wire = None
        self._palette_popup.popup_at(global_pos, extras=tuple(extras))

    def _palette_extra_chosen(self, key: str) -> None:
        """A palette row that is not a node. Both land where the popup was
        opened, like the node rows beside them."""
        if key == "frame":
            self._add_frame_at(self._palette_scene_pos)
        elif key == "paste":
            self._paste(self._palette_scene_pos)

    def _show_order_edge_menu(self, conn_id: str, global_pos: QPoint) -> None:
        """Right-clicking an order edge: what it does to the two nodes it
        joins, a way to remove it, and an explanation of the whole idea.

        The explanation is the reason this menu exists. An order edge shows
        nothing and carries nothing — there is no output to open and no
        value to hover — so somebody meeting one on a flow they did not
        build has no way to find out what it is by poking at it.
        """
        conn = self.graph.connections.get(conn_id)
        if conn is None:
            return
        src = self.graph.nodes.get(conn.src_node)
        dst = self.graph.nodes.get(conn.dst_node)
        menu = QMenu(self)
        if src is not None and dst is not None:
            heading = menu.addAction(f"“{dst.label}” runs after “{src.label}”")
            heading.setEnabled(False)
            menu.addSeparator()
        delete_action = menu.addAction("Delete")
        menu.addSeparator()
        help_action = menu.addAction("What is this?")
        chosen = menu.exec(global_pos)
        if chosen is delete_action:
            self.scene.delete_items([], [conn_id], [])
        elif chosen is help_action:
            self._show_order_edge_help()

    def _show_order_edge_help(self) -> None:
        """One dialog, reused: it is non-modal, so opening a fresh one from
        the next wire would stack them up behind each other."""
        from .canvas.order_help import OrderEdgeHelpDialog, reveal_key_name
        dialog = getattr(self, "_order_help", None)
        if dialog is None:
            dialog = OrderEdgeHelpDialog(self)
            self._order_help = dialog
        # Re-read every time: the reveal key the text names is rebindable,
        # and this is the one place that says which key it is.
        dialog.set_reveal_key(reveal_key_name(self.reveal_ports_key))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _show_frame_menu(self, frame_id: str, global_pos: QPoint) -> None:
        if frame_id not in self.graph.frames:
            return
        item = self.scene.frame_items.get(frame_id)
        if item is not None and not item.isSelected():
            self.scene.clearSelection()
            item.setSelected(True)
        collapsed = self.graph.frames[frame_id].collapsed
        menu = QMenu(self)
        fold_action = menu.addAction("Expand frame" if collapsed
                                     else "Collapse frame")
        # Always offered, folded or not. The run glyph in the title bar is a
        # shortcut, not a substitute: it is gone while the frame is folded,
        # and on an expanded frame holding folded ones it is easy to miss, so
        # hiding the menu entry left people with no way in they could find.
        run_action = menu.addAction("Run frame")
        targets = self._frame_node_ids_by_id(frame_id)
        run_action.setEnabled(bool(targets))
        if not targets:
            run_action.setToolTip("This frame holds no nodes to run.")
        menu.addSeparator()
        # The same two run flags the node menu offers, carried by the frame
        # itself rather than stamped onto the nodes that happen to be inside
        # it: whatever is in the rectangle when a run is built is what the
        # flag reaches, so dragging a node in or out is all it takes.
        frame = self.graph.frames[frame_id]
        all_off = not frame.active
        disable_action = menu.addAction("Enable frame" if all_off
                                        else "Disable frame")
        disable_action.setToolTip(
            "Stop everything in this frame running, along with whatever "
            "they feed. For the corner of a big flow you are not working on."
            if not all_off else
            "Put everything in this frame back into the runs it was in.")
        frame_manual_action = menu.addAction("Run frame only when asked")
        frame_manual_action.setCheckable(True)
        frame_manual_action.setChecked(frame.manual)
        frame_manual_action.setToolTip(
            "Keep this frame out of Run All. Its nodes still run when you "
            "run the frame, and everything below them goes on using "
            "whatever they last produced.")
        menu.addSeparator()
        state = self._component_state(frame_id)
        update_action = None
        if state is not None and state["stale"]:
            update_action = menu.addAction("Update from component")
            # a modified instance has local work in it that an update would
            # throw away, so it is shown greyed rather than hidden — the
            # point is to say why it isn't on offer
            update_action.setEnabled(state["pristine"])
            if not state["pristine"]:
                update_action.setToolTip(
                    "This copy has been edited, so updating it would discard "
                    "those changes.")
        save_component = menu.addAction("Save as component…")
        copy_action = menu.addAction("Copy")
        change_color = menu.addAction("Change colour…")
        layer_actions = add_layer_menu(menu)
        menu.addSeparator()
        delete_action = menu.addAction("Delete")
        chosen = menu.exec(global_pos)
        if chosen in layer_actions:
            self.scene.restack_selection(layer_actions[chosen])
        elif chosen is fold_action:
            item = self.scene.frame_items.get(frame_id)
            if item is not None:
                item.toggle_collapsed()
        elif chosen is run_action:
            self._on_frame_run_requested(frame_id)
        elif chosen is disable_action:
            self.undo_stack.push(SetFrameFlagCommand(
                self.graph, frame_id, "active", all_off,
                "enable frame" if all_off else "disable frame"))
        elif chosen is frame_manual_action:
            self.undo_stack.push(SetFrameFlagCommand(
                self.graph, frame_id, "manual", not frame.manual,
                "run frame with the rest" if frame.manual
                else "run frame only when asked"))
        elif update_action is not None and chosen is update_action:
            self._update_component_instance(frame_id)
        elif chosen is save_component:
            self._save_frame_as_component(frame_id)
        elif chosen is copy_action:
            self._copy_selection()
        elif chosen is change_color:
            self._pick_frame_color(frame_id)
        elif chosen is delete_action:
            # through the scene, so a collapsed frame takes its hidden
            # contents with it and asks first — same as the Delete key
            self.scene.delete_items([], [], [frame_id])

    # ------------------------------------------------------- components

    def _save_frame_as_component(self, frame_id: str) -> None:
        """Write a frame and everything inside it to the user library."""
        from flograph.core import user_frames
        from flograph.paths import user_frames_dir
        frame = self.graph.frames.get(frame_id)
        if frame is None:
            return
        item = self.scene.frame_items.get(frame_id)
        if item is not None and not item.isSelected():
            self.scene.clearSelection()
            item.setSelected(True)
        payload = self._selection_payload()
        if payload is None:
            self.show_status("Nothing to save.", 4000)
            return
        name, ok = QInputDialog.getText(
            self, "Save as component", "Name:", QLineEdit.Normal, frame.title)
        if not (ok and name.strip()):
            return
        frames_dir = user_frames_dir()
        try:
            component_id = user_frames.write_user_frame(
                frames_dir, None, name.strip(), payload)
        except user_frames.UserFrameError:
            if QMessageBox.question(
                    self, "Replace component?",
                    f"A component named “{name.strip()}” already exists. "
                    "Replace it?") != QMessageBox.Yes:
                return
            component_id = user_frames.write_user_frame(
                frames_dir, None, name.strip(), payload, overwrite=True)
        # stamp the frame we saved *from* as an instance of what it became,
        # so it reads as pristine rather than as an unrelated copy
        self.undo_stack.push(SetFrameSourceCommand(
            self.graph, frame_id, component_id,
            user_frames.content_hash(payload)))
        self.library_tree.reload()
        self.show_status(
            f"Saved component “{name.strip()}”.", 4000)

    def _insert_component_at_view_center(self, component_id: str) -> None:
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self._insert_component_at(component_id, center)

    def _insert_component_at(self, component_id: str, scene_pos) -> None:
        """Drop a copy of a saved component onto the canvas.

        A copy, not a link: every id is regenerated, and editing it never
        writes back to the library file. The provenance stamp is what lets a
        copy nobody has touched still be recognised later.
        """
        from flograph.core import user_frames
        from flograph.paths import user_frames_dir
        path = user_frames.path_for(user_frames_dir(), component_id)
        try:
            data = user_frames.read(path)
        except user_frames.UserFrameError as exc:
            QMessageBox.warning(self, "Insert failed", str(exc))
            return
        payload = data.get("payload", {})
        fingerprint = user_frames.content_hash(payload)
        # land it under the cursor: shift by its own top-left corner
        corners = [f.get("rect", [0, 0])[:2] for f in payload.get("frames", [])]
        corners += [n.get("pos", [0, 0]) for n in payload.get("nodes", [])]
        origin_x = min((c[0] for c in corners), default=0.0)
        origin_y = min((c[1] for c in corners), default=0.0)
        for entry in payload.get("frames", []):
            entry["source"] = component_id
            entry["source_fingerprint"] = fingerprint
        self._insert_payload(
            payload,
            offset=(scene_pos.x() - origin_x, scene_pos.y() - origin_y),
            label="insert component")

    def _component_state(self, frame_id: str) -> Optional[dict]:
        """Where a frame stands relative to the component it came from.

        Returns None when it came from nowhere, or the library file it names
        has since gone. Otherwise `pristine` says whether anything inside has
        been edited since it was stamped, and `stale` whether the library
        file has moved on. Only a frame that is both pristine and stale can
        be updated: a modified one has local work in it that an update would
        silently throw away.
        """
        from flograph.core import user_frames
        from flograph.paths import user_frames_dir
        frame = self.graph.frames.get(frame_id)
        if frame is None or not frame.source:
            return None
        path = user_frames.path_for(user_frames_dir(), frame.source)
        try:
            data = user_frames.read(path)
        except user_frames.UserFrameError:
            return None
        library = user_frames.content_hash(data.get("payload", {}))
        current = self._frame_content_hash(frame_id)
        return {
            "component_id": frame.source,
            "payload": data.get("payload", {}),
            "library_fingerprint": library,
            "pristine": current == frame.source_fingerprint,
            "stale": library != frame.source_fingerprint,
        }

    def _frame_content_hash(self, frame_id: str) -> str:
        """Hash this frame as it stands now, via the clipboard payload —
        the same shape, and so the same hash, the library file was written
        from."""
        from flograph.core import user_frames
        keep = [i for i in self.scene.selectedItems()]
        self.scene.clearSelection()
        item = self.scene.frame_items.get(frame_id)
        if item is not None:
            item.setSelected(True)
        payload = self._selection_payload() or {}
        self.scene.clearSelection()
        for prev in keep:
            prev.setSelected(True)
        return user_frames.content_hash(payload)

    def _update_component_instance(self, frame_id: str) -> None:
        """Replace a frame's contents with the library's current version.

        The instance's nodes are thrown away and rebuilt from the file, so
        the wires reaching in from outside have to be re-made afterwards.
        They are matched by node *label* and port name: every id in a
        component is regenerated on insert, so ids cannot carry across, and a
        label is what the user actually named the thing.
        """
        from flograph.core import user_frames
        state = self._component_state(frame_id)
        frame = self.graph.frames.get(frame_id)
        if state is None or frame is None:
            return
        # transitive: a component can hold frames of its own now, and the old
        # instance has to go completely or the update leaves the previous
        # nesting standing alongside the new copy of it
        item = self.scene.frame_items.get(frame_id)
        if item is None:
            return
        member_list, nested_frames = self.scene.frame_contents(item)
        members = set(member_list)
        crossings = []
        for conn in self.graph.connections.values():
            src_in, dst_in = conn.src_node in members, conn.dst_node in members
            if src_in == dst_in:
                continue        # wholly inside, or wholly outside
            if src_in:
                crossings.append(("out", self.graph.nodes[conn.src_node].label,
                                  conn.src_port, conn.dst_node, conn.dst_port))
            else:
                crossings.append(("in", self.graph.nodes[conn.dst_node].label,
                                  conn.dst_port, conn.src_node, conn.src_port))
        origin = (frame.rect[0], frame.rect[1])
        was_collapsed = frame.collapsed
        payload = state["payload"]
        for entry in payload.get("frames", []):
            # only the component's own outer frame takes the instance's
            # provenance and folded state; a frame nested inside it keeps
            # whatever it was saved as. Absent "root" means a file written
            # before components could nest, where the single frame is the
            # root by definition.
            if not entry.get("root", True):
                continue
            entry["source"] = state["component_id"]
            entry["source_fingerprint"] = state["library_fingerprint"]
            entry["collapsed"] = was_collapsed
        corners = [f.get("rect", [0, 0])[:2] for f in payload.get("frames", [])]
        corners += [n.get("pos", [0, 0]) for n in payload.get("nodes", [])]
        off_x = origin[0] - min((c[0] for c in corners), default=0.0)
        off_y = origin[1] - min((c[1] for c in corners), default=0.0)

        self.undo_stack.beginMacro("update component")
        # The members go explicitly rather than relying on the collapsed-frame
        # rule: an expanded instance is being replaced just as thoroughly as a
        # folded one, and leaving its old nodes behind would double them up.
        # No confirm — nothing is being lost, it is rebuilt on the next line.
        self.scene.delete_items(sorted(members), [],
                                [frame_id] + list(nested_frames),
                                confirm=False)
        built = self._insert_payload(payload, offset=(off_x, off_y),
                                     label="insert component")
        if built is not None:
            by_label = {}
            for old_id, new_id in built["nodes"].items():
                node = self.graph.nodes.get(new_id)
                if node is not None:
                    by_label.setdefault(node.label, new_id)
            remade = 0
            for side, label, port, other_node, other_port in crossings:
                new_id = by_label.get(label)
                if new_id is None or other_node not in self.graph.nodes:
                    continue    # that node is gone from the new version
                try:
                    if side == "out":
                        self.undo_stack.push(ConnectCommand(
                            self.graph, new_id, port, other_node, other_port))
                    else:
                        self.undo_stack.push(ConnectCommand(
                            self.graph, other_node, other_port, new_id, port))
                    remade += 1
                except Exception:
                    continue    # the port no longer exists, or it would cycle
            dropped = len(crossings) - remade
            self.undo_stack.endMacro()
            self.show_status(
                f"Updated from “{state['component_id']}”."
                + (f" {dropped} connection{'s' if dropped != 1 else ''} "
                   "could not be remade." if dropped else ""), 6000)
            return
        self.undo_stack.endMacro()

    def _rename_user_frame(self, component_id: str) -> None:
        from flograph.core import user_frames
        from flograph.paths import user_frames_dir
        name, ok = QInputDialog.getText(
            self, "Rename component", "Name:", QLineEdit.Normal, "")
        if not (ok and name.strip()):
            return
        try:
            user_frames.rename_user_frame(user_frames_dir(), component_id,
                                          name.strip())
        except user_frames.UserFrameError as exc:
            QMessageBox.warning(self, "Rename failed", str(exc))
            return
        self.library_tree.reload()

    def _move_user_frame(self, component_id: str) -> None:
        from flograph.core import user_frames
        from flograph.paths import user_frames_dir
        group, ok = QInputDialog.getText(
            self, "Move component", "Group (blank for top level):",
            QLineEdit.Normal, "")
        if not ok:
            return
        try:
            user_frames.move_user_frame(
                user_frames_dir(), component_id,
                user_frames.slugify(group) if group.strip() else None)
        except user_frames.UserFrameError as exc:
            QMessageBox.warning(self, "Move failed", str(exc))
            return
        self.library_tree.reload()

    def _delete_user_frame(self, component_id: str) -> None:
        from flograph.core import user_frames
        from flograph.paths import user_frames_dir
        if QMessageBox.question(
                self, "Delete component",
                f"Delete the saved component “{component_id}”? "
                "Flows already using it are not affected."
        ) != QMessageBox.Yes:
            return
        try:
            user_frames.delete_user_frame(user_frames_dir(), component_id)
        except user_frames.UserFrameError as exc:
            QMessageBox.warning(self, "Delete failed", str(exc))
            return
        self.library_tree.reload()

    def _confirm_collapsed_delete(self, titles: list, count: int) -> bool:
        """Deleting a folded frame deletes what is inside it, which the
        canvas cannot show — so say how much before doing it."""
        names = ", ".join(f"“{t}”" for t in titles) or "this frame"
        box = QMessageBox(self)
        box.setWindowTitle("Delete frame")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"Delete {names} and the "
                    f"{count} node{'s' if count != 1 else ''} inside?")
        box.setInformativeText(
            "The frame is collapsed, so its contents go with it. "
            "Expand it first to delete the frame on its own.")
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        box.setDefaultButton(QMessageBox.Cancel)
        return box.exec() == QMessageBox.Yes

    def _pick_frame_color(self, frame_id: str) -> None:
        if frame_id not in self.graph.frames:
            return
        current = QColor(self.graph.frames[frame_id].color)
        color = QColorDialog.getColor(current, self, "Frame colour")
        if color.isValid():
            self.scene.push_frame_color(frame_id, color.name())

    def _edit_node_appearance(self, node_ids) -> None:
        """Everything about how these nodes look, in one place. Applies live,
        so there is nothing to confirm — see AppearanceDialog. Takes one id
        or a whole selection; the first is the one the dialog opens
        showing."""
        if isinstance(node_ids, str):
            node_ids = [node_ids]
        node_ids = [i for i in node_ids if i in self.graph.nodes]
        if not node_ids:
            return
        from .canvas.appearance_dialog import AppearanceDialog
        AppearanceDialog(self.scene, node_ids, self).exec()

    def _refresh_stale_pins(self) -> set:
        """Recompute which frozen nodes the graph has moved on from, and
        amber them on the canvas. Returns the set of node ids."""
        from flograph.engine import cache_persistence
        try:
            stale = set(cache_persistence.stale_frozen(self.graph))
        except Exception:
            stale = set()
        self.scene.refresh_stale_pins(stale)
        return stale

    def _apply_to_nodes(self, text: str, ids: list, factory) -> None:
        """Make the same change to every node in a selection, as one step on
        the undo stack.

        `factory` builds the command for one node, or returns None where the
        node is already the way it is being asked to be — a selection is
        usually half-and-half, and an undo step made of no-ops would still
        have to be pressed through on the way back.

        A single command is pushed on its own rather than wrapped: a macro of
        one reads as "3 nodes" in the undo list when it was never more than
        one, and it would also stop the mergeable commands merging.
        """
        commands = [c for c in (factory(i) for i in ids) if c is not None]
        if not commands:
            return
        if len(commands) == 1:
            self.undo_stack.push(commands[0])
            return
        self.undo_stack.beginMacro(f"{text} ({len(commands)})")
        for command in commands:
            self.undo_stack.push(command)
        self.undo_stack.endMacro()

    def _set_flag_on(self, ids: list, attr: str, wanted: bool,
                     command, text: str) -> None:
        """One of the run flags, set to `wanted` across a selection.

        Set, not toggled: the menu entry read "Freeze" because the node under
        the cursor was thawed, and the selection ending up half frozen and
        half not is the one outcome nobody clicking it meant.
        """
        self._apply_to_nodes(
            text, ids,
            lambda target: (
                None if getattr(self.graph.nodes[target], attr) == wanted
                else command(self.graph, target, wanted)))

    def _show_node_menu(self, node_id: str, global_pos: QPoint) -> None:
        if node_id not in self.graph.nodes:
            return
        item = self.scene.node_items.get(node_id)
        if item is not None and not item.isSelected():
            self.scene.clearSelection()
            item.setSelected(True)
        node = self.graph.nodes[node_id]
        # Right-clicking inside a selection means the selection. Everything
        # on this menu that *can* be said of several nodes is said of all of
        # them — the run, the flags, the appearance — and everything that can
        # only mean one (its code, its name, its own cached output) leaves the
        # menu rather than quietly acting on whichever one was clicked.
        ids = [i.node.id for i in self.scene.selected_node_items()]
        # the clicked node first: its state is what every toggle below reads
        # its label from, and the rest of the selection is then set to the
        # value that label promises rather than each being flipped separately
        ids = [node_id] + [i for i in ids if i != node_id]
        many = len(ids) > 1
        menu = QMenu(self)
        if many:
            menu.addSection(f"{len(ids)} nodes selected")
        run_to = menu.addAction("Run These Nodes" if many
                                else "Run To This Node")
        menu.addSeparator()
        edit_code = open_window = rename = None
        if not many:
            edit_code = menu.addAction("Edit Code")
            open_window = menu.addAction("Open in Window")
            rename = menu.addAction("Rename")
        # One entry for colour, mark, shape, port names, port collapsing and
        # the canvas preview. They were six, half of them conditional, so the
        # menu changed shape depending on what you right-clicked.
        appearance = menu.addAction("Appearance…")
        rerun = menu.addAction("Mark Dirty")
        menu.addSeparator()
        active_action = menu.addAction(
            "Deactivate" if node.active else "Activate")
        freeze_action = menu.addAction("Unfreeze" if node.frozen else "Freeze")
        manual_action = menu.addAction("Run only when asked")
        manual_action.setCheckable(True)
        manual_action.setChecked(node.manual)
        manual_action.setToolTip(
            "Keep this node out of Run All and out of the re-runs a slider "
            "or a typed cell sets off. It runs when you run it — from this "
            "menu, from Run Selected, or from an Action Button that names "
            "it — and everything below it goes on using whatever it last "
            "produced.")
        lock_action = menu.addAction("Unlock" if node.locked else "Lock")
        exclusive_action = menu.addAction("Run on its own")
        exclusive_action.setCheckable(True)
        exclusive_action.setChecked(is_exclusive(node))
        exclusive_action.setToolTip(
            "Give this node the whole process while it runs, instead of "
            "letting it share with other branches. For code that is not safe "
            "beside anything else.")
        menu.addSeparator()
        import_action = None
        if (not many and card_kind(node) == "grid"
                and self._table_import_source(node_id) is not None):
            import_action = menu.addAction("Import input into table")
        browser_action = None
        if not many and self._can_open_in_browser(node_id):
            browser_action = menu.addAction("Open in Browser")
        # A report *card* has no page, so it has no toolbar, so until these
        # two it had no way of reaching anyone not looking at the canvas.
        # Same two things a report page offers, from the one surface a card
        # has. Offered whether or not the node has run: unlike a webview
        # node, a report card's text is worth exporting on its own, and an
        # unresolved embed says so in the document rather than failing.
        report_export_action = report_browser_action = None
        report_html_action = None
        if not many and card_kind(node) == "report":
            report_export_action = menu.addAction("Export PDF…")
            report_html_action = menu.addAction("Save HTML…")
            report_browser_action = menu.addAction("Open in Browser")
        connected_actions: list = []
        from flograph.core.links import (is_from, is_goto, is_link_node,
                                         link_label, linked_from_nodes,
                                         linked_goto_node)
        if many:
            # a jump lands on one node, so it is not a thing a selection asks
            # for
            targets = []
            target_text = lambda t: t.label
        elif is_goto(node):
            # every From here shares one link name (the Goto's), so it's
            # useless for telling them apart — the node's own label is the
            # only thing that can distinguish them
            targets = linked_from_nodes(self.graph, node_id)
            target_text = lambda t: t.label
        elif is_from(node):
            # the reverse case has the opposite problem: a Goto's own label
            # is generic ("Goto") unless renamed, while its link name is
            # what's shown everywhere else this Goto appears (its card, the
            # From's picker) — so use that instead for a familiar name
            goto = linked_goto_node(self.graph, node_id)
            targets = [goto] if goto is not None else []
            target_text = link_label
        else:
            targets = []
            target_text = lambda t: t.label
        if len(targets) == 1:
            connected_actions.append(
                (menu.addAction(f"Go to {target_text(targets[0])}"),
                 targets[0].id))
        elif targets:
            # a Goto's glow highlights every From at once, which stops
            # helping once they're scattered across a big graph — this is
            # the "jump to one of them" the glow can't offer
            submenu = menu.addMenu("Go to Connected Node")
            for target in targets:
                connected_actions.append(
                    (submenu.addAction(target_text(target)), target.id))
        # Draw this link after all. A Goto speaks for every From reading it,
        # a From only for its own line — so the wording is singular on one
        # end and plural on the other, and the label says what clicking will
        # do rather than what is currently true.
        lines_action = None
        showing_lines = False
        if not many and is_link_node(node):
            from .canvas.link_line import SHOW_LINES_PARAM
            showing_lines = bool(node.params.get(SHOW_LINES_PARAM, False))
            noun = "Link Lines" if is_goto(node) else "Link Line"
            lines_action = menu.addAction(
                f"{'Hide' if showing_lines else 'Show'} {noun}")
        layer_actions = add_layer_menu(menu)
        # a cached output belongs to one node, so these name a port and stay
        # off a selection's menu
        view_actions = [] if many else self._add_view_actions(menu, node_id)
        page_actions: list = []
        new_page_action = None
        tile_ids = [i for i in ids if is_tile_able(self.graph.nodes[i])]
        if tile_ids:
            submenu = menu.addMenu("Add to Page")
            for page in self.graph.pages.values():
                if page.kind != "dashboard":
                    continue   # a report embeds by name, it holds no tiles
                page_actions.append((submenu.addAction(page.title), page.id))
            if page_actions:
                submenu.addSeparator()
            new_page_action = submenu.addAction("New Page…")
        menu.addSeparator()
        copy_action = menu.addAction("Copy")
        delete = menu.addAction("Delete")
        chosen = menu.exec(global_pos)
        if chosen is None:
            # Dismissed. Worth its own line rather than falling through the
            # chain below: the entries a selection does not get are None
            # too, and `chosen is edit_code` is true when both of them are.
            return
        if chosen in layer_actions:
            self.scene.restack_selection(layer_actions[chosen])
        elif chosen is run_to:
            self._flush_pending_edits()
            if many:
                # the selection, not a path to it: several nodes have no
                # single "up to here"
                self.engine.run_targets(ids)
            else:
                self.engine.run_to(node_id)
        elif chosen is edit_code:
            self.editor_panel.set_node(node_id)
            self._reveal_dock(self.editor_dock)
            self.editor_panel.editor.setFocus()
        elif chosen is open_window:
            self.open_node_window(node_id)
        elif chosen is rename:
            self._rename_node(node_id)
        elif chosen is appearance:
            self._edit_node_appearance(ids)
        elif chosen is rerun:
            for target in ids:
                self.graph.mark_dirty(target)
        elif chosen is active_action:
            self._set_flag_on(
                ids, "active", not node.active, SetActiveCommand,
                "deactivate nodes" if node.active else "activate nodes")
        elif chosen is freeze_action:
            self._set_flag_on(
                ids, "frozen", not node.frozen, SetFrozenCommand,
                "unfreeze nodes" if node.frozen else "freeze nodes")
        elif chosen is manual_action:
            self._set_flag_on(
                ids, "manual", not node.manual, SetManualCommand,
                "run nodes with the rest" if node.manual
                else "run nodes only when asked")
        elif chosen is lock_action:
            self._set_flag_on(
                ids, "locked", not node.locked, SetLockedCommand,
                "unlock nodes" if node.locked else "lock nodes")
        elif chosen is exclusive_action:
            wanted = not is_exclusive(node)
            # Back to None rather than to an explicit copy of the script's own
            # answer: a node pinned to what its code already says would keep
            # saying it after the code was edited to say the other thing.
            # Which means the *value* differs per node even though the
            # decision is one — hence a factory rather than _set_flag_on.
            def exclusive_for(target: str):
                target_node = self.graph.nodes[target]
                value = None if wanted == target_node.spec.exclusive else wanted
                if value == target_node.exclusive_override:
                    return None
                return SetExclusiveCommand(self.graph, target, value)
            self._apply_to_nodes(
                "run nodes on their own" if wanted
                else "let nodes run beside others", ids, exclusive_for)
        elif import_action is not None and chosen is import_action:
            self._import_input_into_table(node_id)
        elif browser_action is not None and chosen is browser_action:
            self._open_in_browser(node_id)
        elif (report_export_action is not None
                and chosen is report_export_action):
            self._export_report_card_pdf(node_id)
        elif report_html_action is not None and chosen is report_html_action:
            self._export_report_card_html(node_id)
        elif (report_browser_action is not None
                and chosen is report_browser_action):
            self._open_report_card_in_browser(node_id)
        elif lines_action is not None and chosen is lines_action:
            from .canvas.link_line import SHOW_LINES_PARAM
            # merge=False: one Ctrl+Z puts the line back, rather than the
            # toggle folding into whatever param edit came before it
            self.undo_stack.push(SetParamCommand(
                self.graph, node_id, SHOW_LINES_PARAM, not showing_lines,
                merge=False))
        elif chosen is copy_action:
            self._copy_selection()
        elif chosen is delete:
            self.scene.delete_selection()
        elif new_page_action is not None and chosen is new_page_action:
            self._add_tile_on_new_page(tile_ids)
        else:
            page_id = next((p for a, p in page_actions if a is chosen), None)
            if page_id is not None:
                self._add_tiles_to_page(page_id, tile_ids)
                return
            port_name = next((p for a, p in view_actions if a is chosen), None)
            if port_name is not None:
                from .inspector.popup_view import PopupView
                PopupView(self.graph, self.engine, node_id, port_name,
                          parent=self).show()
                return
            target_id = next((t for a, t in connected_actions if a is chosen),
                             None)
            if target_id is not None:
                self._go_to_node(target_id)

    def _find_node(self) -> None:
        """Edit > Find Node…, and Ctrl+F on the canvas.

        Searching is a model-canvas act, so a dashboard or report page steps
        aside for it: opening the bar over a hidden canvas would look like
        the menu item doing nothing.
        """
        if self.page_bar.current_page_id() is not None:
            self.page_bar.select_page(None)
        self.view.open_search()

    def _go_to_node(self, node_id: str) -> None:
        """Select a node and bring the model canvas to it — the Goto/From
        'Go to Connected Node' menu jumps here without the user having to
        hunt for it by eye across a big graph, and so does a hit in the
        Find Node bar or a clicked name in the statistics window.

        Jumping is a model-canvas act, so a dashboard or report page steps
        aside for it, on the same reasoning as _find_node: the menu item
        would otherwise appear to do nothing over a hidden canvas."""
        if self.page_bar.current_page_id() is not None:
            self.page_bar.select_page(None)
        self.view.go_to_node(node_id)

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
        # frames count as much as nodes here. A collapsed frame is a box in
        # the flow like any other, and grouping a row of them is the obvious
        # thing to want; reading only the nodes meant a selection of nothing
        # but frames looked empty, and Ctrl+G silently dropped a default
        # frame in the middle of the viewport instead of around them.
        selected = (self.scene.selected_node_items()
                    + self.scene.selected_frame_items())
        if selected:
            rect = None
            for item in selected:
                # what the item actually draws, so a collapsed frame
                # contributes its little square and not the region it would
                # grow back into
                bounds = item.sceneBoundingRect()
                rect = bounds if rect is None else rect.united(bounds)
            rect.adjust(-30, -50, 30, 30)
            frame = Frame(id=uuid.uuid4().hex,
                          rect=(rect.x(), rect.y(), rect.width(), rect.height()))
        else:
            center = self.view.mapToScene(self.view.viewport().rect().center())
            frame = Frame(id=uuid.uuid4().hex,
                          rect=(center.x() - 200, center.y() - 130, 400, 260))
        self._push_new_frame(frame)

    def _add_frame_at(self, scene_pos: QPointF) -> None:
        from flograph.core import Frame
        frame = Frame(id=uuid.uuid4().hex,
                      rect=(scene_pos.x(), scene_pos.y(), 400, 260))
        self._push_new_frame(frame)

    def _push_new_frame(self, frame) -> None:
        """Add a frame, and drop it behind anything it has been drawn around.

        A new frame arrives on top of the others, which is right for one you
        have drawn on empty canvas and wrong for one you have drawn *around*
        existing frames: it covers them, and since a frame takes the click
        anywhere in its body, they can no longer be selected at all without
        sending the new one to the back by hand.

        Not simply "frames go to the back on arrival" — that breaks the
        mirror case just as badly. A small frame drawn *inside* a big one
        would arrive behind it and be the unreachable one instead. What
        settles it is containment, not arrival order: a frame that encloses
        another belongs behind it, so this drops the new frame just behind
        the backmost frame it encloses, and leaves it on top when it encloses
        nothing.
        """
        from .commands import AddFrameCommand, RestackCommand
        rect = QRectF(*frame.rect)
        order = self.graph.stacking_order("frame")
        inside = [fid for fid in order
                  if rect.contains(QRectF(*self.graph.frames[fid].rect))]
        if not inside:
            self.undo_stack.push(AddFrameCommand(self.graph, frame))
            return
        new_order = order + [frame.id]
        new_order.remove(frame.id)
        new_order.insert(min(order.index(fid) for fid in inside), frame.id)
        self.undo_stack.beginMacro("add frame")
        self.undo_stack.push(AddFrameCommand(self.graph, frame))
        self.undo_stack.push(RestackCommand(
            self.graph, "frame", new_order, text="add frame"))
        self.undo_stack.endMacro()

    def _align(self, mode: str) -> None:
        # frames line up alongside nodes: a collapsed one is a box in the
        # flow like any other, and leaving it behind while the nodes either
        # side of it shuffled into line was the same blind spot that put a
        # Ctrl+G frame in the wrong place (see _add_frame)
        items = (self.scene.selected_node_items()
                 + self.scene.selected_frame_items())
        if len(items) < 2:
            return
        placements: dict = {}
        if mode in ("left", "top"):
            anchor = min(i.pos().x() if mode == "left" else i.pos().y()
                         for i in items)
            for item in items:
                old = (item.pos().x(), item.pos().y())
                placements[item] = ((anchor, old[1]) if mode == "left"
                                    else (old[0], anchor))
        else:
            horizontal = mode == "dist_h"
            key = (lambda i: i.pos().x()) if horizontal else (lambda i: i.pos().y())
            ordered = sorted(items, key=key)
            first, last = key(ordered[0]), key(ordered[-1])
            step = (last - first) / (len(ordered) - 1)
            for index, item in enumerate(ordered):
                old = (item.pos().x(), item.pos().y())
                coord = first + step * index
                placements[item] = ((coord, old[1]) if horizontal
                                    else (old[0], coord))
        moves, frame_rects = self.scene.placement_plan(placements)
        if not moves and not frame_rects:
            return
        self.undo_stack.beginMacro(f"align {mode}")
        self.scene.apply_nudge(moves, frame_rects)
        self.undo_stack.endMacro()

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

    def _live_edge_strips(self) -> list:
        """Strips with something on their edge. One whose docks have all been
        dragged elsewhere has nothing to collapse and would otherwise make
        'are they all hidden?' unanswerable."""
        return [strip for strip in self._edge_strips.values() if strip.docks()]

    def all_panels_hidden(self) -> bool:
        strips = self._live_edge_strips()
        return bool(strips) and all(strip.is_collapsed() for strip in strips)

    def toggle_all_panels(self) -> None:
        """Ctrl+Shift+H: clear every panel off the canvas at once, and put
        them back the same way. Each edge remembers its own pre-collapse
        set, so a panel closed by its own X before this stays closed."""
        # a dashboard page has already hidden the model docks on purpose;
        # expanding here would drag them onto a page they don't belong to.
        # _current_page_id, not the page bar: this asks which page the docks
        # are currently arranged for, which is what that field tracks.
        if self._current_page_id is not None:
            return
        strips = self._live_edge_strips()
        if not strips:
            return
        hiding = not self.all_panels_hidden()
        for strip in strips:
            strip.collapse() if hiding else strip.expand()
        self._sync_toggle_panels_action()
        self.show_status(
            "Panels hidden — Ctrl+Shift+H to bring them back." if hiding
            else "Panels restored.", 4000)

    def _sync_toggle_panels_action(self) -> None:
        self.action_toggle_panels.setText(
            "Show All Panels" if self.all_panels_hidden()
            else "Hide All Panels")

    def reset_window_layout(self) -> None:
        """Put the docks back where a fresh install has them. Geometry is
        left alone deliberately — someone whose panels have gone missing
        wants them back, not their window resized out from under them."""
        self.settings.remove("dock_state")
        self._dock_host.restoreState(self._default_dock_state)
        # restoreState() carries the default (all-open) visibility, but say it
        # outright: this is the "my panels have gone missing" button, so every
        # dock comes back whatever state it was left in
        for dock in self._model_docks:
            dock.show()
        self._docks_open_on_model_page = list(self._model_docks)
        self.properties_dock.raise_()
        self.show_status("Window layout reset.", 4000)

    def reset_settings(self) -> None:
        """Wipe every stored preference and re-apply the defaults live, so
        the app looks like a fresh install without needing a restart. Recent
        files and per-project state go too — this is the "start over" button,
        not a per-page reset."""
        self.settings.clear()
        # clear() drops the stored rebinds but leaves them applied to the
        # live actions, so the keys would keep working until a restart
        self.shortcuts.reset_all()
        self.set_page_bar_position("top")
        self.set_stats_bar_enabled(True)
        self.set_stats_sampling_enabled(True)
        self.set_stats_history_limit(HISTORY_LIMIT)
        self.set_engine_max_workers(0)
        self.set_lod_enabled(True)
        self.set_lod_threshold(DEFAULT_LOD_THRESHOLD)
        self.set_snap_enabled(True)
        self.set_grid_step(grid.DEFAULT_STEP)
        self.set_grid_visible(True)
        self.set_minimap_enabled(True)
        self.set_port_labels_enabled(False)
        self.set_flow_pins_enabled(False)
        self.set_reveal_ports_key(canvas_view.DEFAULT_REVEAL_PORTS_KEY)
        self.set_double_click_action("properties")
        self.set_compact_nodes(True)
        self.set_tints(theme.DEFAULT_TINT_SOFT, theme.DEFAULT_TINT_STRONG)
        self.action_gpu_viewport.setChecked(False)
        from .spreadsheet import set_autosize_default, set_date_formats_setting
        set_autosize_default(True)
        set_date_formats_setting("")
        self.reset_window_layout()
        self._rebuild_recent_menu()
        if self._settings_dialog is not None:
            # deferred: this usually runs from a button inside that dialog,
            # and rewriting its widgets mid-click is asking for trouble
            QTimer.singleShot(
                0, lambda: self._settings_dialog.refresh_from(self))
        self.show_status("Settings reset to defaults.", 4000)

    # ----------------------------------------------------------- copy/paste

    def _selection_payload(self) -> Optional[dict]:
        node_ids = {item.node.id for item in self.scene.selected_node_items()}
        # dicts as ordered sets: the frames come out in a stable order, and a
        # frame reachable two ways is only written once
        frame_ids: dict = {}
        roots = {item.frame.id for item in self.scene.selected_frame_items()}
        for item in self.scene.selected_frame_items():
            frame_ids[item.frame.id] = None
            # a frame carries what is inside it, same as a drag — and that
            # includes any frame inside it, and whatever *those* hold. Copying
            # only the frames you had selected quietly flattened the nesting:
            # you got the nodes and the outer frame, and the inner frame was
            # simply not in the clipboard at all.
            nodes_in, frames_in = self.scene.frame_contents(item)
            node_ids.update(nodes_in)
            for nested_id in frames_in:
                frame_ids[nested_id] = None
        nodes = [self.graph.nodes[nid] for nid in node_ids
                 if nid in self.graph.nodes]
        frames = [self.graph.frames[fid] for fid in frame_ids
                  if fid in self.graph.frames]
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
                # the id is what lets the membership below be re-pointed at
                # the copies on paste; without it a folded frame arrives
                # standing in for nothing
                "id": f.id,
                # the one you actually selected, as against a frame that came
                # along because it was inside it. A component update stamps
                # the instance's folded state onto the root and leaves the
                # nesting to keep its own.
                "root": f.id in roots,
                "title": f.title, "rect": list(f.rect), "color": f.color,
                "collapsed": f.collapsed,
                # without this a pasted folded frame can never open back to
                # the right size — it only knows the 60px box
                "expanded_size": (list(f.expanded_size)
                                  if f.expanded_size else None),
                "members": [m for m in f.members if m in ids],
                "member_frames": [m for m in f.member_frames
                                  if m in frame_ids],
                # `nudged` is deliberately not copied: it records what this
                # frame shoved aside *on this canvas*, which the copy has
                # displaced nothing of.
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

    def _clipboard_has_image(self) -> bool:
        # mimeData() is documented as possibly null and on some platforms
        # really is — a session with no clipboard owner, a headless run. The
        # canvas asks this on every right-click now, so a null here would be
        # a crash where a menu should be. image_paste guards the same way.
        mime = QApplication.clipboard().mimeData()
        return mime is not None and mime.hasImage()

    def _paste_clipboard_image(self, scene_pos: Optional[QPointF] = None
                               ) -> bool:
        """Clipboard picture -> an Image node on the canvas.

        This is also the whole of "screen grab": every OS screenshot key
        already puts its result on the clipboard, so there is nothing for
        flograph to capture itself.
        """
        from .image_paste import save_clipboard_image
        try:
            path = save_clipboard_image(QApplication.clipboard().mimeData())
        except OSError as exc:
            self.show_status(f"Could not save the image: {exc}", 8000)
            return False
        if path is None:
            return False
        if scene_pos is None:
            scene_pos = self.view.mapToScene(
                self.view.viewport().rect().center())
        node = self.registry.instantiate(
            IMAGE_TYPE, pos=(scene_pos.x(), scene_pos.y()))
        self.undo_stack.beginMacro("paste image")
        self.undo_stack.push(AddNodeCommand(self.graph, node))
        self.undo_stack.push(
            SetParamCommand(self.graph, node.id, "path", path))
        self.undo_stack.endMacro()
        self.scene.clearSelection()
        item = self.scene.node_items.get(node.id)
        if item is not None:
            item.setSelected(True)
        self.show_status("Pasted image from the clipboard", 4000)
        return True

    def _paste(self, scene_pos: Optional[QPointF] = None) -> None:
        payload = self._clipboard_payload()
        if payload is not None:
            self._insert_payload(payload)
            return
        # Only once nothing of ours is on the clipboard, so copying nodes and
        # then pasting never turns into an unexpected picture.
        self._paste_clipboard_image(scene_pos)

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

    def _insert_payload(self, payload: dict,
                        offset: Optional[tuple] = None,
                        label: str = "paste") -> None:
        """Stamp a clipboard-shaped fragment into the graph with fresh ids.

        `offset` shifts everything it contains; the default nudge is what
        makes a paste land clear of what it was copied from. A component
        dropped from the library passes its own, so it arrives under the
        cursor instead.
        """
        from flograph.core import Frame
        from .commands import AddFrameCommand
        dx, dy = offset if offset is not None else (PASTE_OFFSET, PASTE_OFFSET)
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
                pos=(entry["pos"][0] + dx, entry["pos"][1] + dy),
                label_override=entry.get("label"),
                color=entry.get("color"),
                description=entry.get("description", ""),
            ))
        # frames get an id map of their own, for the same reason the nodes do:
        # a folded frame names the nodes and frames it stands in for, and
        # those names have to be re-pointed at the copies. Assigned up front
        # so a frame can name a nested one written after it.
        frame_entries = payload.get("frames", [])
        frame_map: dict = {}
        for index, entry in enumerate(frame_entries):
            # older clipboard fragments carry no frame id, and there is
            # nothing to re-point in them — key by position so they still paste
            frame_map[entry.get("id") or f"\0frame{index}"] = uuid.uuid4().hex
        new_frames: list[Frame] = []
        for index, entry in enumerate(frame_entries):
            rect = entry.get("rect", [0.0, 0.0, 300.0, 200.0])
            size = entry.get("expanded_size")
            new_frames.append(Frame(
                id=frame_map[entry.get("id") or f"\0frame{index}"],
                title=entry.get("title", "Frame"),
                rect=(rect[0] + dx, rect[1] + dy, rect[2], rect[3]),
                color=entry.get("color") or "#33415c",
                collapsed=bool(entry.get("collapsed", False)),
                expanded_size=tuple(size) if size else None,
                # anything the fragment did not bring with it is dropped
                # rather than carried as a dangling name
                members=tuple(id_map[m] for m in entry.get("members", ())
                              if m in id_map),
                member_frames=tuple(frame_map[m]
                                    for m in entry.get("member_frames", ())
                                    if m in frame_map),
                source=entry.get("source", ""),
                source_fingerprint=entry.get("source_fingerprint", ""),
            ))
        if not new_nodes and not new_frames:
            return None
        self.undo_stack.beginMacro(label)
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
        # what it built, so a component update can re-attach the wires that
        # used to reach the nodes this just replaced
        return {"nodes": id_map, "frames": [f.id for f in new_frames]}

    # ------------------------------------------------------ project files

    def _on_clean_changed(self, clean: bool) -> None:
        self._update_title()

    def _update_title(self) -> None:
        name = Path(self._project_path).name if self._project_path else "untitled"
        self.setWindowTitle(f"{name}[*] — flograph")
        self.setWindowModified(not self.undo_stack.isClean())
        title_bar = getattr(self, "_title_bar", None)
        if title_bar is not None:
            title_bar.refresh_title()

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
            # "Save them first?" may just have started a background cache
            # write; see it out or the side-car it was writing is lost.
            self._wait_for_cache_save()
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
        self.show_status(
            "Still restoring cached results from the previous project — try again in a moment",
            4000)
        return True

    def _new_project(self) -> None:
        if self._cache_still_loading():
            return
        if not self._confirm_discard():
            return
        graph = Graph()
        # An unsaved project has no folder to hold a .env, so it reads the
        # per-user one. `serialization.load` does the same for a project that
        # does have a folder, relative to it.
        dotenv.bind(graph, dotenv.default_path())
        self._replace_graph(graph)
        self._project_path = None
        self.engine.history.clear()      # a new project starts unmeasured
        self.resource_monitor.set_disk_watch_path(None)
        self._update_title()

    def _open_dialog(self) -> None:
        if self._cache_still_loading():
            return
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "",
            "flograph projects (*.flograph *.flowf);;"
            "flograph workflow (*.flowf);;All files (*)")
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
        self.engine.history.clear()      # examples open unmeasured
        self.resource_monitor.set_disk_watch_path(None)
        self._update_title()
        self.show_status(
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
        self.resource_monitor.set_disk_watch_path(path)
        self._push_recent(path)
        self._update_title()
        saved_page = self.settings.value(f"active_page/{path}", "")
        if saved_page and saved_page in self.graph.pages:
            self.page_bar.select_page(saved_page)
        broken = sum(1 for n in loaded.nodes.values() if n.spec.broken)
        if broken:
            self.show_status(
                f"Opened {path} — {broken} node(s) couldn't be resolved and "
                f"were loaded as broken placeholders", 6000)
        elif path.endswith(".flowf"):
            self.show_status(
                f"Opened workflow {path} — Save writes a .flograph project; "
                f"Export updates this file", 6000)
        else:
            self.show_status(f"Opened {path}", 4000)
        self._restore_cache(path, quiet=bool(broken))
        # The statistics window opens on this project's saved runs rather
        # than whatever the previous session had in memory.
        self.engine.history.clear()
        for record in cache_persistence.load_run_history(path):
            self.engine.history.add(record)
        return True

    def _restore_cache(self, path: str, quiet: bool = False) -> None:
        """Register the just-opened project's cached results without reading
        any of them.

        This used to unpickle every valid blob up front, on a pool thread
        behind a progress dialog. That is a lot of work to do before the user
        has asked for anything, and on a project whose side-car holds a few
        large frames it is gigabytes: a 14-node project with 2M-row tables
        cost about 4 GB of resident memory just to open, and duplicating such
        a flow was enough to exhaust the machine before Run was ever pressed.

        Now opening reads one manifest. Each node is recorded as cached but
        not loaded, which is all it takes for it to count as clean, and its
        value is fetched when something actually wants it — the engine warms
        a run's inputs on a pool thread (ExecutionEngine._warm_plan), the
        inspector loads a single node's value when asked to show it, and
        everything a *card* displays is queued here, so the flow opens
        looking the way it was left rather than as placeholders waiting for
        a re-run. Only card-visible values load — not the bulk intermediates,
        which is what keeps this from being the 4 GB open it used to be.
        """
        self._finish_warm_watch()       # drop any watch from a prior open
        registered = cache_persistence.register_cache(
            self.graph, self.engine.cache, path)
        if not registered:
            return
        for node_id in registered:
            self.graph.mark_clean(node_id)
            self.graph.set_status(node_id, NodeStatus.DONE)
            self.engine.node_succeeded.emit(node_id)
        # The emit storm above ran every card handler against an empty
        # (spilled) entry — that is what placeholders are. Queue what those
        # cards actually display: their own values, plus whatever upstream
        # feeds a slicer's or control's options.
        warm_ids = self._display_warm_ids(registered)
        done = ("" if quiet else
                f"Opened {path} — {len(registered)} node(s) restored "
                f"from cache")
        if warm_ids and self.engine.warm_entries(warm_ids):
            self._begin_warm_watch(warm_ids, done)
        elif done:
            self.show_status(done, 4000)

    def _begin_warm_watch(self, warm_ids: list[str], done_message: str) -> None:
        """Put a 'Restoring cached results…' busy-bar on the status line
        until the card warm a just-opened project kicked off has landed.

        Opening is instant — one manifest, nothing inflated — but a card
        fed by a large cached frame (a 5M-row table behind a Slicer) can't
        draw until that frame is decompressed and unpickled on the pool
        thread, seconds of work with nothing to show for it. Left silent it
        reads as a hang.

        The watch holds the *blob owners* the warm actually reads off disk
        — a passthrough card aliases its source's blob, so watching the
        card id would never clear."""
        cache = self.engine.cache
        roots: set[str] = set()
        for nid in warm_ids:
            entry = cache.get(nid)
            if entry is None or entry.resident:
                continue
            root = cache.blob_source(nid) or nid
            root_entry = cache.get(root)
            if root_entry is not None and not root_entry.resident:
                roots.add(root)
        if not roots:
            if done_message:
                self.show_status(done_message, 4000)
            return
        self._warm_watch = roots
        self._warm_watch_active = True
        self._warm_done_message = done_message
        self._restore_bar.show()
        self.show_status("Restoring cached results…")
        self._warm_watch_timer.start(90_000)

    def _tick_warm_watch(self) -> None:
        """Drop blobs that have arrived (or failed to); finish when the
        last one is in. Cheap — a set rebuild — and driven by the same
        became-resident / load-failed events the cards already listen on."""
        if not self._warm_watch_active:
            return
        cache = self.engine.cache
        self._warm_watch = {
            r for r in self._warm_watch
            if (e := cache.get(r)) is not None and not e.resident}
        if not self._warm_watch:
            self._finish_warm_watch(completed=True)

    def _finish_warm_watch(self, completed: bool = False) -> None:
        """Take the busy-bar down. `completed` — the watch drained on its
        own (or timed out), so the deferred 'Opened…' line is due; a forced
        reset (a new project is loading) just clears it."""
        self._warm_watch_timer.stop()
        was_active = self._warm_watch_active
        self._warm_watch_active = False
        self._warm_watch = set()
        self._restore_bar.hide()
        message, self._warm_done_message = self._warm_done_message, ""
        if not (completed and was_active) or self.engine.active:
            return          # a run owns the status line; don't talk over it
        if message:
            self.show_status(message, 4000)
        elif self.status_message() == "Restoring cached results…":
            self.show_status("")

    #: The canvas kinds whose cards render cached data rather than params.
    _CARD_DATA_KINDS = ("figure", "webview", "table_viewer", "kpi",
                        "slicer", "control")

    def _display_warm_ids(self, registered: list[str]) -> list[str]:
        """Which spilled entries the visible cards are waiting on.

        A figure/webview/table/kpi card shows its own output; a slicer or
        control shows what its wired inputs' entries say (options, bounds),
        so those nodes' sources come along too. Everything else — bulk
        intermediates nobody is looking at — stays on disk until asked."""
        ids: list[str] = []
        sources: set[str] = set()
        for node_id in registered:
            node = self.graph.nodes.get(node_id)
            if node is None:
                continue
            kind = card_kind(node)
            if kind not in self._CARD_DATA_KINDS:
                continue
            ids.append(node_id)
            if kind in ("slicer", "control"):
                for port in node.spec.inputs:
                    conn = self.graph.input_connection(node_id, port.name)
                    if conn is not None:
                        sources.add(conn.src_node)
                sources.update(self.graph.var_sources(node_id))
        return ids + sorted(sources.difference(ids))

    def _replace_graph(self, loaded: Graph) -> None:
        # A wire/node/frame drag or a middle-drag pan in progress when Open
        # fires never gets its mouse release — the items go away underneath
        # it. Left alone that pins the edge-scroll on and sticks the grab
        # cursor, so the next plain pan of the new flow scrolls at the border
        # and won't let go of the hand. Clear both before the graph churns.
        self.scene.cancel_active_drags()
        self.view.cancel_pan()
        # a warm from the outgoing project is about to be irrelevant
        self._finish_warm_watch()
        # pages opened in a browser belong to the project being closed; the
        # incoming one must not inherit them and start rewriting its files
        from .browser import forget_all
        forget_all()
        # The engine cache is keyed by node id and is *not* emptied by
        # removing nodes — a New/Open would otherwise inherit every frame the
        # previous project had resident. Drop it up front; the incoming
        # project's own entries are registered right after (open_path ->
        # _restore_cache).
        self.engine.cache.clear()
        self._restoring_pages = True
        # Folding is re-derived from scratch on every graph event, which is
        # the right trade everywhere except here: a 500-node load would run
        # it 500 times. Suspend it and fold once, at the end.
        self.scene._suspend_collapse_refresh = True
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
        self.scene._suspend_collapse_refresh = False
        self.scene._refresh_collapsed_frames()
        self.undo_stack.clear()
        self.undo_stack.setClean()
        if loaded.nodes:
            self.view.frame_content()

    def _save(self, *, carry_from: "Optional[str]" = None) -> bool:
        if self._project_path is None:
            return self._save_as()
        # A .flowf that was opened is an imported workflow, not a project
        # file — Save makes a real .flograph for it (Export updates the
        # .flowf). Anything not ending .flograph goes the same way.
        if not self._project_path.endswith(".flograph"):
            return self._save_as()
        if self._cache_save_signals is not None:
            self.show_status(
                "Still writing the last save — try again in a moment", 4000)
            return False

        # One atomic .flograph bundle (graph + cached results), written off
        # the GUI thread.
        self._push_recent(self._project_path)
        self._start_project_save(carry_from or self._project_path)
        return True

    def _export_workflow(self) -> bool:
        """Write the graph alone to a `.flowf` file — no cached results,
        plain JSON, made to be committed to version control and shared.

        Not the project file: `_project_path` and the unsaved-changes state
        are untouched, so a Save still writes the `.flograph` bundle. Re-run
        Export to update the `.flowf`."""
        stem = (Path(self._project_path).stem if self._project_path
                else "workflow")
        start = str((Path(self._project_path).parent if self._project_path
                     else Path.cwd()) / f"{stem}.flowf")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export workflow", start, "flograph workflow (*.flowf)")
        if not path:
            return False
        if not path.endswith(".flowf"):
            path += ".flowf"
        try:
            serialization.save(self.graph, path)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", save_failure_text(
                f'"{path}"', exc))
            return False
        self.show_status(f"Exported workflow to {path}", 4000)
        return True

    def _start_project_save(self, carry_from: str) -> None:
        """Write the .flograph bundle off the GUI thread, with progress on
        the line.

        The snapshot — graph dict, blob plan, run history — is taken here,
        cheaply, so the worker touches only the filesystem (see
        cache_persistence.plan_project_save). While it runs, a second Save,
        Save As and starting a run wait for it. Mid-run the live cache is
        not walked: every blob is copied from the previous file instead,
        exactly as the old JSON-only mid-run save persisted nothing new.
        `carry_from` is the file unchanged blobs are copied from — the same
        path on a plain Save, the old path on Save As."""
        path = self._project_path
        carry_all = self.engine.active
        plan = cache_persistence.plan_project_save(
            self.graph, self.engine.cache, self.engine.history,
            carry_all=carry_all)
        self._save_clean_index = self.undo_stack.index()
        self._folded_sidecar = cache_persistence.has_sidecar(path)

        if not plan.blobs and not carry_all:
            # No blobs to pickle — the archive is just project.json and a
            # short manifest. Write it here and now, so a cache-free save
            # stays instant and starts no background thread.
            try:
                cache_persistence.write_project(
                    path, plan, prev_path=carry_from,
                    compress=self.cache_compression_enabled)
            except OSError as exc:
                QMessageBox.critical(self, "Save failed", save_failure_text(
                    f'"{path}"', exc))
                return
            if self.undo_stack.index() == self._save_clean_index:
                self.undo_stack.setClean()
            self._announce_saved()
            return

        signals = CacheSaveSignals(parent=self)
        signals.progressed.connect(self._on_cache_save_progress)
        signals.finished.connect(self._on_cache_save_finished)
        self._cache_save_signals = signals
        self._save_bar.setRange(0, max(1, len(plan.blobs)))
        self._save_bar.setValue(0)
        self._save_bar.show()
        self.show_status(f"Saving {Path(path).name}…")
        QThreadPool.globalInstance().start(
            CacheSaveRunnable(path, plan, signals,
                              compress=self.cache_compression_enabled,
                              prev_path=carry_from, carry_all=carry_all))

    def _on_cache_save_progress(self, done: int, total: int) -> None:
        self._save_bar.setRange(0, max(1, total))
        self._save_bar.setValue(done)
        name = Path(self._project_path).name if self._project_path else ""
        self.show_status(f"Saving {name} · {done}/{total}")

    def _on_cache_save_finished(self, error: str) -> None:
        signals, self._cache_save_signals = self._cache_save_signals, None
        self._save_bar.hide()
        if signals is not None:
            signals.progressed.disconnect()
            signals.finished.disconnect()
        if error:
            QMessageBox.critical(self, "Save failed", error)
            return
        # Mark clean only if editing has not moved past the snapshot the
        # writer just committed — an edit made *during* the write stays
        # unsaved, as it should.
        if self.undo_stack.index() == self._save_clean_index:
            self.undo_stack.setClean()
        if self.engine.active:
            return      # the run line is speaking; do not talk over it
        self._announce_saved()

    def _announce_saved(self) -> None:
        msg = f"Saved {self._project_path}"
        if self._folded_sidecar:
            self._folded_sidecar = False
            msg += (f" · folded {Path(self._project_path).name}.cache "
                    f"into the project file")
        self.show_status(msg, 4000)

    def _cache_still_writing(self) -> bool:
        """True while a background cache write from the last Save is going.
        Starting a run mid-write would dirty and refill the very entries the
        writer is walking; the honest answer is to wait, briefly."""
        if self._cache_save_signals is None:
            return False
        self.show_status(
            "Still saving cached results — starting a run waits for it",
            4000)
        return True

    def _wait_for_cache_save(self) -> None:
        """On close: pump events until the background cache write lands.

        Closing right after "Save them first?" would otherwise tear down the
        window under a runnable that may be halfway through writing blobs —
        atomic per blob, but a manifest that never gets written throws away
        the whole side-car's worth of work. Bounded like
        _wait_for_cache_load, for the same reason."""
        if self._cache_save_signals is None:
            return
        deadline = time.monotonic() + 60
        while self._cache_save_signals is not None and time.monotonic() < deadline:
            QApplication.processEvents(QEventLoop.WaitForMoreEvents, 200)
        signals, self._cache_save_signals = self._cache_save_signals, None
        if signals is not None:
            signals.progressed.disconnect()
            signals.finished.disconnect()

    def _save_as(self) -> bool:
        # Before the dialog and before _project_path moves: refusing after
        # the switch would leave the project aimed at a file never written.
        if self._cache_save_signals is not None:
            self.show_status(
                "Still writing the last save — try again in a moment", 4000)
            return False
        old_path = self._project_path
        if old_path:
            suggested = str(Path(old_path).with_suffix(".flograph"))
        else:
            suggested = "untitled.flograph"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", suggested,
            "flograph projects (*.flograph)")
        if not path:
            return False
        if path.endswith(".flowf"):
            path = path[:-len(".flowf")] + ".flograph"
        elif not path.endswith(".flograph"):
            path += ".flograph"
        self._project_path = path
        self.resource_monitor.set_disk_watch_path(path)
        # carry the cached results across from the old file rather than
        # re-pickling them (or dropping the ones not in memory)
        return self._save(carry_from=old_path)

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
