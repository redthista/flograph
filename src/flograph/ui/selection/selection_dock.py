"""The Selection pane: every shape and frame on the canvas, listed top-to-bottom
in front-to-back drawing order — the way Power BI's Selection pane reads.

It answers two questions the canvas itself answers slowly once a flow is busy:
*what is stacked on top of what*, and *what have I hidden*. Rows carry an eye
toggle (shapes only — hiding a frame's contents is a separate question) and
can be dragged to restack. A shape dragged across the **Nodes & wires**
divider swaps sides: above it the shape draws over the nodes, below it behind
them.

Nodes are deliberately not in this list. They have their own structural view
in the Navigator; here they are just the reference line the shapes sit around.

Rebuilt from the graph on any change that could move a row, coalesced to one
pass per event-loop turn, exactly as the Navigator does it. The graph is the
authority: a drag pushes commands and the rebuild that follows redraws the
list from what actually landed.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from flograph.core import Graph

from ..canvas.shape_item import KIND_LABELS

_ROLE = Qt.UserRole            # (kind, id) on a real row; ("divider", name) else
_DIVIDER_NODES = ("divider", "nodes")
_DIVIDER_FRAMES = ("divider", "frames")


class SelectionPanel(QWidget):
    """List of the canvas's shapes and frames. Emits
    `navigate_requested(kind, id)` — kind is "shape" or "frame" — when a row
    is clicked."""

    navigate_requested = Signal(str, str)

    def __init__(self, graph: Graph, scene, parent=None) -> None:
        super().__init__(parent)
        self._graph = graph
        self._scene = scene
        self._syncing = False

        self._tree = _ReorderTree(self)
        self._tree.setColumnCount(2)
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.setDragDropMode(QAbstractItemView.InternalMove)
        self._tree.setColumnWidth(1, 24)
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setMinimumSectionSize(22)
        self._tree.itemClicked.connect(self._on_clicked)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.rows_reordered.connect(self._commit_reorder)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.addWidget(self._tree)

        self._pending = QTimer(self)
        self._pending.setSingleShot(True)
        self._pending.setInterval(90)
        self._pending.timeout.connect(self._rebuild)

        ev = graph.events
        for event in (ev.shape_added, ev.shape_removed, ev.shape_changed,
                      ev.frame_added, ev.frame_removed, ev.frame_changed,
                      ev.restacked, ev.label_changed):
            event.connect(self._schedule)
        scene.selectionChanged.connect(self._sync_selection)
        self._rebuild()

    # ------------------------------------------------------------- rebuild

    def _schedule(self, *_args) -> None:
        self._pending.start()

    def _front_first(self, kind: str) -> list[str]:
        return list(reversed(self._graph.stacking_order(kind)))

    def _rebuild(self) -> None:
        self._pending.stop()
        shapes = self._graph.shapes
        front = [s for s in self._front_first("shape")
                 if not shapes[s].behind]
        back = [s for s in self._front_first("shape") if shapes[s].behind]
        frames = self._front_first("frame")

        self._tree.blockSignals(True)
        self._tree.clear()
        for sid in front:
            self._tree.addTopLevelItem(self._shape_row(sid))
        self._tree.addTopLevelItem(self._divider("Nodes & wires",
                                                 _DIVIDER_NODES))
        for sid in back:
            self._tree.addTopLevelItem(self._shape_row(sid))
        if frames:
            self._tree.addTopLevelItem(self._divider("Frames",
                                                     _DIVIDER_FRAMES))
            for fid in frames:
                self._tree.addTopLevelItem(self._frame_row(fid))
        self._tree.blockSignals(False)
        self._sync_selection()

    def _shape_row(self, shape_id: str) -> QTreeWidgetItem:
        shape = self._graph.shapes[shape_id]
        name = shape.text.splitlines()[0].strip() if shape.text else ""
        label = name or KIND_LABELS.get(shape.kind, shape.kind.title())
        item = QTreeWidgetItem([label, ""])
        item.setData(0, _ROLE, ("shape", shape_id))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable
                      | Qt.ItemIsDragEnabled | Qt.ItemIsUserCheckable)
        item.setCheckState(1, Qt.Unchecked if shape.hidden else Qt.Checked)
        item.setToolTip(1, "Hidden" if shape.hidden else "Visible")
        if shape.hidden:
            item.setForeground(0, QBrush(QColor("#6b7280")))
        return item

    def _frame_row(self, frame_id: str) -> QTreeWidgetItem:
        frame = self._graph.frames[frame_id]
        title = frame.title + ("  (folded)" if frame.collapsed else "")
        item = QTreeWidgetItem([title, ""])
        item.setData(0, _ROLE, ("frame", frame_id))
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable
                      | Qt.ItemIsDragEnabled)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        return item

    def _divider(self, text: str, key) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text, ""])
        item.setData(0, _ROLE, key)
        item.setFlags(Qt.ItemIsEnabled)          # no select, no drag
        item.setForeground(0, QBrush(QColor("#6b7280")))
        font = item.font(0)
        font.setItalic(True)
        item.setFont(0, font)
        return item

    # -------------------------------------------------------------- events

    def _on_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        data = item.data(0, _ROLE)
        if not data or data[0] == "divider":
            return
        if col != 1:                       # column 1 is the eye; don't navigate
            self.navigate_requested.emit(*data)

    def _on_item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        if col != 1:
            return
        data = item.data(0, _ROLE)
        if not data or data[0] != "shape":
            return
        shape = self._graph.shapes.get(data[1])
        if shape is None:
            return
        want_hidden = item.checkState(1) == Qt.Unchecked
        if want_hidden != shape.hidden:
            self._scene.push_shape_style(
                data[1], label="hide shape" if want_hidden else "show shape",
                hidden=want_hidden)

    def _sync_selection(self) -> None:
        if self._syncing:
            return
        try:
            picked = {("shape", i.shape_model.id)
                      for i in self._scene.selected_shape_items()}
            picked |= {("frame", i.frame.id)
                       for i in self._scene.selected_frame_items()}
        except RuntimeError:
            return
        self._syncing = True
        try:
            self._tree.clearSelection()
            for i in range(self._tree.topLevelItemCount()):
                row = self._tree.topLevelItem(i)
                if row.data(0, _ROLE) in picked:
                    row.setSelected(True)
        finally:
            self._syncing = False

    # ----------------------------------------------------------- reordering

    def _commit_reorder(self) -> None:
        """Read the list back after an internal drag and push whatever
        restack / behind-flip it implies, in one undo step."""
        rows = [self._tree.topLevelItem(i).data(0, _ROLE)
                for i in range(self._tree.topLevelItemCount())]
        section = "front"
        front, back, frames = [], [], []
        for data in rows:
            if data == _DIVIDER_NODES:
                section = "back"
            elif data == _DIVIDER_FRAMES:
                section = "frames"
            elif data and data[0] == "shape":
                (front if section == "front" else back).append(data[1])
            elif data and data[0] == "frame":
                frames.append(data[1])

        shapes = self._graph.shapes
        # back-to-front: behind shapes first (lower z), then the front ones
        new_shape_order = list(reversed(back)) + list(reversed(front))
        new_frame_order = list(reversed(frames))
        behind_flips = {sid: True for sid in back if not shapes[sid].behind}
        behind_flips.update({sid: False for sid in front if shapes[sid].behind})

        cur_shape = self._graph.stacking_order("shape")
        cur_frame = self._graph.stacking_order("frame")
        if (new_shape_order == cur_shape and new_frame_order == cur_frame
                and not behind_flips):
            return

        from ..commands import RestackCommand, UpdateShapeCommand
        self._scene.undo_stack.beginMacro("reorder canvas")
        for sid, value in behind_flips.items():
            self._scene.undo_stack.push(UpdateShapeCommand(
                self._graph, sid, label="restack shape", behind=value))
        if new_shape_order != cur_shape:
            self._scene.undo_stack.push(RestackCommand(
                self._graph, "shape", new_shape_order, text="reorder canvas"))
        if new_frame_order != cur_frame:
            self._scene.undo_stack.push(RestackCommand(
                self._graph, "frame", new_frame_order, text="reorder canvas"))
        self._scene.undo_stack.endMacro()
        self._rebuild()


class _ReorderTree(QTreeWidget):
    """A flat tree that reports when an internal drag has rearranged its
    top-level rows. Drops *onto* a row are refused — the list never nests."""

    rows_reordered = Signal()

    def dropEvent(self, event) -> None:
        if self.dropIndicatorPosition() == QAbstractItemView.OnItem:
            event.ignore()
            return
        super().dropEvent(event)
        # after Qt has moved the rows; a single-shot so the model has settled
        QTimer.singleShot(0, self.rows_reordered.emit)
