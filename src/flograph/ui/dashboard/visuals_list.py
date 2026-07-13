"""VisualsList: the flow's tile-able nodes (Show* visuals and Action
Buttons), draggable onto the dashboard page beside it."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

from flograph.core import Graph

TILE_NODE_MIME = "application/x-flograph-tile-node"

_KIND_GLYPHS = {
    "figure": "📈",
    "webview": "📊",
    "table_viewer": "▦",
    "kpi": "🔢",
    "slicer": "⑂",
    "button": "▶",
}


class VisualsList(QListWidget):
    def __init__(self, graph: Graph, parent=None) -> None:
        super().__init__(parent)
        self._graph = graph
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

        events = graph.events
        self._event_subs = [
            (events.node_added, self._on_nodes_changed),
            (events.node_removed, self._on_nodes_changed),
            (events.label_changed, self._on_nodes_changed),
        ]
        for event, callback in self._event_subs:
            event.connect(callback)
        self._rebuild()

    def dispose(self) -> None:
        """Core events hold strong refs — disconnect on page removal."""
        for event, callback in self._event_subs:
            event.disconnect(callback)
        self._event_subs = []

    def _on_nodes_changed(self, *args) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        from ..canvas.node_item import card_kind
        from .tile_item import is_tile_able
        self.clear()
        for node in self._graph.nodes.values():
            if not is_tile_able(node):
                continue
            glyph = _KIND_GLYPHS.get(card_kind(node), "")
            item = QListWidgetItem(f"{glyph} {node.label}".strip())
            item.setData(Qt.UserRole, node.id)
            item.setToolTip("Drag onto the page to place this visual")
            self.addItem(item)

    def mimeData(self, items) -> QMimeData:
        mime = QMimeData()
        for item in items:
            node_id = item.data(Qt.UserRole)
            if node_id:
                mime.setData(TILE_NODE_MIME, node_id.encode())
                break
        return mime

    def mimeTypes(self) -> list[str]:
        return [TILE_NODE_MIME]
