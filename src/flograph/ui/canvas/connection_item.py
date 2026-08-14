"""Bezier wires: committed connections and the live drag preview."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, Qt
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

    @property
    def src_anchor(self) -> PortItem:
        return self._src_anchor

    @property
    def dst_anchor(self) -> PortItem:
        return self._dst_anchor

    def update_path(self) -> None:
        self.setPath(bezier_path(self._src_anchor.scenePos(),
                                 self._dst_anchor.scenePos()))

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(self.path())

    def paint(self, painter: QPainter, option, widget=None) -> None:
        color = (theme.SELECTION_OUTLINE if self.isSelected()
                 else _color_for(self.src_port, self.dst_port))
        width = 3.0 if (self.isSelected() or self._hover) else 2.0
        scene = self.scene()
        threshold = getattr(scene, "lod_threshold", DEFAULT_LOD_THRESHOLD)
        lod_enabled = getattr(scene, "lod_enabled", True)
        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        if not lod_enabled or lod >= threshold:  # a bezier is indistinguishable
            painter.setRenderHint(QPainter.Antialiasing)  # from a line this small
        painter.setPen(QPen(color, width))
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
        if scene is not None:
            scene.insert_reroute(self.conn, event.scenePos())
        event.accept()


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
        self.setPath(bezier_path(a, b))
        color = (theme.WIRE_PENDING if valid is None
                 else theme.WIRE_VALID if valid else theme.WIRE_INVALID)
        pen = self.pen()
        pen.setColor(color)
        self.setPen(pen)
