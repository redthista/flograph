"""NodeWindow: one node's Properties and Code in a floating window.

Ctrl+double-click a node on the canvas. Several can be open at once — that
is the point of it, and the reason it exists alongside the docks: the docks
show whatever is *selected*, one node at a time, so comparing two nodes'
parameters, or keeping a script visible while editing the node that feeds it,
means clicking back and forth and losing your place.

Ordinary windows, deliberately: no Qt.Tool, no always-on-top. A window you
have to dismiss before you can use the app is a modal dialog wearing a
disguise, and these are meant to be left open and stacked with everything
else the way any other window is.

**One window per node.** MainWindow keeps a registry keyed by node id and
raises the existing window rather than opening a second, because two editors
on the *same* node genuinely conflict: `NodeInstance._temp_edit` and the
`temp_edit_changed` event are global, unowned state, so a second editor
loading a clean copy would clear the first one's unsaved-edit marker while it
still held unsaved text. Different nodes are fine, and are what this is for.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QDialog, QTabWidget, QVBoxLayout

from flograph.core import Graph, NodeRegistry

from .editor.editor_dock import EditorPanel
from .properties.params_panel import ParamsPanel


class NodeWindow(QDialog):
    """Properties and Code for one node, in tabs."""

    # forwarded from the embedded editor so MainWindow can own the dialog,
    # the filesystem and the registry reload exactly as it does for the dock
    save_as_user_node_requested = Signal(str)  # node_id
    closed = Signal(str)                       # node_id

    def __init__(self, graph: Graph, undo_stack: QUndoStack,
                 registry: NodeRegistry, node_id: str,
                 cache=None, parent=None) -> None:
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._graph = graph
        self._node_id = node_id

        self.params_panel = ParamsPanel(graph, undo_stack, cache=cache)
        self.editor_panel = EditorPanel(graph, undo_stack, registry)
        self.editor_panel.save_as_user_node_requested.connect(
            self.save_as_user_node_requested.emit)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.params_panel, "Properties")
        self.tabs.addTab(self.editor_panel, "Code")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.tabs)

        self.params_panel.set_node(node_id)
        self.editor_panel.set_node(node_id)

        graph.events.label_changed.connect(self._on_label_changed)
        graph.events.node_removed.connect(self._on_node_removed)
        self.destroyed.connect(self._disconnect)

        self._retitle()
        self.resize(460, 560)

    @property
    def node_id(self) -> str:
        return self._node_id

    def show_tab(self, name: str) -> None:
        """Bring one of the two tabs to the front by name."""
        index = 0 if name == "properties" else 1
        self.tabs.setCurrentIndex(index)

    def flush_pending(self) -> None:
        """Land any half-typed parameter. MainWindow calls this before a run,
        the same as it does for the docked panel — a value still sitting in
        the debounce timer is a value the run would otherwise miss."""
        self.params_panel.flush_pending()

    def _retitle(self) -> None:
        node = self._graph.nodes.get(self._node_id)
        self.setWindowTitle(node.label if node is not None else "Node")

    def _on_label_changed(self, node_id: str) -> None:
        if node_id == self._node_id and self._alive():
            self._retitle()

    def _on_node_removed(self, node_id: str) -> None:
        if node_id == self._node_id and self._alive():
            self.close()

    def _alive(self) -> bool:
        """WA_DeleteOnClose destruction is deferred, so a graph event already
        in flight can reach a window whose C++ half has gone. Same guard
        PopupView carries, for the same reason."""
        import shiboken6
        return shiboken6.isValid(self)

    def _disconnect(self, *_args) -> None:
        for event, slot in (
            (self._graph.events.label_changed, self._on_label_changed),
            (self._graph.events.node_removed, self._on_node_removed),
        ):
            try:
                event.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def closeEvent(self, event) -> None:
        # Unsaved code is the editor's business and stays unsaved; the
        # parameter debounce is not, and would otherwise be dropped on the
        # floor by a window closed a tenth of a second after a keystroke.
        self.params_panel.flush_pending()
        self.closed.emit(self._node_id)
        super().closeEvent(event)
