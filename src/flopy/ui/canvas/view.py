"""NodeGraphView: infinite-feeling canvas with zoom-to-cursor, middle/space
pan, rubber-band selection, and an adaptive grid."""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QGraphicsProxyWidget, QGraphicsView

from .. import theme
from .scene import NodeGraphScene

ZOOM_MIN = 0.1
ZOOM_MAX = 4.0
GRID_FINE = 20.0
GRID_COARSE = 100.0
FINE_GRID_LOD = 0.4


class NodeGraphView(QGraphicsView):
    add_node_requested = Signal(QPointF, QPoint)   # scene pos, global pos
    palette_requested = Signal(QPointF, QPoint)    # scene pos, global pos
    node_dropped = Signal(str, QPointF)            # type_id, scene pos
    node_context_requested = Signal(str, QPoint)   # node_id, global pos

    def __init__(self, scene: NodeGraphScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setAcceptDrops(True)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self._panning = False
        self._pan_last = QPointF()
        self._space_held = False
        self.centerOn(0, 0)

        from .minimap import Minimap
        self.minimap = Minimap(self)
        self.minimap.show()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.minimap.reposition()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.minimap.reposition()

    # ----------------------------------------------------------------- zoom

    @property
    def zoom(self) -> float:
        return self.transform().m11()

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 ** (event.angleDelta().y() / 120.0)
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom * factor))
        factor = new_zoom / self.zoom
        if math.isclose(factor, 1.0):
            return
        pos = event.position().toPoint()
        before = self.mapToScene(pos)
        self.scale(factor, factor)
        after = self.mapToScene(pos)
        delta = after - before
        self.translate(delta.x(), delta.y())

    # ------------------------------------------------------------------ pan

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_last = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            delta = event.position() - self._pan_last
            self._pan_last = event.position()
            self.translate(delta.x() / self.zoom, delta.y() / self.zoom)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------ keyboard

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if isinstance(self.scene().focusItem(), QGraphicsProxyWidget):
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
        if key == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self.setDragMode(QGraphicsView.ScrollHandDrag)
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
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            self.setDragMode(QGraphicsView.RubberBandDrag)
            event.accept()
            return
        super().keyReleaseEvent(event)

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
        items = scene.selected_node_items() or list(scene.node_items.values())
        if not items:
            return
        rect = QRectF()
        for item in items:
            rect = rect.united(item.sceneBoundingRect())
        rect.adjust(-60, -60, 60, 60)
        self.fitInView(rect, Qt.KeepAspectRatio)
        if self.zoom > 1.5:  # don't over-zoom on a single node
            factor = 1.5 / self.zoom
            self.scale(factor, factor)

    # --------------------------------------------------------- context menu

    def contextMenuEvent(self, event) -> None:
        from .node_item import NodeItem, PortItem
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

    # ------------------------------------------------------------------ bg

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, theme.CANVAS_BG)
        if self.zoom >= FINE_GRID_LOD:
            self._draw_grid(painter, rect, GRID_FINE, theme.GRID_FINE)
        self._draw_grid(painter, rect, GRID_COARSE, theme.GRID_COARSE)

    @staticmethod
    def _draw_grid(painter: QPainter, rect: QRectF, step: float, color) -> None:
        painter.setPen(QPen(color, 0))
        x = math.floor(rect.left() / step) * step
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
        y = math.floor(rect.top() / step) * step
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step
