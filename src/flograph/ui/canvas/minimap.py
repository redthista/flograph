"""Minimap: a painted overlay in the view's corner — node rects plus the
current viewport, click/drag to navigate. No second QGraphicsView."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from flograph.core.node import NodeStatus

from .. import theme
from .node_item import DEACTIVATED_OPACITY

WIDTH, HEIGHT = 200, 140
MARGIN = 12
REFRESH_MS = 200


def _state_color(item) -> QColor:
    """What one node reads as at four pixels across.

    The order is the point. An error outranks everything — it is the one
    thing worth crossing the map for. A frozen node comes next, *above* its
    own run status, because that status is stale by definition: the node was
    skipped, so it still shows whatever it last finished as, and a green
    "done" is precisely the wrong thing to say about a node nobody is
    refreshing. Only then does the live status apply, then the user's own
    colour, which is organisation rather than state and yields to both.
    """
    node = item.node
    if node.status == NodeStatus.ERROR:
        return theme.status_color(node.status)
    if node.frozen:
        return theme.PIN_STALE if item.pin_stale else theme.PIN_HELD
    if node.status != NodeStatus.IDLE:
        return theme.status_color(node.status)
    if node.color:
        # same tint as the card header, so a node reads as the same colour
        # in the minimap as it does on the canvas
        return theme.tint(theme.NODE_HEADER, node.color, theme.TINT_STRONG)
    return theme.NODE_HEADER.lighter(150)


def _node_brush(item) -> QColor:
    """The fill: the node's state colour, faded if it is deactivated.

    Fading rather than recolouring is deliberate, and it is what the canvas
    already does with opacity. A deactivated node has not become a different
    kind of thing — it is the same node, out of play — and spending another
    hue on it would put it in competition with the colours that do mean
    something is happening.
    """
    colour = QColor(_state_color(item))
    if not item.node.active:
        colour.setAlphaF(DEACTIVATED_OPACITY)
    return colour


def _node_pen(item):
    """The border: an outline on a locked node, nothing otherwise.

    Locking says nothing about the run — it is about editing — so it must
    not take the one channel that does. Putting it on the border instead
    keeps everything legible at once: a node can be locked *and* frozen
    *and* failing, and the map can say all three.
    """
    if item.node.locked:
        return QPen(theme.NODE_TEXT, 1)
    return Qt.NoPen


class Minimap(QWidget):
    def __init__(self, view) -> None:
        super().__init__(view)
        self._view = view
        self.setFixedSize(WIDTH, HEIGHT)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    # ------------------------------------------------------------- mapping

    def _content_rect(self) -> QRectF:
        scene = self._view.scene()
        rect = QRectF()
        for item in scene.node_items.values():
            rect = rect.united(item.sceneBoundingRect())
        for item in scene.frame_items.values():
            rect = rect.united(item.scene_rect())
        viewport = self._view.mapToScene(
            self._view.viewport().rect()).boundingRect()
        rect = rect.united(viewport)
        if rect.isEmpty():
            rect = QRectF(-500, -400, 1000, 800)
        pad_x = rect.width() * 0.08
        pad_y = rect.height() * 0.08
        return rect.adjusted(-pad_x, -pad_y, pad_x, pad_y)

    def _scale(self, content: QRectF) -> float:
        return min(WIDTH / content.width(), HEIGHT / content.height())

    def _to_mini(self, point: QPointF, content: QRectF, s: float) -> QPointF:
        offset_x = (WIDTH - content.width() * s) / 2
        offset_y = (HEIGHT - content.height() * s) / 2
        return QPointF((point.x() - content.x()) * s + offset_x,
                       (point.y() - content.y()) * s + offset_y)

    def _to_scene(self, point: QPointF) -> QPointF:
        content = self._content_rect()
        s = self._scale(content)
        offset_x = (WIDTH - content.width() * s) / 2
        offset_y = (HEIGHT - content.height() * s) / 2
        return QPointF((point.x() - offset_x) / s + content.x(),
                       (point.y() - offset_y) / s + content.y())

    # ------------------------------------------------------------- painting

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg = QColor(theme.CANVAS_BG)
        bg.setAlphaF(0.85)
        painter.setBrush(bg)
        painter.setPen(QPen(theme.GRID_COARSE, 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 4, 4)

        scene = self._view.scene()
        content = self._content_rect()
        s = self._scale(content)

        for item in scene.frame_items.values():
            rect = item.scene_rect()
            top_left = self._to_mini(rect.topLeft(), content, s)
            color = QColor(item.frame.color)
            color.setAlphaF(0.35)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRect(QRectF(top_left,
                                    rect.size() * s).toRect())

        for item in scene.node_items.values():
            rect = item.sceneBoundingRect()
            top_left = self._to_mini(rect.topLeft(), content, s)
            painter.setPen(_node_pen(item))
            painter.setBrush(_node_brush(item))
            painter.drawRect(QRectF(top_left, rect.size() * s).toRect())

        viewport = self._view.mapToScene(
            self._view.viewport().rect()).boundingRect()
        top_left = self._to_mini(viewport.topLeft(), content, s)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(theme.SELECTION_OUTLINE, 1.5))
        painter.drawRect(QRectF(top_left, viewport.size() * s))

    # ---------------------------------------------------------- interaction

    def mousePressEvent(self, event) -> None:
        self._view.centerOn(self._to_scene(event.position()))
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self._view.centerOn(self._to_scene(event.position()))
            event.accept()

    def reposition(self) -> None:
        self.move(self._view.viewport().width() - WIDTH - MARGIN, MARGIN)
