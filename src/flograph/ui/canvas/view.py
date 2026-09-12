"""NodeGraphView: the modeling canvas — ZoomPanGraphicsView plus node
drag & drop, the Tab palette, node keyboard shortcuts, minimap, and the
node context menu."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetricsF, QKeyEvent,
                           QMouseEvent, QPainter, QPainterPath, QPen,
                           QTransform)
from PySide6.QtWidgets import (QApplication, QGraphicsView, QRubberBand,
                               QToolTip)

from .. import theme
from .base_view import (ZoomPanGraphicsView, edge_scroll_delta,
                        EDGE_SCROLL_TICK_MS)
from .file_drop import resolve_dropped_path
from .scene import NodeGraphScene
from .stacking import layer_action_for

# Hold this to see every port's name. Q because the canvas has already spent
# F (frame), Tab (palette), Space (pan), Delete/Backspace and the arrows, and
# because a letter next to nothing important is cheap to hold with the left
# hand while the right one is on the mouse.
DEFAULT_REVEAL_PORTS_KEY = Qt.Key_Q

# A frame's own tab (G12): how far past the frame's edges the view may pan,
# in scene units — room to breathe at the edge, not a way back to the rest.
FENCE_PAD = 600.0
# the labels on wires leaving a fenced frame, in screen pixels
STUB_GAP = 6.0
STUB_PAD_X = 8.0
STUB_PAD_Y = 3.0
STUB_MAX_W = 200.0


@dataclass(frozen=True)
class FenceStub:
    """A wire that leaves a fenced frame, at the point it crosses the edge."""
    conn_id: str
    node_id: str        # the node at the far end, outside the frame
    text: str
    point: QPointF      # where the wire crosses the frame's edge, scene coords
    outgoing: bool      # True: the wire goes out of the frame to that node


def edge_crossing(path: QPainterPath, rect: QRectF) -> Optional[float]:
    """How far along `path` (0..1) it crosses `rect`'s edge, when exactly one
    of its ends lies inside; None when both ends are on the same side.

    A binary search on the two ends' sides: a wire that weaves out and back
    in has more than one crossing, and any of them is a fair place to say
    where it goes."""
    if path.isEmpty():
        return None
    start_in = rect.contains(path.pointAtPercent(0.0))
    if start_in == rect.contains(path.pointAtPercent(1.0)):
        return None
    lo, hi = 0.0, 1.0
    for _ in range(16):
        mid = (lo + hi) / 2
        if rect.contains(path.pointAtPercent(mid)) == start_in:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _stub_box(point: QPointF, edges: QRectF, w: float, h: float) -> QRectF:
    """A label's box, just outside whichever edge of `edges` (the frame, in
    viewport pixels) `point` is on — so it covers painted-over canvas,
    never a node inside the frame."""
    side = min((abs(point.x() - edges.left()), "left"),
               (abs(point.x() - edges.right()), "right"),
               (abs(point.y() - edges.top()), "top"),
               (abs(point.y() - edges.bottom()), "bottom"))[1]
    if side == "right":
        return QRectF(point.x() + STUB_GAP, point.y() - h / 2, w, h)
    if side == "left":
        return QRectF(point.x() - STUB_GAP - w, point.y() - h / 2, w, h)
    if side == "top":
        return QRectF(point.x() - w / 2, point.y() - STUB_GAP - h, w, h)
    return QRectF(point.x() - w / 2, point.y() + STUB_GAP, w, h)


class NodeGraphView(ZoomPanGraphicsView):
    add_node_requested = Signal(QPointF, QPoint)   # scene pos, global pos
    palette_requested = Signal(QPointF, QPoint)    # scene pos, global pos
    node_dropped = Signal(str, QPointF)            # type_id, scene pos
    frame_dropped = Signal(str, QPointF)           # component id, scene pos
    files_dropped = Signal(list, QPointF)          # local file paths, scene pos
    node_context_requested = Signal(str, QPoint)   # node_id, global pos
    frame_context_requested = Signal(str, QPoint)  # frame_id, global pos
    shape_context_requested = Signal(str, QPoint)  # shape_id, global pos
    shape_draw_requested = Signal(str, QRectF)     # kind, scene-coord rect
    # An order edge only: a data wire has never had a menu, and the one this
    # opens is about what an order edge *is*.
    order_context_requested = Signal(str, QPoint)  # conn_id, global pos
    # A frame's tab (G12): a jump aimed outside the fenced frame, which the
    # window answers by going back to the whole canvas; and a label at the
    # fence edge clicked, naming the node the wire goes to out there.
    fence_escape_requested = Signal()
    fence_node_requested = Signal(str)             # node_id

    def __init__(self, scene: NodeGraphScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setAcceptDrops(True)
        # Held-key port-name reveal. A bare key rather than a modifier: Alt
        # is the menu bar's on both Linux and Windows, so binding it here
        # means either swallowing that or having the menu bar flicker into
        # focus on every tap. The main window is the sole writer.
        self.reveal_ports_key = DEFAULT_REVEAL_PORTS_KEY
        self._reveal_held = False

        from .minimap import Minimap
        self.minimap = Minimap(self)
        self.minimap.show()

        from .node_search import NodeSearchBar
        self.search_bar = NodeSearchBar(self)
        self.search_bar.reveal_requested.connect(self.go_to_node)

        # Edge-scroll while anything is being dragged (G3): hold a wire, a
        # node or a frame against a viewport border and the canvas glides
        # that way until the destination is on screen, so wiring or placing
        # two things that are not on screen together no longer means letting
        # go, panning, and starting again.
        self._edge_timer = QTimer(self)
        self._edge_timer.setInterval(EDGE_SCROLL_TICK_MS)
        self._edge_timer.timeout.connect(self._edge_scroll_tick)
        scene.canvas_drag_changed.connect(self._set_edge_scrolling)

        # the optional shape tool rail (Settings ▸ Canvas), and draw mode
        self._shape_rail = None
        self._shape_draw_kind: "str | None" = None
        self._draw_origin: "QPoint | None" = None
        self._draw_band: "QRubberBand | None" = None

        # the frame a frame's tab fences this view to (G12), None for the
        # whole canvas; and where the last paint put the labels on wires
        # leaving it, as (viewport rect, node id, text)
        self._fence_frame: "str | None" = None
        self._stub_hits: list = []
        self._stub_cursor = False

    # ------------------------------------------------------- the fence (G12)
    #
    # A frame's tab is this same view, on this same scene, fenced to the
    # frame: everything outside it is painted over and takes no clicks, the
    # view pans no further than a margin past its edges, and each wire that
    # leaves it gets a label at the edge naming the node it goes to. One view
    # and one scene rather than a copy of either, so an edit in the tab is an
    # edit to the flow by the ordinary route, and every shortcut, menu and
    # dock that works on the canvas works there without knowing about tabs.

    @property
    def fence_frame(self) -> "str | None":
        return self._fence_frame

    def set_fence(self, frame_id: "str | None") -> None:
        """Fence the view to one frame, or (None) give it the whole canvas."""
        if frame_id != self._fence_frame:
            self._fence_frame = frame_id
            self._stub_hits = []
            self._set_stub_cursor(False)
            # the edge labels follow wires that move without the edge being
            # repainted, so a fenced view redraws whole — it only shows a
            # frame's worth of flow, which keeps that cheap
            self.setViewportUpdateMode(
                QGraphicsView.FullViewportUpdate if frame_id is not None
                else QGraphicsView.BoundingRectViewportUpdate)
        self.refresh_fence()

    def fence_rect(self) -> Optional[QRectF]:
        """The fenced frame's rectangle in scene coordinates: None when the
        view has the whole canvas, a null rect when the frame is gone."""
        if self._fence_frame is None:
            return None
        item = self.scene().frame_items.get(self._fence_frame)
        return item.scene_rect() if item is not None else QRectF()

    def refresh_fence(self) -> None:
        """Follow the frame after it moved, resized, folded, went or came
        back: the span the view can pan over is the frame plus a margin."""
        rect = self.fence_rect()
        if rect is None:
            self.setSceneRect(QRectF())     # null: follow the scene's again
        elif not rect.isNull():
            self.setSceneRect(rect.adjusted(-FENCE_PAD, -FENCE_PAD,
                                            FENCE_PAD, FENCE_PAD))
        self.viewport().update()

    def fence_contains(self, scene_pos: QPointF) -> bool:
        rect = self.fence_rect()
        return rect is None or rect.contains(scene_pos)

    def fence_holds(self, item) -> bool:
        """Whether `item` is part of what the fenced view shows: a node or a
        shape that reaches into the frame, or a frame lying within it — a
        frame around it is the rest of the flow, and selecting that from
        here would put it one Delete away without ever being seen."""
        rect = self.fence_rect()
        if rect is None:
            return True
        if rect.isNull():
            return False
        from .frame_item import FrameItem
        if isinstance(item, FrameItem):
            return rect.contains(item.scene_rect())
        return rect.intersects(item.sceneBoundingRect())

    def _escape_fence_for(self, item) -> None:
        """A jump to something outside the fenced frame leaves the frame's
        tab for the whole canvas first: landing on painted-over canvas would
        look like the jump doing nothing."""
        rect = self.fence_rect()
        if rect is not None and not rect.contains(
                item.sceneBoundingRect().center()):
            self.fence_escape_requested.emit()

    def fence_stubs(self) -> list:
        """A FenceStub for every drawn wire with one end in the fenced frame
        and the other outside it."""
        rect = self.fence_rect()
        if rect is None or rect.isNull():
            return []
        scene = self.scene()
        stubs = []
        for conn_id, item in scene.connection_items.items():
            if not item.isVisible():
                continue
            path = item.mapToScene(item.path())
            t = edge_crossing(path, rect)
            if t is None:
                continue
            conn = item.conn
            outgoing = rect.contains(path.pointAtPercent(0.0))
            far = conn.dst_node if outgoing else conn.src_node
            node = scene.graph.nodes.get(far)
            name = node.label if node is not None else far
            stubs.append(FenceStub(conn_id, far,
                                   f"→ {name}" if outgoing else f"← {name}",
                                   path.pointAtPercent(t), outgoing))
        return stubs

    def _stub_at(self, pos) -> "tuple | None":
        point = QPointF(pos)
        for hit in self._stub_hits:
            if hit[0].contains(point):
                return hit
        return None

    def _set_stub_cursor(self, on: bool) -> None:
        if on != self._stub_cursor:
            self._stub_cursor = on
            if on:
                self.viewport().setCursor(Qt.PointingHandCursor)
            else:
                self.viewport().unsetCursor()

    def _fence_blocks(self, event) -> bool:
        """A press the fence answers itself. A click on an edge label goes to
        the node it names; anything else outside the frame is swallowed —
        what is out there is painted over, so it must not be picked either.
        A middle-drag or a Space pan still pans from anywhere."""
        if (self._fence_frame is None or self._space_held
                or event.button() == Qt.MiddleButton):
            return False
        pos = event.position().toPoint()
        hit = self._stub_at(pos)
        if hit is not None:
            if event.button() == Qt.LeftButton:
                self.fence_node_requested.emit(hit[1])
            event.accept()
            return True
        if self.fence_contains(self.mapToScene(pos)):
            return False
        event.accept()
        return True

    def _drop_fenced_out_selection(self) -> None:
        """A drag-select stretched past the frame's edge must not catch what
        is painted over out there."""
        for item in self.scene().selectedItems():
            if not self.fence_holds(item):
                item.setSelected(False)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        fence = self.fence_rect()
        if fence is None:
            return
        outside = QPainterPath()
        outside.addRect(rect)
        if not fence.isNull():
            inside = QPainterPath()
            inside.addRect(fence)
            outside = outside.subtracted(inside)
        painter.fillPath(outside, theme.CANVAS_BG)
        # the labels in screen pixels, the size of the rest of the chrome
        # whatever the zoom — map labels, not scene text
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont(self.font())
        font.setPointSizeF(9.0)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        if fence.isNull():
            self._stub_hits = []
            painter.setPen(theme.NODE_SUBTEXT)
            painter.drawText(
                QRectF(self.viewport().rect()), Qt.AlignCenter | Qt.TextWordWrap,
                "The frame this tab shows has been deleted.\n"
                "Undo brings it back; right-click the tab to close it.")
            painter.restore()
            return
        edges = QRectF(self.mapFromScene(fence.topLeft()),
                       self.mapFromScene(fence.bottomRight()))
        hits = []
        for stub in self.fence_stubs():
            text = metrics.elidedText(stub.text, Qt.ElideRight, STUB_MAX_W)
            w = metrics.horizontalAdvance(text) + 2 * STUB_PAD_X
            h = metrics.height() + 2 * STUB_PAD_Y
            box = _stub_box(QPointF(self.mapFromScene(stub.point)), edges, w, h)
            # several wires leaving side by side: step each label along the
            # edge off the ones already placed, rather than stack them
            along_x = box.center().y() < edges.top() or \
                box.center().y() > edges.bottom()
            for _ in range(12):
                if not any(box.intersects(other[0]) for other in hits):
                    break
                box.translate(w + 4 if along_x else 0, 0 if along_x else h + 3)
            painter.setPen(QPen(QColor(theme.NODE_SUBTEXT), 1.0))
            painter.setBrush(theme.NODE_BODY)
            painter.drawRoundedRect(box, h / 2, h / 2)
            painter.setPen(theme.NODE_TEXT)
            painter.drawText(box, Qt.AlignCenter, text)
            hits.append((box, stub.node_id, stub.text))
        self._stub_hits = hits
        painter.restore()

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.ToolTip and self._fence_frame is not None:
            hit = self._stub_at(event.pos())
            if hit is not None:
                QToolTip.showText(
                    event.globalPos(),
                    f"{hit[2]}\nClick to go to it on the whole canvas.",
                    self.viewport())
                return True
            if not self.fence_contains(self.mapToScene(event.pos())):
                QToolTip.hideText()     # nothing out there to explain
                return True
        return super().viewportEvent(event)

    # ------------------------------------------------ each tab's own place

    def view_state(self) -> tuple:
        """Where the view stands — zoom and the scene point at its centre —
        so a tab that shares it can put it back (G12)."""
        return (self.zoom,
                self.mapToScene(self.viewport().rect().center()))

    def restore_view_state(self, state: tuple) -> None:
        zoom, center = state
        self.setTransform(QTransform.fromScale(zoom, zoom))
        self.center_on_scene(center)
        self._zoom_updated()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.minimap.reposition()
        self.search_bar.reposition()
        if self._shape_rail is not None and self._shape_rail.isVisible():
            self._shape_rail.reposition()
            self._shape_rail.raise_()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.minimap.reposition()
        self.search_bar.reposition()
        if self._shape_rail is not None and self._shape_rail.isVisible():
            self._shape_rail.reposition()
            self._shape_rail.raise_()

    # -------------------------------------------------------- shape tool rail

    def set_shape_rail_enabled(self, enabled: bool) -> None:
        if enabled and self._shape_rail is None:
            from .shape_rail import ShapeRail
            self._shape_rail = ShapeRail(self)
            self._shape_rail.tool_armed.connect(self._arm_shape_draw)
            self._shape_rail.tool_disarmed.connect(
                lambda: self._arm_shape_draw(None))
        if self._shape_rail is not None:
            self._shape_rail.setVisible(enabled)
            if enabled:
                # created after the viewport, so it stacks below it until
                # lifted — same reason a late-added overlay needs raise_()
                self._shape_rail.reposition()
                self._shape_rail.raise_()
        if not enabled:
            self._arm_shape_draw(None)

    def _arm_shape_draw(self, kind: "str | None") -> None:
        self._shape_draw_kind = kind
        self.viewport().setCursor(Qt.CrossCursor if kind else Qt.ArrowCursor)
        if kind is None:
            self._draw_origin = None
            if self._draw_band is not None:
                self._draw_band.hide()
            if self._shape_rail is not None:
                self._shape_rail.clear_selection()

    def _band(self) -> QRubberBand:
        if self._draw_band is None or self._draw_band.parent() is not self.viewport():
            self._draw_band = QRubberBand(QRubberBand.Rectangle, self.viewport())
        return self._draw_band

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._fence_blocks(event):
            return
        if (self._shape_draw_kind is not None
                and event.button() == Qt.LeftButton):
            self._draw_origin = event.position().toPoint()
            band = self._band()
            band.setGeometry(QRect(self._draw_origin, self._draw_origin))
            band.show()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._draw_origin is not None:
            self._band().setGeometry(
                QRect(self._draw_origin, event.position().toPoint()).normalized())
            event.accept()
            return
        if self._fence_frame is not None and not event.buttons():
            self._set_stub_cursor(
                self._stub_at(event.position().toPoint()) is not None)
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._fence_blocks(event):
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._draw_origin is not None and event.button() == Qt.LeftButton:
            origin, self._draw_origin = self._draw_origin, None
            self._band().hide()
            end = event.position().toPoint()
            kind = self._shape_draw_kind
            a = self.mapToScene(origin)
            b = self.mapToScene(end)
            rect = QRectF(a, b).normalized()
            if rect.width() < 6 and rect.height() < 6:
                # a click, not a drag — a default-sized shape at the point
                w, h = (190.0, 90.0) if kind in ("line", "arrow") else (
                    150.0, 46.0) if kind == "text" else (170.0, 110.0)
                rect = QRectF(a.x() - w / 2, a.y() - h / 2, w, h)
            self.shape_draw_requested.emit(kind, rect)
            self._arm_shape_draw(None)     # one shape per pick; re-click to repeat
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self._fence_frame is not None and event.button() == Qt.LeftButton:
            self._drop_fenced_out_selection()

    # ------------------------------------------------------------ edge scroll

    def _set_edge_scrolling(self, active: bool) -> None:
        if active:
            self._edge_timer.start()
        else:
            self._edge_timer.stop()

    def _edge_scroll_tick(self) -> None:
        scene = self.scene()
        if scene is None or not scene.canvas_drag_active:
            # a belt for the signal being missed (scene swapped mid-drag)
            self._edge_timer.stop()
            return
        if self._panning:
            # a middle-drag pan is its own way of reaching the edge; it must
            # never also trigger the drag-a-thing-to-the-border scroll, even
            # if some stale drag state left the timer running
            return
        self.edge_scroll_at(QCursor.pos())

    def edge_scroll_at(self, global_pos: QPoint) -> None:
        """One edge-scroll step as if the cursor were at `global_pos`.

        Split from the timer tick so tests can drive it without moving the
        real cursor. Scrolling alone would strand what is being dragged:
        a pan changes which scene point the cursor means, so each branch
        re-aims at the hand — the wire directly, and a dragged selection by
        feeding the view a synthetic mouse move (see _ride_selection)."""
        viewport = self.viewport()
        cursor = viewport.mapFromGlobal(global_pos)
        delta = edge_scroll_delta(viewport.rect(), cursor)
        if delta.isNull():
            return
        self.scroll_by(delta.x(), delta.y())
        scene = self.scene()
        if scene.wire_drag_active:
            scene.update_wire_drag(self.mapToScene(cursor))
        elif scene.group_drag_active:
            self._ride_selection(cursor)

    def _ride_selection(self, cursor: QPoint) -> None:
        """Keep a dragged selection under the hand after an edge pan.

        Qt moves a movable item to *press position + total cursor travel*,
        recomputed from its press anchor on every real move — so panning
        underneath and nudging the items ourselves would be clobbered (and
        the selection snap back) by the next mouse move. A synthetic move
        through the ordinary event path instead lets Qt do the arithmetic
        with post-pan coordinates: the selection lands where it would have
        had the mouse really carried it there, snapping, carried contents,
        group moves and all."""
        event = QMouseEvent(QEvent.MouseMove,
                            QPointF(cursor), self.mapToGlobal(cursor),
                            Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(self.viewport(), event)

    # -------------------------------------------------------------- find/goto

    def open_search(self) -> None:
        """Ctrl+F, or Edit > Find Node…"""
        self.search_bar.open_bar()

    def go_to_node(self, node_id: str) -> bool:
        """Select one node and bring the view to it.

        Zoomed far out the centring alone lands on a flattened smudge (the
        canvas drops node detail below its LOD threshold), so a jump from
        further out than MIN_REVEAL_ZOOM zooms back in to something
        readable. Closer in, the zoom is left alone — the user chose it.
        """
        from .node_search import MIN_REVEAL_ZOOM, REVEAL_ZOOM
        scene: NodeGraphScene = self.scene()
        item = scene.node_items.get(node_id)
        if item is None:
            return False
        if not item.isVisible():
            # Search resolves against the graph, so a node folded inside a
            # collapsed frame is findable — but centring on it would park the
            # view on empty canvas with nothing selected (Qt ignores
            # setSelected on a hidden item). Show the box holding it instead.
            owner = scene._owner_of(node_id)
            frame_item = scene.frame_items.get(owner) if owner else None
            if frame_item is not None:
                item = frame_item
        self._escape_fence_for(item)
        scene.clearSelection()
        item.setSelected(True)
        if self.zoom < MIN_REVEAL_ZOOM:
            self.set_zoom(REVEAL_ZOOM)
        self.center_on_scene(item)
        return True

    def go_to_frame(self, frame_id: str) -> bool:
        """Select one frame and bring the view to it — the Navigator's jump
        for a frame row, and for a node that is folded away inside one."""
        from .node_search import MIN_REVEAL_ZOOM, REVEAL_ZOOM
        scene: NodeGraphScene = self.scene()
        item = scene.frame_items.get(frame_id)
        if item is None:
            return False
        self._escape_fence_for(item)
        scene.clearSelection()
        item.setSelected(True)
        if self.zoom < MIN_REVEAL_ZOOM:
            self.set_zoom(REVEAL_ZOOM)
        self.center_on_scene(item)
        return True

    def go_to_shape(self, shape_id: str) -> bool:
        """Select one shape and bring the view to it — the Selection pane's
        jump for a shape row. A hidden shape only selects; there is nothing
        to centre on."""
        from .node_search import MIN_REVEAL_ZOOM, REVEAL_ZOOM
        scene: NodeGraphScene = self.scene()
        item = scene.shape_items.get(shape_id)
        if item is None:
            return False
        scene.clearSelection()
        if not item.isVisible():
            return True
        self._escape_fence_for(item)
        item.setSelected(True)
        if self.zoom < MIN_REVEAL_ZOOM:
            self.set_zoom(REVEAL_ZOOM)
        self.center_on_scene(item)
        return True

    # ------------------------------------------------------------ keyboard

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._proxy_widget_has_focus():
            # A note editor or table cell is focused inside an embedded
            # widget — let it handle keys (backspace, arrows, letters)
            # instead of hijacking them as canvas shortcuts.
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key_Escape and self._shape_draw_kind is not None:
            self._arm_shape_draw(None)
            event.accept()
            return
        # Before everything else, and only on a bare press: holding it with a
        # modifier down is somebody reaching for a different shortcut.
        # isAutoRepeat is mandatory — X11 and Wayland synthesise release/press
        # pairs while a key is held, so without it a hold reads as a stutter.
        if (key == self.reveal_ports_key and not event.isAutoRepeat()
                and not event.modifiers()):
            self._set_reveal_held(True)
            event.accept()
            return
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
        action = layer_action_for(event)
        if action is not None and self.scene().restack_selection(action):
            event.accept()
            return
        super().keyPressEvent(event)  # space-pan lives in the base view

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == self.reveal_ports_key and not event.isAutoRepeat():
            self._set_reveal_held(False)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _set_reveal_held(self, held: bool) -> None:
        if held == self._reveal_held:
            return
        self._reveal_held = held
        self.scene().set_revealing_port_labels(held)

    def set_reveal_ports_key(self, key: int) -> None:
        """Rebind the hold-to-reveal key. Ends any reveal in progress, since
        the release of the old key will never be recognised."""
        self._set_reveal_held(False)
        self.reveal_ports_key = key

    # The key-release that ends a reveal can be swallowed outright — a popup
    # takes focus, the pointer leaves, the window deactivates with the key
    # still down — and the names would then stay up with nothing holding
    # them. Same three belts space-pan wears, for the same reason.

    def focusOutEvent(self, event) -> None:
        self._set_reveal_held(False)
        super().focusOutEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_reveal_held(False)
        super().leaveEvent(event)

    def changeEvent(self, event) -> None:
        if (event.type() == QEvent.ActivationChange
                and not self.isActiveWindow()):
            self._set_reveal_held(False)
        super().changeEvent(event)

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
        """F: fit the selection (or everything) in view.

        Everything *visible*: nodes folded inside a collapsed frame would
        otherwise pull the fit out over a region showing nothing. Frames
        count too, or a canvas holding only collapsed ones fits to nothing.
        """
        scene: NodeGraphScene = self.scene()
        selected = scene.selected_node_items()
        if selected:
            self.fit_items(selected)
            return
        if self._fence_frame is not None:
            # a frame's tab: "everything" is the frame
            item = scene.frame_items.get(self._fence_frame)
            if item is not None:
                self.fit_items([item])
            return
        self.fit_items([item for item in (*scene.node_items.values(),
                                          *scene.frame_items.values())
                        if item.isVisible()])

    # --------------------------------------------------------- context menu

    def contextMenuEvent(self, event) -> None:
        from .node_item import NodeItem, PortItem
        from .frame_item import FrameItem
        from .connection_item import ConnectionItem
        from .shape_item import ShapeItem
        from .. import menu_guard
        if menu_guard.stray(event):
            # the tail of a menu that just closed over this view (the page
            # bar's), at a point that is inside the viewport — so only the
            # timing tells it from a right-click here. See ui/menu_guard.
            event.accept()
            return
        if (event.spontaneous()
                and event.reason() == type(event).Reason.Mouse
                and not self.viewport().rect().contains(event.pos())):
            # a right-click elsewhere (a page tab's), delivered here because
            # the canvas had the focus — see the same guard on DashboardView
            event.accept()
            return
        if self._fence_frame is not None and (
                self._stub_at(event.pos()) is not None
                or not self.fence_contains(self.mapToScene(event.pos()))):
            event.accept()      # painted-over canvas has no menu
            return
        item = self.itemAt(event.pos())
        scene_pos = self.mapToScene(event.pos())
        if item is None:
            self.add_node_requested.emit(scene_pos, event.globalPos())
            event.accept()
            return
        if isinstance(item, ShapeItem):
            self.shape_context_requested.emit(item.shape_model.id,
                                              event.globalPos())
            event.accept()
            return
        if isinstance(item, PortItem):
            item = item.node_item
        if isinstance(item, NodeItem):
            if item.button:
                # Right-click on an Action Button enters edit mode (move/resize)
                # rather than opening the node context menu.
                item.enter_button_edit()
                event.accept()
                return
            self.node_context_requested.emit(item.node.id, event.globalPos())
            event.accept()
            return
        if isinstance(item, FrameItem):
            # Same split as the drag: the title bar is the frame, the body is
            # canvas. A frame is usually bigger than the screen, so treating
            # its whole rectangle as the frame meant that inside one — which
            # is exactly where you want to add the next node — the canvas
            # menu was unreachable.
            if item.chrome_at(item.mapFromScene(scene_pos)):
                self.frame_context_requested.emit(item.frame.id,
                                                  event.globalPos())
            else:
                self.add_node_requested.emit(scene_pos, event.globalPos())
            event.accept()
            return
        if isinstance(item, ConnectionItem) and item.is_order:
            self.order_context_requested.emit(item.conn.id, event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    # ---------------------------------------------------------- drag & drop

    def _matching_dropped_files(self, mime) -> list[str]:
        """Local paths in `mime` — files or folders — that map to a node."""
        if not mime.hasUrls():
            return []
        local_paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
        return [p for p in local_paths if resolve_dropped_path(p)]

    def dragEnterEvent(self, event) -> None:
        from .palette import FRAME_ID_MIME, NODE_TYPE_MIME
        from .shape_rail import SHAPE_KIND_MIME
        if event.mimeData().hasFormat(NODE_TYPE_MIME) \
                or event.mimeData().hasFormat(FRAME_ID_MIME) \
                or event.mimeData().hasFormat(SHAPE_KIND_MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            if self._matching_dropped_files(event.mimeData()):
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self.scene().clear_drop_hint()
        super().dragLeaveEvent(event)

    def dragMoveEvent(self, event) -> None:
        from .palette import FRAME_ID_MIME, NODE_TYPE_MIME
        from .shape_rail import SHAPE_KIND_MIME
        if event.mimeData().hasFormat(NODE_TYPE_MIME):
            # light up what this drop would do, so letting go is never a
            # guess: a green wire means splice, a ringed node means replace
            type_id = bytes(event.mimeData().data(NODE_TYPE_MIME)).decode()
            self.scene().set_drop_hint(self.scene().drop_target_at(
                type_id, self.mapToScene(event.position().toPoint())))
            event.acceptProposedAction()
        elif event.mimeData().hasFormat(FRAME_ID_MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasFormat(SHAPE_KIND_MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            if self._matching_dropped_files(event.mimeData()):
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        from .palette import FRAME_ID_MIME, NODE_TYPE_MIME
        from .shape_rail import SHAPE_KIND_MIME
        if event.mimeData().hasFormat(SHAPE_KIND_MIME):
            kind = bytes(event.mimeData().data(SHAPE_KIND_MIME)).decode()
            a = self.mapToScene(event.position().toPoint())
            w, h = (190.0, 90.0) if kind in ("line", "arrow") else (
                150.0, 46.0) if kind == "text" else (170.0, 110.0)
            self.shape_draw_requested.emit(
                kind, QRectF(a.x() - w / 2, a.y() - h / 2, w, h))
            self._arm_shape_draw(None)
            event.acceptProposedAction()
            return
        if event.mimeData().hasFormat(NODE_TYPE_MIME):
            type_id = bytes(event.mimeData().data(NODE_TYPE_MIME)).decode()
            scene_pos = self.mapToScene(event.position().toPoint())
            scene: NodeGraphScene = self.scene()
            scene.clear_drop_hint()
            # Alt drops past the aiming: a plain add exactly where released,
            # for parking a node on or beside a wire without touching it.
            target = None if (event.modifiers() & Qt.AltModifier) \
                else scene.drop_target_at(type_id, scene_pos)
            handled = False
            if target is not None:
                kind, obj = target
                if kind == "wire":
                    handled = scene.splice_into_wire(
                        type_id, obj.conn.id, scene_pos)
                else:
                    handled = scene.replace_node_with(type_id, obj.node.id)
            if not handled:
                self.node_dropped.emit(type_id, scene_pos)
            event.acceptProposedAction()
        elif event.mimeData().hasFormat(FRAME_ID_MIME):
            frame_id = bytes(event.mimeData().data(FRAME_ID_MIME)).decode()
            self.frame_dropped.emit(
                frame_id, self.mapToScene(event.position().toPoint()))
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            paths = self._matching_dropped_files(event.mimeData())
            if paths:
                self.files_dropped.emit(
                    paths, self.mapToScene(event.position().toPoint()))
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dropEvent(event)
