"""Minimap: a painted overlay in the view's corner — node rects plus the
current viewport, click/drag to navigate. No second QGraphicsView."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
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
    if node.bypassed:
        # like a pin, its "done" says nothing about the node's own work
        return theme.BYPASS
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
    """Paints from a snapshot of the scene, not the scene.

    The map is a child of the view, so every frame of a pan or a drag
    repaints it — and it used to walk every node twice to do so, which on a
    big flow was most of each frame (0.1.25: 50-73% of a pan frame). Now a
    paint draws the last snapshot plus the viewport box: O(1) whatever the
    node count. The snapshot is retaken when the graph says something the
    map shows has changed — a node added, moved, resized, recoloured, run —
    once things settle for SETTLE_MS, and at least every MAX_WAIT_MS while
    they keep changing, so a running flow's colours still move on the map.

    Not QGraphicsScene.changed, which would be the obvious hook: connecting
    anything to it makes Qt stop sending item updates straight to the views
    and repaint whole changed regions instead — slower painting everywhere,
    to save time in the corner.
    """

    #: what the map shows changes with these graph events
    WATCHED_EVENTS = (
        "node_added", "node_removed", "node_moved", "param_changed",
        "label_changed", "active_changed", "locked_changed",
        "frozen_changed", "bypassed_changed", "color_changed",
        "compact_view_changed", "preview_enabled_changed",
        "ports_collapsed_changed", "status_changed", "dirty_changed",
        "item_canvas_changed", "frame_added", "frame_removed",
        "frame_changed")

    #: quiet time after a change before the snapshot is retaken
    SETTLE_MS = REFRESH_MS
    #: the longest a busy scene (a drag, a run) waits for a fresh map
    MAX_WAIT_MS = 1000

    def __init__(self, view) -> None:
        super().__init__(view)
        self._view = view
        self.setFixedSize(WIDTH, HEIGHT)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        # (rect, brush, pen) per frame and node, in scene coordinates
        self._frames: list = []
        self._nodes: list = []
        self._items_rect = QRectF()
        self._stale = True
        self._watched = None
        self._stale_since = 0.0
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(self.SETTLE_MS)
        self._settle.timeout.connect(self._retake)
        #: how many snapshots were taken — tests count these, not ms
        self.snapshots = 0

    # ------------------------------------------------------------ snapshot

    def _watch_scene(self):
        scene = self._view.scene()
        graph = getattr(scene, "graph", None)
        if graph is not self._watched:
            for name in self.WATCHED_EVENTS:
                if self._watched is not None:
                    getattr(self._watched.events, name).disconnect(
                        self.mark_stale)
                if graph is not None and hasattr(graph.events, name):
                    getattr(graph.events, name).connect(self.mark_stale)
            self._watched = graph
            self._stale = True
        return scene

    def mark_stale(self, *_args) -> None:
        """Something in the scene changed: retake the snapshot once it
        settles, or after MAX_WAIT_MS if it never does."""
        import time
        now = time.monotonic()
        if not self._stale:
            self._stale = True
            self._stale_since = now
        if not self.isVisible():
            return      # retaken on the next paint, if there ever is one
        if (now - self._stale_since) * 1000 >= self.MAX_WAIT_MS:
            if not self._settle.isActive():
                self._settle.start(0)
            return
        self._settle.start(self.SETTLE_MS)

    def _retake(self) -> None:
        if self._stale and self.isVisible():
            self._snapshot()
            self.update()

    def _snapshot(self) -> None:
        scene = self._watch_scene()
        self._stale = False
        self.snapshots += 1
        frames, nodes = [], []
        rect = QRectF()
        if scene is not None:
            # hidden items are inside a collapsed frame; the map shows the
            # canvas as it looks, and their region is represented by that
            # frame's box. display_rect, not scene_rect: a collapsed frame
            # keeps its full region in the model, but here it is the small box
            for item in scene.frame_items.values():
                if item.isVisible():
                    box = item.display_rect()
                    color = QColor(item.frame.color)
                    color.setAlphaF(0.35)
                    frames.append((box, color))
                    rect = rect.united(box)
            for item in scene.node_items.values():
                if item.isVisible():
                    box = item.sceneBoundingRect()
                    nodes.append((box, _node_brush(item), _node_pen(item)))
                    rect = rect.united(box)
        self._frames, self._nodes, self._items_rect = frames, nodes, rect

    # ------------------------------------------------------------- mapping

    def _content_rect(self) -> QRectF:
        # Only a map with no snapshot yet takes one here. A stale one is
        # still drawn: a paint mid-drag retaking it would put the whole
        # walk back into every frame — the timer retakes it instead.
        if (self.snapshots == 0 or self._watched
                is not getattr(self._view.scene(), "graph", None)):
            self._snapshot()
        viewport = self._view.mapToScene(
            self._view.viewport().rect()).boundingRect()
        rect = self._items_rect.united(viewport)
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

    def _scene_picture(self, content: QRectF, s: float) -> QPixmap:
        """The frames and nodes drawn at this mapping, kept until either the
        snapshot or the mapping changes — a pan inside the flow keeps both."""
        key = (self.snapshots, content.x(), content.y(), content.width(),
               content.height(), self.devicePixelRatioF())
        if getattr(self, "_picture_key", None) == key:
            return self._picture
        ratio = self.devicePixelRatioF()
        picture = QPixmap(int(WIDTH * ratio), int(HEIGHT * ratio))
        picture.setDevicePixelRatio(ratio)
        picture.fill(Qt.transparent)
        painter = QPainter(picture)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        for rect, color in self._frames:
            top_left = self._to_mini(rect.topLeft(), content, s)
            painter.setBrush(color)
            painter.drawRect(QRectF(top_left, rect.size() * s).toRect())
        for rect, brush, pen in self._nodes:
            top_left = self._to_mini(rect.topLeft(), content, s)
            painter.setPen(pen)
            painter.setBrush(brush)
            painter.drawRect(QRectF(top_left, rect.size() * s).toRect())
        painter.end()
        self._picture, self._picture_key = picture, key
        return picture

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._watch_scene()
        if self._stale:
            self._settle.start(0)   # changed while hidden

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        # a theme switch: the snapshot holds colours, take them again
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.PaletteChange, QEvent.StyleChange):
            self.mark_stale()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bg = QColor(theme.CANVAS_BG)
        bg.setAlphaF(0.85)
        painter.setBrush(bg)
        painter.setPen(QPen(theme.GRID_COARSE, 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 4, 4)

        content = self._content_rect()
        s = self._scale(content)
        painter.drawPixmap(0, 0, self._scene_picture(content, s))

        viewport = self._view.mapToScene(
            self._view.viewport().rect()).boundingRect()
        top_left = self._to_mini(viewport.topLeft(), content, s)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(theme.SELECTION_OUTLINE, 1.5))
        painter.drawRect(QRectF(top_left, viewport.size() * s))

    # ---------------------------------------------------------- interaction

    def mousePressEvent(self, event) -> None:
        self._view.center_on_scene(self._to_scene(event.position()))
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton:
            self._view.center_on_scene(self._to_scene(event.position()))
            event.accept()

    def reposition(self) -> None:
        self.move(self._view.viewport().width() - WIDTH - MARGIN, MARGIN)
