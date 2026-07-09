"""PopupView: a non-modal window showing one node's cached output for one
port, live-updating as the node re-runs. Multiple can be open at once, for
the same or different nodes — opened from the canvas's node context menu."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from flopy.core import Graph
from flopy.engine import ExecutionEngine

from .view_for import view_for


class PopupView(QDialog):
    def __init__(self, graph: Graph, engine: ExecutionEngine,
                 node_id: str, port_name: str, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._graph = graph
        self._engine = engine
        self._node_id = node_id
        self._port_name = port_name
        self._current_widget: Optional[QWidget] = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)

        engine.node_succeeded.connect(self._on_node_ran)
        engine.node_failed.connect(self._on_node_ran)
        graph.events.dirty_changed.connect(self._on_dirty_changed)
        graph.events.node_removed.connect(self._on_node_removed)
        self.destroyed.connect(self._disconnect)

        self._refresh()
        self.resize(640, 480)

    def _disconnect(self, *_args) -> None:
        for sig, slot in (
            (self._engine.node_succeeded, self._on_node_ran),
            (self._engine.node_failed, self._on_node_ran),
            (self._graph.events.dirty_changed, self._on_dirty_changed),
            (self._graph.events.node_removed, self._on_node_removed),
        ):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _refresh(self) -> None:
        entry = self._engine.cache.get(self._node_id)
        value = entry.outputs.get(self._port_name) if entry else None
        if self._current_widget is not None:
            self._layout.removeWidget(self._current_widget)
            self._current_widget.deleteLater()
        self._current_widget = view_for(value)
        self._layout.addWidget(self._current_widget)
        node = self._graph.nodes.get(self._node_id)
        stale = bool(node and node.dirty and entry is not None)
        self.setWindowTitle(
            f"{node.label if node else '?'} — {self._port_name}"
            + ("  [STALE]" if stale else ""))

    def _on_node_ran(self, node_id: str, *_args) -> None:
        if node_id == self._node_id:
            self._refresh()

    def _on_dirty_changed(self, node_id: str, _dirty: bool) -> None:
        if node_id == self._node_id:
            self._refresh()

    def _on_node_removed(self, node_id: str) -> None:
        if node_id == self._node_id:
            self.close()
