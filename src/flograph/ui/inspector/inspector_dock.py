"""The inspector: click a node (or a wire) and see the cached data flowing
through it — table view for DataFrames, figure canvas for plots, pretty repr
for everything else. One tab per output port, with a stale watermark when the
node needs a re-run."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from flograph.core import Connection, Graph
from flograph.engine import ExecutionEngine, summarize

from .spec_view import spec_view_for
from .view_for import view_for as _view_for


class InspectorPanel(QWidget):
    def __init__(self, graph: Graph, engine: ExecutionEngine, parent=None) -> None:
        super().__init__(parent)
        self._graph = graph
        self._engine = engine
        self._node_id: Optional[str] = None
        self._port_filter: Optional[str] = None  # set when inspecting a wire

        self._header = QLabel("Nothing selected")
        self._header.setStyleSheet("color: #9ca3af;")
        self._stale = QLabel("STALE — re-run to refresh")
        self._stale.setStyleSheet(
            "color: #eab308; font-weight: bold; padding: 0 8px;")
        self._stale.hide()
        top = QHBoxLayout()
        top.addWidget(self._header, 1)
        top.addWidget(self._stale)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.addLayout(top)
        layout.addWidget(self._tabs, 1)

        engine.node_succeeded.connect(self._on_node_ran)
        engine.node_failed.connect(self._on_node_ran)
        graph.events.dirty_changed.connect(self._on_dirty_changed)
        graph.events.node_removed.connect(self._on_node_removed)

    # -------------------------------------------------------------- targets

    def show_node(self, node_id: Optional[str]) -> None:
        self._node_id = node_id
        self._port_filter = None
        self._refresh()

    def show_wire(self, conn: Connection) -> None:
        """Inspect the value flowing on a wire = its source port's cache."""
        self._node_id = conn.src_node
        self._port_filter = conn.src_port
        self._refresh()

    # -------------------------------------------------------------- refresh

    def _refresh(self) -> None:
        self._tabs.clear()
        if self._node_id is None or self._node_id not in self._graph.nodes:
            self._header.setText("Nothing selected")
            self._stale.hide()
            return
        node = self._graph.node(self._node_id)
        entry = self._engine.cache.get(self._node_id)
        self._stale.setVisible(node.dirty and entry is not None)

        ports = [p for p in node.spec.outputs
                 if self._port_filter is None or p.name == self._port_filter]
        if not ports:
            self._header.setText(f"{node.label} — no output ports")
            return

        if entry is None:
            self._header.setText(f"{node.label} — not computed yet")
            for port in ports:
                placeholder = QLabel("Run the graph to see this output.")
                placeholder.setAlignment(Qt.AlignCenter)
                placeholder.setStyleSheet("color: #6b7280;")
                self._tabs.addTab(placeholder, port.name)
            return

        wire_note = f" · wire: {self._port_filter}" if self._port_filter else ""
        self._header.setText(
            f"{node.label} — computed in {entry.wall_time * 1000:.0f} ms{wire_note}")
        for port in ports:
            value = entry.outputs.get(port.name)
            host = QWidget()
            host_layout = QVBoxLayout(host)
            host_layout.setContentsMargins(0, 2, 0, 0)
            meta = QLabel(f"{port.type.value} · {summarize(value)}")
            meta.setStyleSheet("color: #6b7280; font-size: 8pt; padding: 0 4px;")
            host_layout.addWidget(meta)
            spec = spec_view_for(value)
            if spec is None:
                host_layout.addWidget(_view_for(value), 1)
            else:
                # table values get a column spec next to the data
                sub = QTabWidget()
                sub.setDocumentMode(True)
                sub.addTab(_view_for(value), "Data")
                sub.addTab(spec, "Spec")
                host_layout.addWidget(sub, 1)
            self._tabs.addTab(host, port.name)

    # --------------------------------------------------------------- events

    def _on_node_ran(self, node_id: str, *args) -> None:
        if node_id == self._node_id:
            self._refresh()

    def _on_dirty_changed(self, node_id: str, dirty: bool) -> None:
        if node_id == self._node_id:
            node = self._graph.nodes.get(node_id)
            has_cache = self._engine.cache.has(node_id)
            self._stale.setVisible(bool(node and node.dirty and has_cache))

    def _on_node_removed(self, node_id: str) -> None:
        if node_id == self._node_id:
            self.show_node(None)
