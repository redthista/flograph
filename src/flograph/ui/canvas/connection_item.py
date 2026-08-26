"""Bezier wires: committed connections and the live drag preview."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsItem

from flograph.core import Connection, PortType

from .. import theme
from .node_item import DEFAULT_LOD_THRESHOLD, PortItem
from .stacking import PENDING_WIRE_Z, WIRE_Z


def bezier_path(start: QPointF, end: QPointF) -> QPainterPath:
    dx = end.x() - start.x()
    offset = max(40.0, min(160.0, abs(dx) * 0.5))
    path = QPainterPath(start)
    path.cubicTo(
        QPointF(start.x() + offset, start.y()),
        QPointF(end.x() - offset, end.y()),
        end,
    )
    return path


def order_path(start: QPointF, end: QPointF) -> QPainterPath:
    """The arc an order edge draws: up out of one node's top edge and down
    into the other's.

    Vertical control points, where `bezier_path` uses horizontal ones,
    because that is where the flow pins are — and because an order edge
    reading as an arc *over* the two nodes rather than a wire *between* them
    is most of what tells the two kinds apart at a glance. It carries no
    value, so it should not look like the wires that do.
    """
    lift = max(30.0, min(90.0, abs(end.x() - start.x()) * 0.25
                         + abs(end.y() - start.y()) * 0.25))
    path = QPainterPath(start)
    path.cubicTo(
        QPointF(start.x(), start.y() - lift),
        QPointF(end.x(), end.y() - lift),
        end,
    )
    return path


def _color_for(src: Optional[PortItem], dst: Optional[PortItem]) -> QColor:
    """A wire takes the color of its concrete end; ANY defers to the other."""
    types = [p.spec.type for p in (src, dst) if p is not None]
    concrete = [t for t in types if t != PortType.ANY]
    return theme.wire_color(concrete[0] if concrete else PortType.ANY)


class ConnectionItem(QGraphicsPathItem):
    def __init__(self, conn: Connection, src: PortItem, dst: PortItem) -> None:
        super().__init__()
        self.conn = conn
        self.src_port = src
        self.dst_port = dst
        # Where each end is *drawn*, which is not always its own pin: when a
        # node is folded inside a collapsed frame, its wires terminate on a
        # pin on that frame's box instead. Kept separate from src_port /
        # dst_port so identity and colour still come from the real ports.
        self._src_anchor = src
        self._dst_anchor = dst
        self._hover = False
        self._drop_hint = False
        self.setZValue(WIRE_Z)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.update_path()

    def set_anchors(self, src: Optional[PortItem] = None,
                    dst: Optional[PortItem] = None) -> None:
        """Redirect either end's drawn position. None restores the real port."""
        self._src_anchor = src if src is not None else self.src_port
        self._dst_anchor = dst if dst is not None else self.dst_port
        self.update_path()

    def reattach(self, src: PortItem, dst: PortItem) -> None:
        """Point both ends at freshly built port items.

        `NodeItem.rebuild_ports` replaces every PortItem, and a wire holding
        the old ones would keep drawing to orphaned ghosts — pins removed
        from the scene report their local coordinates, so the wire lands
        somewhere near the node's top-left corner instead of on a dot. An
        anchor that *is* the real port follows the rebuild; a FramePortItem
        anchor (the node folded inside a collapsed frame) is not the wire's
        business here — it stands where the frame put it.
        """
        if self._src_anchor is self.src_port:
            self._src_anchor = src
        if self._dst_anchor is self.dst_port:
            self._dst_anchor = dst
        self.src_port = src
        self.dst_port = dst
        self.update_path()

    @property
    def src_anchor(self) -> PortItem:
        return self._src_anchor

    @property
    def dst_anchor(self) -> PortItem:
        return self._dst_anchor

    @property
    def is_order(self) -> bool:
        """Whether this wire is an order edge rather than a data wire."""
        return self.src_port.spec.type == PortType.FLOW

    def update_path(self) -> None:
        draw = order_path if self.is_order else bezier_path
        self.setPath(draw(self._src_anchor.scenePos(),
                          self._dst_anchor.scenePos()))

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(self.path())

    def boundingRect(self) -> QRectF:
        # The inherited answer is the path's own rect, which ignores the
        # pen — and this wire paints up to 5px wide (hover, selection, the
        # splice hint) plus antialiasing spread. Fringe pixels outside the
        # damage region never get repainted when the wire moves: faint
        # skids across the canvas until a zoom or pan forces a full redraw.
        return self.path().boundingRect().adjusted(-4, -4, 4, 4)

    def set_drop_hint(self, on: bool) -> None:
        """Lit while a dragged node hovers over this wire: letting go here
        will splice the node into it. Green is the pending wire's valid
        colour — it answers the same question, "this drop will connect"."""
        if on != self._drop_hint:
            self._drop_hint = on
            self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        color = (theme.SELECTION_OUTLINE if self.isSelected()
                 else _color_for(self.src_port, self.dst_port))
        # thinner and dashed: an order edge is a constraint on the run, not a
        # path anything travels along, and it should stay quiet behind the
        # wires that do carry the data
        order = self.is_order
        width = (2.0 if order else 3.0) if (self.isSelected() or self._hover) \
            else (1.4 if order else 2.0)
        if self._drop_hint:
            # the splice target outranks selection styling while a node is
            # over it — this green is what says letting go is safe
            color = theme.WIRE_VALID
            width = 3.0 if order else 5.0
        scene = self.scene()
        threshold = getattr(scene, "lod_threshold", DEFAULT_LOD_THRESHOLD)
        lod_enabled = getattr(scene, "lod_enabled", True)
        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        if not lod_enabled or lod >= threshold:  # a bezier is indistinguishable
            painter.setRenderHint(QPainter.Antialiasing)  # from a line this small
        pen = QPen(color, width)
        if order:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        # A reroute dot passes a value along, so there is nothing for it to
        # do on an order edge — splitting one would only put a node in the
        # middle of a constraint.
        if (scene is not None and not self.is_order
                and not self._crosses_a_collapsed_frame()):
            scene.insert_reroute(self.conn, event.scenePos())
        event.accept()

    def _crosses_a_collapsed_frame(self) -> bool:
        """Whether either end is pinned to a folded frame.

        A reroute is inserted where the wire was double-clicked, which for
        the visible stub of a crossing wire is inside the collapsed frame's
        vacated region. The new node would not be hidden — it is not in the
        captured membership — so it would sit in apparently empty canvas,
        get swept up by anything that resolves the frame's nodes from its
        rect, and reappear inside the frame on expand.
        """
        return (self._src_anchor is not self.src_port
                or self._dst_anchor is not self.dst_port)


class PendingConnectionItem(QGraphicsPathItem):
    """The dashed preview while dragging a wire from a port."""

    def __init__(self, fixed_port: PortItem) -> None:
        super().__init__()
        self.fixed_port = fixed_port
        self.setZValue(PENDING_WIRE_Z)
        pen = QPen(theme.WIRE_PENDING, 2, Qt.DashLine)
        self.setPen(pen)

    def update_drag(self, cursor: QPointF, valid: Optional[bool]) -> None:
        start = self.fixed_port.scenePos()
        from_output = self.fixed_port.spec.direction.value == "output"
        a, b = (start, cursor) if from_output else (cursor, start)
        draw = (order_path if self.fixed_port.spec.type == PortType.FLOW
                else bezier_path)
        self.setPath(draw(a, b))
        color = (theme.WIRE_PENDING if valid is None
                 else theme.WIRE_VALID if valid else theme.WIRE_INVALID)
        pen = self.pen()
        pen.setColor(color)
        self.setPen(pen)
