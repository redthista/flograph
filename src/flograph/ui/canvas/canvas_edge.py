"""The edge of a model canvas, seen from inside it (G13).

A frame turned into a model canvas shows its declared ports as pins on the
box. From inside — on the canvas the contents moved to — those same ports
need saying too, or the canvas is a block of flow with wires that stop at
nothing and no sign of what reaches the outside.

So each declared port draws a small pill beside the inner port it names:
to the left of an input, to the right of an output, pointing the way the
data goes. Chrome, not an item of the graph: nothing selects it, drags it
or wires to it — the wiring end of a port is the node's own pin, exactly
as it is for a node with no box around it.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem

from .. import theme

PAD_X = 7.0
PAD_Y = 3.0
GAP = 14.0          # between the pill and the port it names
ARROW = 7.0
MAX_W = 150.0
#: Above the nodes: a pill tucked behind a card would say nothing at all.
MARKER_Z = 9_000.0


def _font() -> QFont:
    font = QFont()
    font.setPointSizeF(8.5)
    return font


class CanvasEdgeMarker(QGraphicsItem):
    """One declared port of the box, drawn beside the port it stands for."""

    def __init__(self, name: str, side: str, color: str = "") -> None:
        super().__init__()
        self.name = name
        self.side = side                  # "input" | "output"
        self._color = QColor(color) if color else QColor(theme.BUTTON_ACCENT)
        self.setZValue(MARKER_Z)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setToolTip(
            f"“{name}” — {'into' if side == 'input' else 'out of'} this "
            f"canvas, through its box")

    def _text(self) -> str:
        metrics = QFontMetricsF(_font())
        return metrics.elidedText(self.name, Qt.ElideRight, MAX_W)

    def _size(self) -> tuple:
        metrics = QFontMetricsF(_font())
        return (metrics.horizontalAdvance(self._text()) + 2 * PAD_X + ARROW,
                metrics.height() + 2 * PAD_Y)

    def boundingRect(self) -> QRectF:
        width, height = self._size()
        # drawn from its own origin, which the scene puts at the end nearest
        # the port: leftwards for an input, rightwards for an output
        left = -width if self.side == "input" else 0.0
        return QRectF(left - 1, -height / 2 - 1, width + 2, height + 2)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        width, height = self._size()
        left = -width if self.side == "input" else 0.0
        body = QRectF(left, -height / 2, width, height)
        painter.setRenderHint(QPainter.Antialiasing)
        fill = theme.tint(theme.CANVAS_BG, self._color, theme.TINT_SOFT)
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(self._color, 1.0))
        painter.drawRoundedRect(body, height / 2, height / 2)

        # the arrow points the way the data travels: in from the left, out
        # to the right, so a glance says which side of the block this is
        painter.setPen(QPen(theme.NODE_TEXT, 1.4))
        tip_x = (body.right() - PAD_X if self.side == "input"
                 else body.left() + PAD_X + ARROW)
        back_x = tip_x - ARROW if self.side == "input" else tip_x - ARROW
        painter.drawLine(QPointF(back_x, 0.0), QPointF(tip_x, 0.0))
        for dy in (-3.0, 3.0):
            painter.drawLine(QPointF(tip_x, 0.0),
                             QPointF(tip_x - 3.5, dy))

        painter.setFont(_font())
        painter.setPen(QPen(theme.NODE_TEXT))
        text_rect = QRectF(body.left() + PAD_X, body.top(),
                           body.width() - 2 * PAD_X - ARROW, body.height())
        if self.side == "input":
            text_rect.translate(0.0, 0.0)
        else:
            text_rect.translate(ARROW, 0.0)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft,
                         self._text())
