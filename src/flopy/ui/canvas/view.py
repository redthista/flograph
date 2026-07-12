"""NodeGraphView: the modeling canvas — ZoomPanGraphicsView plus node
drag & drop, the Tab palette, node keyboard shortcuts, minimap, and the
node context menu."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QKeyEvent

from .base_view import ZoomPanGraphicsView
from .scene import NodeGraphScene


class NodeGraphView(ZoomPanGraphicsView):
    add_node_requested = Signal(QPointF, QPoint)   # scene pos, global pos
    palette_requested = Signal(QPointF, QPoint)    # scene pos, global pos
    node_dropped = Signal(str, QPointF)            # type_id, scene pos
    node_context_requested = Signal(str, QPoint)   # node_id, global pos
    frame_context_requested = Signal(str, QPoint)  # frame_id, global pos

    def __init__(self, scene: NodeGraphScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setAcceptDrops(True)

        from .minimap import Minimap
        self.minimap = Minimap(self)
        self.minimap.show()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.minimap.reposition()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.minimap.reposition()

    # ------------------------------------------------------------ keyboard

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._proxy_widget_has_focus():
            # A note editor or table cell is focused inside an embedded
            # widget — let it handle keys (backspace, arrows, letters)
            # instead of hijacking them as canvas shortcuts.
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key_Tab:
            cursor_pos = self.mapFromGlobal(self.cursor().pos())
            if not self.viewport().rect().contains(cursor_pos):
                cursor_pos = self.viewport().rect().center()
            self.palette_requested.emit(
                self.mapToScene(cursor_pos), self.mapToGlobal(cursor_pos))
            event.accept()
            return
        if key == Qt.Key_Delete or key == Qt.Key_Backspace:
            self.scene().delete_selection()
            event.accept()
            return
        if key == Qt.Key_F:
            self.frame_content()
            event.accept()
            return
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            self._nudge_selection(key, 10.0 if not event.modifiers() & Qt.ShiftModifier else 1.0)
            event.accept()
            return
        super().keyPressEvent(event)  # space-pan lives in the base view

    def _nudge_selection(self, key, step: float) -> None:
        scene: NodeGraphScene = self.scene()
        items = scene.selected_node_items()
        if not items:
            return
        dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(key, 0.0)
        dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(key, 0.0)
        moves = {}
        for item in items:
            old = (item.pos().x(), item.pos().y())
            moves[item.node.id] = (old, (old[0] + dx, old[1] + dy))
        scene.push_move_command(moves)

    def frame_content(self) -> None:
        """F: fit the selection (or everything) in view."""
        scene: NodeGraphScene = self.scene()
        self.fit_items(scene.selected_node_items()
                       or list(scene.node_items.values()))

    # --------------------------------------------------------- context menu

    def contextMenuEvent(self, event) -> None:
        from .node_item import NodeItem, PortItem
        from .frame_item import FrameItem
        item = self.itemAt(event.pos())
        if item is None:
            self.add_node_requested.emit(
                self.mapToScene(event.pos()), event.globalPos())
            event.accept()
            return
        if isinstance(item, PortItem):
            item = item.node_item
        if isinstance(item, NodeItem):
            self.node_context_requested.emit(item.node.id, event.globalPos())
            event.accept()
            return
        if isinstance(item, FrameItem):
            self.frame_context_requested.emit(item.frame.id, event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    # ---------------------------------------------------------- drag & drop

    def dragEnterEvent(self, event) -> None:
        from .palette import NODE_TYPE_MIME
        if event.mimeData().hasFormat(NODE_TYPE_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        from .palette import NODE_TYPE_MIME
        if event.mimeData().hasFormat(NODE_TYPE_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        from .palette import NODE_TYPE_MIME
        if event.mimeData().hasFormat(NODE_TYPE_MIME):
            type_id = bytes(event.mimeData().data(NODE_TYPE_MIME)).decode()
            self.node_dropped.emit(
                type_id, self.mapToScene(event.position().toPoint()))
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
