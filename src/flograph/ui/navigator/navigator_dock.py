"""The Navigator: a tree view of what is on the canvas.

Frames are the groups — a frame is a branch, and the nodes and frames inside
it are its children, nested as deep as the frames nest. Everything sitting on
the bare canvas is a top-level row alongside them. Click a row and the canvas
goes there: a node folded inside a collapsed frame lands on the frame instead
(there is nothing else to show), and the same click once the frame is open
lands on the node itself — `NodeGraphView.go_to_node` already draws that line.

The tree is rebuilt from the canvas on any change that could move a row —
node/frame added, removed, renamed, moved, folded — coalesced into one pass
per event loop turn. The expand/collapse state of the tree is the reader's
own and is kept across rebuilds; it has nothing to do with whether a frame is
folded on the canvas.

Three orderings, applied at every level: by position (top-to-bottom, then
left-to-right — how the eye scans the canvas), by name, or by runtime (the
slowest first, so the bottleneck floats to the top). A frame's runtime is the
sum of its contents'.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QStackedWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from flograph.core import Graph
from flograph.engine import ExecutionEngine

from ..resource_monitor import format_seconds

_ROLE = Qt.UserRole  # (kind, id) on column 0

_SORTS = [
    ("pos", "Position"),
    ("alpha", "Name"),
    ("runtime", "Runtime"),
]


class NavigatorPanel(QWidget):
    """Tree of the model canvas. Emits `navigate_requested(kind, id)` — kind is
    "node" or "frame" — when a row is clicked."""

    navigate_requested = Signal(str, str)

    def __init__(self, graph: Graph, scene, engine: ExecutionEngine,
                 parent=None) -> None:
        super().__init__(parent)
        self._graph = graph
        self._scene = scene
        self._engine = engine
        self._sort = "pos"
        #: frame ids the reader has collapsed in the tree (default is open)
        self._collapsed: set[str] = set()
        self._syncing = False  # guard: canvas -> tree selection echo
        self._runtime_cache: dict = {}  # frame_id -> summed wall time, per build

        self._combo = QComboBox()
        for key, label in _SORTS:
            self._combo.addItem(label, key)
        self._combo.setToolTip("How to order the rows, at every level")
        self._combo.currentIndexChanged.connect(self._on_sort_changed)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(QLabel("Sort"))
        top.addWidget(self._combo, 1)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.setUniformRowHeights(True)
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.itemCollapsed.connect(self._on_item_collapsed)

        self._placeholder = QLabel("Nothing on the canvas yet.")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color: #6b7280;")

        self._stack = QStackedWidget()
        self._stack.addWidget(self._tree)         # 0
        self._stack.addWidget(self._placeholder)  # 1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(4)
        layout.addLayout(top)
        layout.addWidget(self._stack, 1)

        # one rebuild once the dust settles — a node drag emits node_moved
        # per pixel, and opening a file emits a burst of node_added; the
        # timer restarts on each so the tree is rebuilt after the last one
        self._pending = QTimer(self)
        self._pending.setSingleShot(True)
        self._pending.setInterval(120)
        self._pending.timeout.connect(self._rebuild)

        ev = graph.events
        for event in (ev.node_added, ev.node_removed, ev.node_moved,
                      ev.label_changed, ev.frame_added, ev.frame_removed,
                      ev.frame_changed):
            event.connect(self._schedule)
        engine.node_succeeded.connect(self._on_node_ran)
        engine.node_failed.connect(self._on_node_ran)
        scene.selectionChanged.connect(self._sync_selection)

        self._rebuild()

    # ------------------------------------------------------------- rebuild

    def _schedule(self, *_args) -> None:
        self._pending.start()  # restart: rebuild after the events stop coming

    def _on_node_ran(self, *_args) -> None:
        # timings only matter to the runtime ordering; leave the tree alone
        # otherwise so a big run does not thrash it
        if self._sort == "runtime":
            self._schedule()

    def _on_sort_changed(self) -> None:
        self._sort = self._combo.currentData()
        self._rebuild()

    def _rebuild(self) -> None:
        self._pending.stop()
        top_nodes, top_frames, tree = self._scene.canvas_outline()
        if not top_nodes and not top_frames and not tree:
            self._stack.setCurrentIndex(1)
            self._tree.clear()
            return
        self._stack.setCurrentIndex(0)

        # frame runtimes feed the runtime ordering, so every level can be
        # sorted before its rows are built
        self._runtime_cache: dict = {}
        for frame_id in tree:
            self._frame_runtime(frame_id, tree)

        self._tree.blockSignals(True)
        self._tree.clear()
        for kind, ident in self._ordered(
                [("node", n) for n in top_nodes]
                + [("frame", f) for f in top_frames]):
            if kind == "node":
                self._tree.addTopLevelItem(self._node_item(ident))
            else:
                self._tree.addTopLevelItem(self._frame_item(ident, tree))
        # expansion has to be set after the items are in the tree — a detached
        # QTreeWidgetItem does not keep it
        self._apply_expansion(self._tree.invisibleRootItem())
        self._tree.blockSignals(False)
        self._sync_selection()

    def _apply_expansion(self, parent: QTreeWidgetItem) -> None:
        for i in range(parent.childCount()):
            child = parent.child(i)
            data = child.data(0, _ROLE)
            if data and data[0] == "frame":
                child.setExpanded(data[1] not in self._collapsed)
            self._apply_expansion(child)

    def _frame_item(self, frame_id: str, tree: dict) -> QTreeWidgetItem:
        frame = self._graph.frames.get(frame_id)
        title = frame.title if frame else frame_id
        folded = bool(frame and frame.collapsed)
        item = QTreeWidgetItem([title + ("  (folded)" if folded else ""), ""])
        item.setData(0, _ROLE, ("frame", frame_id))
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        if folded:
            item.setForeground(0, QBrush(QColor("#9ca3af")))

        child_nodes, child_frames = tree.get(frame_id, ([], []))
        entries = ([("node", n) for n in child_nodes]
                   + [("frame", f) for f in child_frames])
        for kind, ident in self._ordered(entries):
            if kind == "node":
                item.addChild(self._node_item(ident))
            else:
                item.addChild(self._frame_item(ident, tree))

        secs = self._frame_runtime(frame_id, tree)
        if secs > 0:
            item.setText(1, format_seconds(secs))
            item.setForeground(1, QBrush(QColor("#6b7280")))
        return item

    def _node_item(self, node_id: str) -> QTreeWidgetItem:
        node = self._graph.nodes.get(node_id)
        label = node.label if node else node_id
        item = QTreeWidgetItem([label, ""])
        item.setData(0, _ROLE, ("node", node_id))
        if node is not None:
            item.setToolTip(0, f"{node.label} — {node.spec.label}")
        secs = self._node_runtime(node_id)
        if secs > 0:
            item.setText(1, format_seconds(secs))
            item.setForeground(1, QBrush(QColor("#6b7280")))
        return item

    # -------------------------------------------------------------- sorting

    def _ordered(self, entries: list) -> list:
        return sorted(entries, key=lambda e: self._key(*e))

    def _key(self, kind: str, ident: str):
        if self._sort == "alpha":
            return (self._name(kind, ident).lower(),)
        if self._sort == "runtime":
            secs = (self._node_runtime(ident) if kind == "node"
                    else self._runtime_cache.get(ident, 0.0))
            return (-secs, self._name(kind, ident).lower())
        x, y = self._pos(kind, ident)
        return (round(y), round(x))

    def _name(self, kind: str, ident: str) -> str:
        if kind == "node":
            node = self._graph.nodes.get(ident)
            return node.label if node else ident
        frame = self._graph.frames.get(ident)
        return frame.title if frame else ident

    def _pos(self, kind: str, ident: str) -> tuple:
        if kind == "node":
            node = self._graph.nodes.get(ident)
            return node.pos if node else (0.0, 0.0)
        frame = self._graph.frames.get(ident)
        return (frame.rect[0], frame.rect[1]) if frame else (0.0, 0.0)

    def _node_runtime(self, node_id: str) -> float:
        entry = self._engine.cache.get(node_id)
        return entry.wall_time if entry is not None else 0.0

    def _frame_runtime(self, frame_id: str, tree: dict) -> float:
        if frame_id in self._runtime_cache:
            return self._runtime_cache[frame_id]
        self._runtime_cache[frame_id] = 0.0  # break any stale membership cycle
        nodes, frames = tree.get(frame_id, ([], []))
        total = sum(self._node_runtime(n) for n in nodes)
        total += sum(self._frame_runtime(f, tree) for f in frames)
        self._runtime_cache[frame_id] = total
        return total

    # -------------------------------------------------------------- events

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, _ROLE)
        if data:
            self.navigate_requested.emit(*data)

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, _ROLE)
        if data and data[0] == "frame":
            self._collapsed.discard(data[1])

    def _on_item_collapsed(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, _ROLE)
        if data and data[0] == "frame":
            self._collapsed.add(data[1])

    def _sync_selection(self) -> None:
        """Mirror the canvas selection onto the tree — never the other way, and
        never a jump: the row just highlights so the reader can see where they
        are in the layout."""
        if self._syncing or self._stack.currentIndex() != 0:
            return
        try:
            selected = {("node", i.node.id)
                        for i in self._scene.selected_node_items()}
            selected |= {("frame", i.frame.id)
                         for i in self._scene.selected_frame_items()}
        except RuntimeError:
            return  # scene torn down under us (test teardown, window close)
        self._syncing = True
        try:
            self._tree.clearSelection()
            match: Optional[QTreeWidgetItem] = None
            it = self._tree.invisibleRootItem()
            stack = [it.child(i) for i in range(it.childCount())]
            while stack:
                node = stack.pop()
                if node is None:
                    continue
                if node.data(0, _ROLE) in selected:
                    node.setSelected(True)
                    match = match or node
                stack.extend(node.child(i) for i in range(node.childCount()))
            if match is not None:
                self._tree.scrollToItem(match)
        finally:
            self._syncing = False
