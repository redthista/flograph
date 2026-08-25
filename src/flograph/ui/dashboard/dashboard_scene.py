"""DashboardScene: a *view* of one Page's tiles, mirroring the modeling
scene's one-way data flow — tile interactions push QUndoCommands, graph
events come back and update the items.

Live updates are dispatched centrally: the scene subscribes once to the
engine and graph and routes to its tiles by node id, so tiles themselves
never hold event subscriptions. Core `Event.connect` keeps strong references
— whoever removes a page MUST call dispose() or the dead scene keeps
receiving events and touches deleted Qt objects."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QGraphicsScene

from flograph.core import Graph, Tile

from ..commands import (
    MoveResizeTileCommand, RemoveTileCommand, SetPageMaximizedTileCommand,
)
from ..canvas.scene import ContentFittedSceneRect
from .tile_item import TileItem


class DashboardScene(QGraphicsScene, ContentFittedSceneRect):
    button_fired = Signal(str)  # node_id — an Action Button tile was clicked
    slicer_changed = Signal(str)  # node_id — a Slicer tile's selection changed
    sheet_edited = Signal(str)  # node_id — a Table tile's cells were edited
    control_changed = Signal(str)  # node_id — an input control was moved

    def __init__(self, graph: Graph, engine, undo_stack: QUndoStack,
                 page_id: str, parent=None) -> None:
        super().__init__(parent)
        self.graph = graph
        self.engine = engine
        self.undo_stack = undo_stack
        self.page_id = page_id
        self.tile_items: dict[str, TileItem] = {}

        # Snap-to-grid view preference; the main window is the sole writer.
        from ..canvas.grid import DEFAULT_STEP
        self.snap_enabled = True
        self.grid_step = DEFAULT_STEP
        # Layout locked (view mode). Read by tiles built later, so a tile
        # added to a view-mode page arrives locked rather than movable.
        self.view_mode = False

        self._install_rect_fit()
        self._fit_scene_rect()

        events = graph.events
        self._event_subs = [
            (events.tile_added, self._on_tile_added),
            (events.tile_removed, self._on_tile_removed),
            (events.tile_changed, self._on_tile_changed),
            (events.page_changed, self._on_page_changed),
            (events.node_added, self._on_node_presence_changed),
            (events.node_removed, self._on_node_presence_changed),
            (events.dirty_changed, self._on_dirty_changed),
            (events.status_changed, self._on_status_changed),
            (events.label_changed, self._on_label_changed),
            (events.param_changed, self._on_param_changed),
            (events.restacked, self._on_restacked),
        ]
        for event, callback in self._event_subs:
            event.connect(callback)
        engine.node_succeeded.connect(self._on_node_ran)
        engine.node_failed.connect(self._on_node_ran)
        engine.request_changed.connect(self._on_request_changed)

        page = graph.pages.get(page_id)
        if page is not None:
            for tile in page.tiles.values():
                self._on_tile_added(page_id, tile)

    def dispose(self) -> None:
        """Mandatory on page removal: core events hold strong refs and would
        keep calling into this scene after its Qt side is deleted."""
        for event, callback in self._event_subs:
            event.disconnect(callback)
        self._event_subs = []
        self.engine.node_succeeded.disconnect(self._on_node_ran)
        self.engine.node_failed.disconnect(self._on_node_ran)
        self.engine.request_changed.disconnect(self._on_request_changed)
        for item in self.tile_items.values():
            item.dispose()

    # ------------------------------------------------------- event mirrors

    def _on_tile_added(self, page_id: str, tile: Tile) -> None:
        if page_id != self.page_id:
            return
        item = TileItem(tile, self.graph, self.engine)
        self.addItem(item)
        self.tile_items[tile.id] = item
        if self.view_mode:
            # undoing a delete on a view-mode page must bring the tile back
            # locked, not as the one movable thing on a locked page
            item.set_layout_locked(True)
        if any(getattr(view, "fullscreen_tile", None) is not None
               for view in self.views()):
            # a tile added (or undeleted) while another is maximized must not
            # pop up over it — it reappears when fullscreen is left
            item.setVisible(False)
        # undoing the delete of a maximized tile brings it back maximized
        self.sync_fullscreen()

    def _on_tile_removed(self, page_id: str, tile_id: str) -> None:
        if page_id != self.page_id:
            return
        item = self.tile_items.pop(tile_id, None)
        if item is not None:
            # leaves page.maximized_tile dangling rather than writing to the
            # graph outside a command — sync_fullscreen ignores an id with no
            # tile, and undoing the delete resolves it again
            self.sync_fullscreen()
            # stop anything still running before the item's widgets go: a
            # QMovie writing into a deleted document is a crash
            item.dispose()
            self.removeItem(item)

    def set_animations_playing(self, playing: bool) -> None:
        """The page holding this scene was shown or hidden — an animation
        on a tab nobody has open should not be spending frames."""
        for item in self.tile_items.values():
            item.set_animations_playing(playing)

    def _on_page_changed(self, page) -> None:
        if page.id == self.page_id:
            self.sync_fullscreen()

    def _on_tile_changed(self, page_id: str, tile: Tile) -> None:
        if page_id != self.page_id:
            return
        item = self.tile_items.get(tile.id)
        if item is not None:
            item.sync_from_model()

    def _tiles_for(self, node_id: str) -> list[TileItem]:
        return [item for item in self.tile_items.values()
                if item.tile.node_id == node_id]

    def _on_node_ran(self, node_id: str, *args) -> None:
        for item in self._tiles_for(node_id):
            item.refresh_content()

    def _on_node_presence_changed(self, node_or_id) -> None:
        node_id = getattr(node_or_id, "id", node_or_id)
        for item in self._tiles_for(node_id):
            item.refresh_content()

    def _on_dirty_changed(self, node_id: str, dirty: bool) -> None:
        for item in self._tiles_for(node_id):
            item.refresh_freshness()

    def _on_status_changed(self, node_id: str, status, message: str) -> None:
        """Queued, running, done: what the tile paints its UPDATING badge
        and its fade from, so it has to hear about every hop."""
        for item in self._tiles_for(node_id):
            item.refresh_freshness()

    def _on_request_changed(self) -> None:
        """A re-run was queued or dequeued. Which nodes it covers is the
        engine's to answer, so every tile re-asks rather than being told."""
        for item in self.tile_items.values():
            item.refresh_freshness()

    def _on_label_changed(self, node_id: str) -> None:
        for item in self._tiles_for(node_id):
            item.refresh_content()

    def _on_param_changed(self, node_id: str, name: str, value) -> None:
        # A report tile draws from nodes *upstream* of itself, so a param
        # change it should react to usually belongs to some other node —
        # and a cosmetic one never runs the flow to announce itself.
        for item in self.tile_items.values():
            if item._kind() == "report":
                item._render_report()
        for item in self._tiles_for(node_id):
            item.on_param_changed()

    # ------------------------------------------------------------- helpers

    def selected_tile_items(self) -> list[TileItem]:
        return [i for i in self.selectedItems() if isinstance(i, TileItem)]

    def set_view_mode(self, view_mode: bool) -> None:
        """Lock or unlock every tile's furniture. Contents are untouched —
        see DashboardPage.set_view_mode for why that distinction is the
        whole point."""
        self.view_mode = bool(view_mode)
        if self.view_mode:
            self.clearSelection()   # a selection outline is editing chrome
        for item in self.tile_items.values():
            item.set_layout_locked(self.view_mode)

    def refresh_render_ratios(self) -> None:
        for item in self.tile_items.values():
            item.refresh_render_ratio()

    def remove_tile(self, tile_id: str) -> None:
        self.undo_stack.push(
            RemoveTileCommand(self.graph, self.page_id, tile_id))

    def delete_selected_tiles(self) -> None:
        items = self.selected_tile_items()
        if not items:
            return
        self.undo_stack.beginMacro("delete tiles")
        for item in items:
            self.remove_tile(item.tile.id)
        self.undo_stack.endMacro()

    def push_tile_rect(self, tile_id: str, old_rect: tuple,
                       new_rect: tuple) -> None:
        self.undo_stack.push(MoveResizeTileCommand(
            self.graph, self.page_id, tile_id, old_rect, new_rect))

    # -------------------------------------------------------------- layering

    def restack_selection(self, action: str) -> bool:
        """Bring the selected tiles to the front / forward / backward / to
        the back, in one undo step. Returns whether anything moved."""
        from flograph.core.layers import restack

        from ..canvas.stacking import LAYER_LABELS
        from ..commands import RestackCommand
        ids = {i.tile.id for i in self.selected_tile_items()}
        if not ids or self.page_id not in self.graph.pages:
            return False
        current = self.graph.stacking_order("tile", self.page_id)
        new = restack(current, ids, action)
        if new == current:
            return False
        self.undo_stack.push(RestackCommand(
            self.graph, "tile", new, self.page_id, LAYER_LABELS[action]))
        return True

    def _on_restacked(self, kind: str, page_id) -> None:
        if kind != "tile" or page_id != self.page_id:
            return
        for item in self.tile_items.values():
            item.apply_stacking()

    # ----------------------------------------------------------- fullscreen

    def _maximized_tile_id(self) -> Optional[str]:
        page = self.graph.pages.get(self.page_id)
        return page.maximized_tile if page is not None else None

    def toggle_fullscreen(self, tile_id: str) -> None:
        """A tile's maximize/restore button (or a title-bar double-click).
        Pushed rather than applied directly: which tile is maximized is saved
        with the project, so it is a graph edit like any other."""
        if self.page_id not in self.graph.pages:
            return
        target = None if self._maximized_tile_id() == tile_id else tile_id
        self.undo_stack.push(SetPageMaximizedTileCommand(
            self.graph, self.page_id, target))

    def exit_fullscreen(self) -> None:
        """Esc, and anything else that means "give me the page back"."""
        if self._maximized_tile_id():
            self.undo_stack.push(SetPageMaximizedTileCommand(
                self.graph, self.page_id, None))

    def sync_fullscreen(self) -> None:
        """Point the views at whatever the model says is maximized. The one
        place the view's fullscreen is turned on or off — everything else
        edits the model and lands back here."""
        tile_id = self._maximized_tile_id()
        item = self.tile_items.get(tile_id) if tile_id else None
        for view in self.views():
            if not hasattr(view, "fullscreen_tile"):
                continue  # a plain QGraphicsView attached for a screenshot
            if item is None:
                view.exit_fullscreen()
            elif view.fullscreen_tile is not item:
                view.enter_fullscreen(item)
