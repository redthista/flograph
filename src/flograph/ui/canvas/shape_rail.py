"""The optional shape tool rail — a slim Miro-style strip of buttons over the
canvas. Experimental, off by default (Settings ▸ Canvas). A button can be
clicked (arms draw mode — the next click-drag rubber-bands out a shape) or
dragged straight onto the canvas.

Overlay widget parented to the view, positioned in the view's own
resizeEvent — the same pattern the minimap uses.
"""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QDrag, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import QButtonGroup, QFrame, QToolButton, QVBoxLayout

from .. import theme
from .shape_item import KIND_LABELS

#: Carries the shape kind when a rail button is dragged onto the canvas.
SHAPE_KIND_MIME = "application/x-flograph-shape-kind"

_KINDS = ("rect", "rounded", "ellipse", "diamond", "triangle",
          "line", "arrow", "text")


def _glyph(kind: str) -> QIcon:
    px = QPixmap(20, 20)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(theme.NODE_TEXT, 1.6)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    r = QRectF(3, 3, 14, 14)
    if kind == "rect":
        p.drawRect(r)
    elif kind == "rounded":
        p.drawRoundedRect(r, 4, 4)
    elif kind == "ellipse":
        p.drawEllipse(r)
    elif kind == "diamond":
        p.drawPolygon(QPolygonF([QPointF(10, 3), QPointF(17, 10),
                                 QPointF(10, 17), QPointF(3, 10)]))
    elif kind == "triangle":
        p.drawPolygon(QPolygonF([QPointF(10, 3), QPointF(17, 17),
                                 QPointF(3, 17)]))
    elif kind == "line":
        p.drawLine(4, 16, 16, 4)
    elif kind == "arrow":
        p.drawLine(4, 16, 16, 4)
        path = QPainterPath(QPointF(16, 4))
        path.lineTo(11, 5)
        path.moveTo(16, 4)
        path.lineTo(15, 9)
        p.drawPath(path)
    elif kind == "text":
        f = p.font()
        f.setBold(True)
        f.setPointSize(12)
        p.setFont(f)
        p.drawText(px.rect(), Qt.AlignCenter, "T")
    p.end()
    return QIcon(px)


class _ToolButton(QToolButton):
    """A rail button that also starts a drag carrying its shape kind, so the
    tool can be dropped straight onto the canvas instead of armed first."""

    def __init__(self, kind: str, parent=None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._press: QPoint | None = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (self._press is not None
                and (event.position().toPoint() - self._press).manhattanLength()
                >= 8):
            self._press = None
            self.setDown(False)
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(SHAPE_KIND_MIME, self._kind.encode())
            drag.setMimeData(mime)
            drag.setPixmap(self.icon().pixmap(20, 20))
            drag.exec(Qt.CopyAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press = None
        super().mouseReleaseEvent(event)


class ShapeRail(QFrame):
    """Emits `tool_armed(kind)` when a tool is picked and `tool_disarmed()`
    when it is switched off."""

    tool_armed = Signal(str)
    tool_disarmed = Signal()

    def __init__(self, view) -> None:
        super().__init__(view)
        self._view = view
        self.setObjectName("shape_rail")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "#shape_rail { background: rgba(30,32,38,0.92);"
            " border: 1px solid #3b3d46; border-radius: 7px; }"
            " QToolButton { border: none; border-radius: 5px; padding: 3px; }"
            " QToolButton:hover { background: #3a3d47; }"
            " QToolButton:checked { background: #4b4e58; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for kind in _KINDS:
            btn = _ToolButton(kind, self)
            btn.setCheckable(True)
            btn.setIcon(_glyph(kind))
            btn.setToolTip(
                f"{KIND_LABELS[kind]} — click to arm, or drag onto the canvas")
            btn.clicked.connect(
                lambda checked, k=kind, b=btn: self._on_click(k, b, checked))
            layout.addWidget(btn)
            self._group.addButton(btn)
        self.adjustSize()

    def _on_click(self, kind: str, button, checked: bool) -> None:
        if not checked:                    # clicking the active tool turns it off
            self.tool_disarmed.emit()
            return
        self.tool_armed.emit(kind)

    def clear_selection(self) -> None:
        """Drop the armed tool without re-emitting — the view calls this when
        draw mode ends by Esc or by finishing a shape."""
        checked = self._group.checkedButton()
        if checked is not None:
            self._group.setExclusive(False)
            checked.setChecked(False)
            self._group.setExclusive(True)

    def reposition(self) -> None:
        self.adjustSize()
        self.move(12, 64)
