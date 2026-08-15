"""The dashed line a Goto/From pair draws when asked to.

A named link is a wire the canvas deliberately doesn't draw — that is what
it is *for*, and it is why the two cards glow at each other when either is
selected instead. But a glow only answers "is there a partner"; on a canvas
where the partner is three screens away it cannot answer "which one, and
where". Turning `show_lines` on for either end (right-click either card, or
tick it in the properties panel) draws the line for that link and no other,
so one confusing pair can be traced without the canvas going back to being
the plate of spaghetti the links were introduced to avoid.

The line is drawn, never dragged: it has no ports to grab, cannot be
selected, cut or hovered, and takes no mouse events at all. Deleting it
means turning the toggle back off.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem

from .. import theme
from .connection_item import bezier_path
from .stacking import LINK_LINE_Z

#: Where along the curve the direction arrow sits. Just past the middle:
#: at the very end it would be hidden under the From card.
_ARROW_AT = 0.55
#: Length of the arrow, and how wide it is across the base as a fraction of
#: that. Half as wide as it is long: at the equilateral proportions this
#: started with, every vertex looks equally like the point, and the arrow
#: stops saying anything about direction.
_ARROW_SIZE = 13.0
_ARROW_HALF_WIDTH = 0.32

#: Param both link cards carry; True on *either* end draws the line.
SHOW_LINES_PARAM = "show_lines"


def wants_lines(node) -> bool:
    return bool(node.params.get(SHOW_LINES_PARAM, False))


class LinkLineItem(QGraphicsPathItem):
    """One Goto -> From link, drawn between the two cards' facing edges.

    Endpoints come from the *cards*, not from ports: a Goto has no output
    pin on the canvas and a From has no input pin (see links.py), which is
    exactly why this cannot reuse ConnectionItem.
    """

    def __init__(self, link_id: str, src_item, dst_item, label: str) -> None:
        super().__init__()
        self.link_id = link_id
        self.src_item = src_item
        self.dst_item = dst_item
        # A card folded inside a collapsed frame draws its end of the line on
        # a pin on that frame's box instead of on itself — same indirection
        # ConnectionItem uses, and for the same reason.
        self._src_anchor = None
        self._dst_anchor = None
        self.setZValue(LINK_LINE_Z)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setAcceptHoverEvents(False)
        self.setToolTip(f"Link: {label}")
        self.update_path()

    def set_anchors(self, src=None, dst=None) -> None:
        """Redirect either end. None restores the card's own edge."""
        self._src_anchor = src
        self._dst_anchor = dst
        self.update_path()

    def update_path(self) -> None:
        self.setPath(bezier_path(self._start(), self._end()))

    def _start(self) -> QPointF:
        if self._src_anchor is not None:
            return self._src_anchor.scenePos()
        item = self.src_item
        return item.mapToScene(QPointF(item.width, item.body_height / 2.0))

    def _end(self) -> QPointF:
        if self._dst_anchor is not None:
            return self._dst_anchor.scenePos()
        item = self.dst_item
        return item.mapToScene(QPointF(0.0, item.body_height / 2.0))

    def paint(self, painter: QPainter, option, widget=None) -> None:
        path = self.path()
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(theme.SELECTION_OUTLINE, 1.6, Qt.DashLine)
        pen.setDashPattern([5.0, 4.0])
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        # Which way the value flows. A wire is read left to right from its
        # pins; this has none, and a link between two cards sitting the
        # wrong way round on the canvas would otherwise be ambiguous.
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.SELECTION_OUTLINE)
        painter.drawPolygon(self._arrow_head(path))

    def _arrow_head(self, path: QPainterPath) -> QPolygonF:
        """A triangle pointing the way the value travels.

        Built from two points on the curve rather than from
        angleAtPercent(): that angle is measured counter-clockwise about a
        y-axis pointing *up*, while the scene's y grows down, and the sign
        juggling that reconciles them produced an arrow aimed confidently
        back at the Goto. Subtracting two points cannot be got backwards.
        """
        from math import hypot
        step = 0.02
        behind = path.pointAtPercent(max(0.0, _ARROW_AT - step))
        ahead = path.pointAtPercent(min(1.0, _ARROW_AT + step))
        dx, dy = ahead.x() - behind.x(), ahead.y() - behind.y()
        length = hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length     # unit vector along the travel
        nx, ny = -uy, ux                      # and across it
        point = path.pointAtPercent(_ARROW_AT)
        tip = QPointF(point.x() + ux * _ARROW_SIZE * 0.5,
                      point.y() + uy * _ARROW_SIZE * 0.5)
        base = QPointF(tip.x() - ux * _ARROW_SIZE,
                       tip.y() - uy * _ARROW_SIZE)
        half = _ARROW_SIZE * _ARROW_HALF_WIDTH
        return QPolygonF([
            tip,
            QPointF(base.x() + nx * half, base.y() + ny * half),
            QPointF(base.x() - nx * half, base.y() - ny * half),
        ])
