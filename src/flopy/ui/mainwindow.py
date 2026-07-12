from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, QSettings, Qt
from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QInputDialog, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QStackedWidget,
    QTextEdit, QToolBar, QVBoxLayout, QWidget,
)

from flopy.core import (
    Graph, GraphError, NodeInstance, NodeRegistry, NodeStatus, Page, Tile,
    parse_spec,
)
from flopy.core import serialization
from flopy.core import user_nodes
from flopy.engine import ExecutionEngine, cache_persistence
from flopy.paths import user_nodes_dir

from .commands import (
    AddNodeCommand, AddPageCommand, AddTileCommand, ConnectCommand,
    RemovePageCommand, RenamePageCommand, SetLabelCommand,
)
from .canvas import ConnectionItem, NodeGraphScene, NodeGraphView
from .canvas.node_item import (
    FIGURE_TYPES, KPI_TYPE, PLOTLY_TYPE, SLICER_TYPE, TABLE_VIEWER_TYPES,
)
from .canvas.palette import LibraryTree, NodePalettePopup
from .dashboard import (
    DashboardPage, PageTabBar, TILE_ABLE_TYPES, default_tile_port,
    default_tile_size,
)
from .console.log_dock import LogConsole
from .editor.editor_dock import EditorPanel
from .editor.save_user_node_dialog import SaveUserNodeDialog
from .inspector.inspector_dock import InspectorPanel
from .properties.params_panel import ParamsPanel

MAX_RECENT = 8
PASTE_OFFSET = 30.0
_CLIPBOARD_KEY = "flopy_clipboard"


