"""DashboardScene: a *view* of one Page's tiles, mirroring the modeling
scene's one-way data flow — tile interactions push QUndoCommands, graph
events come back and update the items.

Live updates are dispatched centrally: the scene subscribes once to the
engine and graph and routes to its tiles by node id, so tiles themselves
never hold event subscriptions. Core `Event.connect` keeps strong references
— whoever removes a page MUST call dispose() or the dead scene keeps
receiving events and touches deleted Qt objects."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QGraphicsScene

from flograph.core import Graph, Tile

from ..commands import MoveResizeTileCommand, RemoveTileCommand
from ..canvas.scene import SCENE_EXTENT
from .tile_item import TileItem


class DashboardScene(QGraphicsScene):
    button_fired = Signal(str)  # node_id — an Action Button tile was clicked
    slicer_changed = Signal(str)  # node_id — a Slicer tile's selection changed

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

        self.setSceneRect(QRectF(-SCENE_EXTENT, -SCENE_EXTENT,
                                 2 * SCENE_EXTENT, 2 * SCENE_EXTENT))

        events = graph.events
        self._event_subs = [
            (events.tile_added, self._on_tile_added),
            (events.tile_removed, self._on_tile_removed),
            (events.tile_changed, self._on_tile_changed),
            (events.node_added, self._on_node_presence_changed),
            (events.node_removed, self._on_node_presence_changed),
            (events.dirty_changed, self._on_dirty_changed),
            (events.label_changed, self._on_label_changed),
            (events.param_changed, self._on_param_changed),
        ]
        for event, callback in self._event_subs:
            event.connect(callback)
        engine.node_succeeded.connect(self._on_node_ran)
        engine.node_failed.connect(self._on_node_ran)

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

    # ------------------------------------------------------- event mirrors

    def _on_tile_added(self, page_id: str, tile: Tile) -> None:
        if page_id != self.page_id:
            return
        item = TileItem(tile, self.graph, self.engine)
        self.addItem(item)
        self.tile_items[tile.id] = item

    def _on_tile_removed(self, page_id: str, tile_id: str) -> None:
        if page_id != self.page_id:
            return
        item = self.tile_items.pop(tile_id, None)
        if item is not None:
            self.removeItem(item)

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
            item.update()

    def _on_label_changed(self, node_id: str) -> None:
        for item in self._tiles_for(node_id):
            item.refresh_content()

    def _on_param_changed(self, node_id: str, name: str, value) -> None:
        for item in self._tiles_for(node_id):
            item.on_param_changed()

    # ------------------------------------------------------------- helpers

    def selected_tile_items(self) -> list[TileItem]:
        return [i for i in self.selectedItems() if isinstance(i, TileItem)]

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