class MainWindow(QMainWindow):
    def __init__(self, registry: NodeRegistry) -> None:
        super().__init__()
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks)
        self.registry = registry
        self.graph = Graph()
        self.undo_stack = QUndoStack(self)
        self.scene = NodeGraphScene(self.graph, self.undo_stack,
                                    registry=registry, parent=self)
        self.view = NodeGraphView(self.scene)
        self._canvas_stack = QStackedWidget()
        self._canvas_stack.addWidget(self.view)
        self.page_bar = PageTabBar()
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._canvas_stack, 1)
        central_layout.addWidget(self.page_bar)
        self.setCentralWidget(central)
        self._dashboard_pages: dict[str, DashboardPage] = {}
        self._restoring_pages = False
        self.engine = ExecutionEngine(self.graph, parent=self)
        self.settings = QSettings("flopy", "flopy")
        self._project_path: Optional[str] = None
        # set False to close without the unsaved-changes prompt (tests, scripts)
        self.confirm_close = True

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
        self._update_title()
        self._restore_window_state()
        self.statusBar().showMessage("Ready")

    # ---------------------------------------------------------------- docks

    def _build_docks(self) -> None:
        self.library_tree = LibraryTree(self.registry)
        library_dock = QDockWidget("Node Library", self)
        library_dock.setObjectName("dock_library")
        library_dock.setWidget(self.library_tree)
        self.addDockWidget(Qt.LeftDockWidgetArea, library_dock)
        self.library_tree.add_requested.connect(self._add_node_at_view_center)
        self.library_tree.new_group_requested.connect(self._new_user_group)
        self.library_tree.rename_user_node_requested.connect(
            self._rename_user_node)
        self.library_tree.move_user_node_requested.connect(self._move_user_node)
        self.library_tree.delete_user_node_requested.connect(
            self._delete_user_node)

        self.params_panel = ParamsPanel(self.graph, self.undo_stack,
                                        cache=self.engine.cache)
        self.properties_dock = QDockWidget("Properties", self)
        self.properties_dock.setObjectName("dock_properties")
        self.properties_dock.setWidget(self.params_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.properties_dock)

        self.editor_panel = EditorPanel(self.graph, self.undo_stack, self.registry)
        self.editor_panel.save_as_user_node_requested.connect(
            self._save_as_user_node)
        self.editor_dock = QDockWidget("Code", self)
        self.editor_dock.setObjectName("dock_editor")
        self.editor_dock.setWidget(self.editor_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.editor_dock)
        self.tabifyDockWidget(self.properties_dock, self.editor_dock)
        self.properties_dock.raise_()
        self.resizeDocks([self.properties_dock], [420], Qt.Horizontal)

        self.inspector_panel = InspectorPanel(self.graph, self.engine)
        self.inspector_dock = QDockWidget("Inspector", self)
        self.inspector_dock.setObjectName("dock_inspector")
        self.inspector_dock.setWidget(self.inspector_panel)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.inspector_dock)

        self.log_console = LogConsole(self.graph, self.engine)
        self.log_dock = QDockWidget("Log", self)
        self.log_dock.setObjectName("dock_log")
        self.log_dock.setWidget(self.log_console)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
        self.tabifyDockWidget(self.inspector_dock, self.log_dock)
        self.inspector_dock.raise_()
        self.resizeDocks([self.inspector_dock], [260], Qt.Vertical)

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
        self.action_packages = act("Manage &Packages…", None,
                                   self._show_packages)

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
        tools_menu.addAction(self.action_packages)

        view_menu = self.menuBar().addMenu("&View")
        for dock in self.findChildren(QDockWidget):
            view_menu.addAction(dock.toggleViewAction())

    def _smart_edit(self, text_method: str, canvas_fn) -> None:
        """Route Ctrl+Z/X/C/V to the focused text widget when there is one,
        to the canvas otherwise."""
        widget = QApplication.focusWidget()
        if isinstance(widget, (QPlainTextEdit, QTextEdit, QLineEdit)):
            getattr(widget, text_method)()
        else:
            canvas_fn()

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
        engine.node_succeeded.connect(self._on_kpi_node_succeeded)
        engine.node_succeeded.connect(self._on_slicer_node_succeeded)

    def _wire_canvas(self) -> None:
        self.view.add_node_requested.connect(self._show_add_node_menu)
        self.view.palette_requested.connect(self._show_palette)
        self.view.node_dropped.connect(self._add_node_at)
        self.view.node_context_requested.connect(self._show_node_menu)
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.scene.node_double_clicked.connect(self._on_node_double_clicked)
        self.scene.node_rename_requested.connect(self._rename_node)
        self.scene.wire_dropped.connect(self._on_wire_dropped)
        self.scene.button_fired.connect(self._on_button_fired)
        self.scene.slicer_changed.connect(self._on_slicer_changed)
        self.scene.frame_run_requested.connect(self._on_frame_run_requested)

    def _on_figure_node_succeeded(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None or node.type_id not in FIGURE_TYPES:
            return
        item = self.scene.node_items.get(node_id)
        if item is None:
            return
        entry = self.engine.cache.get(node_id)
        item.set_figure(entry.outputs.get("figure") if entry else None)

    def _on_plotly_node_succeeded(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None or node.type_id != PLOTLY_TYPE:
            return
        item = self.scene.node_items.get(node_id)
        if item is None:
            return
        entry = self.engine.cache.get(node_id)
        item.set_plotly_figure(entry.outputs.get("figure") if entry else None)

    def _on_table_viewer_node_succeeded(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None or node.type_id not in TABLE_VIEWER_TYPES:
            return
        item = self.scene.node_items.get(node_id)
        if item is None:
            return
        entry = self.engine.cache.get(node_id)
        # first output holds the displayed frame: "table" for Show Table,
        # "spec" for Table Spec
        port = node.spec.outputs[0].name if node.spec.outputs else "table"
        item.set_table_data(entry.outputs.get(port) if entry else None)

    def _on_kpi_node_succeeded(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None or node.type_id != KPI_TYPE:
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
        if node is None or node.type_id != SLICER_TYPE:
            return
        item = self.scene.node_items.get(node_id)
        if item is None:
            return
        from flopy.engine.introspect import slicer_options
        item.set_slicer_options(
            slicer_options(self.graph, self.engine.cache, node_id))

    # ------------------------------------------------------ dashboard pages

    def _wire_pages(self) -> None:
        events = self.graph.events
        events.page_added.connect(self._on_page_added)
        events.page_removed.connect(self._on_page_removed)
        events.page_changed.connect(self._on_page_changed)
        self.page_bar.add_page_requested.connect(self._add_page)
        self.page_bar.rename_page_requested.connect(self._rename_page)
        self.page_bar.delete_page_requested.connect(self._delete_page)
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

    def _on_current_page_changed(self, page_id) -> None:
        widget = self._dashboard_pages.get(page_id) if page_id else None
        self._canvas_stack.setCurrentWidget(
            widget if widget is not None else self.view)
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
        width, height = default_tile_size(node.type_id)
        tile = Tile(id=uuid.uuid4().hex, node_id=node_id,
                    port=default_tile_port(node.type_id),
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
        if node is not None and node.type_id in (
                "flopy.util.note", "flopy.util.action_button"):
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
            if new != node.label_override:
                self.undo_stack.push(SetLabelCommand(self.graph, node_id, new))

    def _rename_selected(self) -> None:
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
        dialog.activateWindow()

    # ------------------------------------------------------- action button

    def _on_button_fired(self, node_id: str) -> None:
        node = self.graph.nodes.get(node_id)
        if node is None or node.type_id != "flopy.util.action_button":
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
        if node is None or node.type_id != SLICER_TYPE:
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
        from flopy.core import can_connect
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
        from flopy.core import can_connect
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
        chosen = menu.exec(global_pos)
        if chosen is frame_action:
            self._add_frame_at(scene_pos)
        elif chosen is not None and chosen.data():
            self._add_node_at(chosen.data(), scene_pos)

    def _show_node_menu(self, node_id: str, global_pos: QPoint) -> None:
        if node_id not in self.graph.nodes:
            return
        item = self.scene.node_items.get(node_id)
        if item is not None and not item.isSelected():
            self.scene.clearSelection()
            item.setSelected(True)
        menu = QMenu(self)
        run_to = menu.addAction("Run To This Node")
        menu.addSeparator()
        edit_code = menu.addAction("Edit Code")
        rename = menu.addAction("Rename")
        rerun = menu.addAction("Mark Dirty")
        view_actions = self._add_view_actions(menu, node_id)
        page_actions: list = []
        new_page_action = None
        if self.graph.nodes[node_id].type_id in TILE_ABLE_TYPES:
            submenu = menu.addMenu("Add to Page")
            for page in self.graph.pages.values():
                page_actions.append((submenu.addAction(page.title), page.id))
            if page_actions:
                submenu.addSeparator()
            new_page_action = submenu.addAction("New Page…")
        menu.addSeparator()
        delete = menu.addAction("Delete")
        chosen = menu.exec(global_pos)
        if chosen is run_to:
            self.engine.run_to(node_id)
        elif chosen is edit_code:
            self._on_node_double_clicked(node_id)
        elif chosen is rename:
            self._rename_node(node_id)
        elif chosen is rerun:
            self.graph.mark_dirty(node_id)
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
        from flopy.core import Frame
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
        from flopy.core import Frame
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
        state = self.settings.value("window_state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)

    def _save_window_state(self) -> None:
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())

    # ----------------------------------------------------------- copy/paste

    def _selection_payload(self) -> Optional[dict]:
        nodes = [item.node for item in self.scene.selected_node_items()]
        if not nodes:
            return None
        ids = {n.id for n in nodes}
        return {
            _CLIPBOARD_KEY: 1,
            "nodes": [{
                "id": n.id, "type": n.type_id, "pos": list(n.pos),
                "params": dict(n.params), "code": n.code_override,
                "label": n.label_override,
            } for n in nodes],
            "connections": [{
                "src": [c.src_node, c.src_port], "dst": [c.dst_node, c.dst_port],
            } for c in self.graph.connections.values()
                if c.src_node in ids and c.dst_node in ids],
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

    def _paste(self) -> None:
        try:
            payload = json.loads(QApplication.clipboard().text())
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(payload, dict) or _CLIPBOARD_KEY not in payload:
            return
        self._insert_payload(payload)

    def _duplicate(self) -> None:
        payload = self._selection_payload()
        if payload is not None:
            self._insert_payload(payload)

    def _insert_payload(self, payload: dict) -> None:
        id_map: dict[str, str] = {}
        new_nodes: list[NodeInstance] = []
        for entry in payload.get("nodes", []):
            code = entry.get("code")
            if code is not None:
                try:
                    spec = parse_spec(code, entry["type"])
                except Exception:
                    continue
            else:
                spec = self.registry.maybe_get(entry["type"])
                if spec is None:
                    continue
            new_id = uuid.uuid4().hex
            id_map[entry["id"]] = new_id
            new_nodes.append(NodeInstance(
                id=new_id, spec=spec, code_override=code,
                params={**spec.default_params(), **entry.get("params", {})},
                pos=(entry["pos"][0] + PASTE_OFFSET,
                     entry["pos"][1] + PASTE_OFFSET),
                label_override=entry.get("label"),
            ))
        if not new_nodes:
            return
        self.undo_stack.beginMacro("paste")
        for node in new_nodes:
            self.undo_stack.push(AddNodeCommand(self.graph, node))
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

    # ------------------------------------------------------ project files

    def _on_clean_changed(self, clean: bool) -> None:
        self._update_title()

    def _update_title(self) -> None:
        name = Path(self._project_path).name if self._project_path else "untitled"
        self.setWindowTitle(f"{name}[*] — flopy")
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
            self._save_window_state()
            event.accept()
        else:
            event.ignore()

    def _new_project(self) -> None:
        if not self._confirm_discard():
            return
        self._replace_graph(Graph())
        self._project_path = None
        self._update_title()

    def _open_dialog(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "flopy projects (*.flopy)")
        if path:
            self.open_path(path, confirm=False)

    def open_path(self, path: str, confirm: bool = True) -> bool:
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
        restored = cache_persistence.load_cache(self.graph, self.engine.cache, path)
        for node_id in restored:
            self.graph.mark_clean(node_id)
            self.graph.set_status(node_id, NodeStatus.DONE)
            self.engine.node_succeeded.emit(node_id)
        saved_page = self.settings.value(f"active_page/{path}", "")
        if saved_page and saved_page in self.graph.pages:
            self.page_bar.select_page(saved_page)
        broken = sum(1 for n in loaded.nodes.values() if n.spec.broken)
        if broken:
            self.statusBar().showMessage(
                f"Opened {path} — {broken} node(s) couldn't be resolved and "
                f"were loaded as broken placeholders", 6000)
        elif restored:
            self.statusBar().showMessage(
                f"Opened {path} — {len(restored)} node(s) restored from cache", 4000)
        else:
            self.statusBar().showMessage(f"Opened {path}", 4000)
        return True

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
            self, "Save project", "untitled.flopy", "flopy projects (*.flopy)")
        if not path:
            return False
        if not path.endswith(".flopy"):
            path += ".flopy"
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
